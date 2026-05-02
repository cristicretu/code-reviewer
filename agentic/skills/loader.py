"""Skill detection + on-demand loading.

A skill is a markdown file under agentic/skills/ with YAML-style frontmatter
declaring trigger conditions.

Two-stage design (so we don't blow up the agent's context window):

1. `detect_skills(workspace, diff)` runs at task setup. It parses the consumer
   repo's manifest files (package.json, pyproject.toml, Cargo.toml, go.mod) plus
   the changed-file extensions and returns a tiny *catalog* of matching skills:
   each entry is just (name, description). The catalog gets injected into the
   system prompt under "STACK PLAYBOOK CATALOG". This costs ~one line per skill.

2. `load_skill(name)` is exposed to the agent as the LoadSkillTool. The agent
   calls it when it actually wants the playbook body (e.g. when reviewing a hunk
   that uses `useEffect`, it loads the `react` skill). Bodies enter the
   conversation only on demand.
"""

import json
import os
import re
from pathlib import Path
from typing import Iterable, List, NamedTuple, Optional

from loguru import logger

_SKILLS_DIR = Path(__file__).parent
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)


class SkillEntry(NamedTuple):
    name: str
    description: str


def _parse_frontmatter(skill_path: Path) -> tuple[dict, str]:
    """Lightweight YAML-ish frontmatter parser.

    Only handles the shape we use: top-level scalar keys plus a `triggers:`
    block whose values are either lists of strings or scalars. Avoids a PyYAML
    dependency for one tiny use case.
    """
    text = skill_path.read_text(encoding="utf-8")
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    raw_meta, body = m.group(1), m.group(2)

    meta: dict = {}
    triggers: dict = {}
    current_section: Optional[str] = None
    for line in raw_meta.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line.startswith(" "):
            key, _, val = line.partition(":")
            key = key.strip()
            val = val.strip()
            if key == "triggers":
                current_section = "triggers"
                continue
            current_section = None
            meta[key] = val
        elif current_section == "triggers":
            stripped = line.strip()
            if not stripped or ":" not in stripped:
                continue
            tkey, _, tval = stripped.partition(":")
            tkey = tkey.strip()
            tval = tval.strip()
            if tval.startswith("[") and tval.endswith("]"):
                items = [
                    p.strip().strip('"').strip("'")
                    for p in tval[1:-1].split(",")
                    if p.strip()
                ]
                triggers[tkey] = items
            else:
                triggers[tkey] = tval.strip('"').strip("'")
    if triggers:
        meta["triggers"] = triggers
    return meta, body


def _load_package_deps(workspace: Path) -> set[str]:
    pkg = workspace / "package.json"
    if not pkg.exists():
        return set()
    try:
        data = json.loads(pkg.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"Could not parse {pkg}: {e}")
        return set()
    deps: set[str] = set()
    deps.update((data.get("dependencies") or {}).keys())
    deps.update((data.get("devDependencies") or {}).keys())
    deps.update((data.get("peerDependencies") or {}).keys())
    return deps


def _load_pyproject_deps(workspace: Path) -> set[str]:
    pyp = workspace / "pyproject.toml"
    if not pyp.exists():
        return set()
    deps: set[str] = set()
    try:
        text = pyp.read_text(encoding="utf-8")
    except Exception:
        return deps
    for m in re.finditer(r'^\s*([a-zA-Z0-9_.-]+)\s*=\s*"', text, flags=re.MULTILINE):
        deps.add(m.group(1).lower())
    for m in re.finditer(r'"([a-zA-Z0-9_.-]+)\s*[<>=!~]', text):
        deps.add(m.group(1).lower())
    return deps


def _load_cargo_deps(workspace: Path) -> set[str]:
    cargo = workspace / "Cargo.toml"
    if not cargo.exists():
        return set()
    deps: set[str] = set()
    try:
        text = cargo.read_text(encoding="utf-8")
    except Exception:
        return deps
    in_deps = False
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("[") and s.endswith("]"):
            in_deps = "dependencies" in s
            continue
        if in_deps and "=" in s and not s.startswith("#"):
            deps.add(s.split("=", 1)[0].strip().strip('"'))
    return deps


def _load_go_modules(workspace: Path) -> set[str]:
    gomod = workspace / "go.mod"
    if not gomod.exists():
        return set()
    mods: set[str] = set()
    try:
        text = gomod.read_text(encoding="utf-8")
    except Exception:
        return mods
    for m in re.finditer(r"^\s*([\w./-]+)\s+v[\w.+-]+", text, flags=re.MULTILINE):
        mods.add(m.group(1))
    return mods


def _diff_extensions(diff: str) -> set[str]:
    exts: set[str] = set()
    for line in diff.splitlines():
        if line.startswith("diff --git ") or line.startswith("+++ b/"):
            for tok in line.split():
                if "." in tok:
                    base = tok.rsplit("/", 1)[-1]
                    if "." in base:
                        exts.add("." + base.rsplit(".", 1)[-1].rstrip(","))
    return exts


def _matches(triggers: dict, ctx: dict) -> bool:
    if not triggers:
        return False
    for key, val in triggers.items():
        wanted = val if isinstance(val, list) else [val]
        if key == "package_json_dep":
            if any(w in ctx["package_deps"] for w in wanted):
                return True
        elif key == "package_json_dep_prefix":
            for w in wanted:
                if any(d.startswith(w) for d in ctx["package_deps"]):
                    return True
        elif key == "pyproject_dep":
            if any(w.lower() in ctx["pyproject_deps"] for w in wanted):
                return True
        elif key == "cargo_dep":
            if any(w in ctx["cargo_deps"] for w in wanted):
                return True
        elif key == "go_mod_module":
            if any(w in ctx["go_mods"] for w in wanted):
                return True
        elif key == "files":
            if any((ctx["workspace"] / w).exists() for w in wanted):
                return True
        elif key == "diff_extensions":
            if any(w in ctx["diff_exts"] for w in wanted):
                return True
    return False


def detect_skills(
    workspace: Optional[Path] = None,
    diff: str = "",
) -> List[SkillEntry]:
    """Return a tiny catalog of skills that *could* be relevant to this PR.

    Each entry is just (name, description). Bodies are NOT loaded -- the agent
    fetches them on demand via load_skill().
    """
    workspace = workspace or Path(os.environ.get("REPO_PATH", ".")).resolve()
    ctx = {
        "workspace": workspace,
        "package_deps": _load_package_deps(workspace),
        "pyproject_deps": _load_pyproject_deps(workspace),
        "cargo_deps": _load_cargo_deps(workspace),
        "go_mods": _load_go_modules(workspace),
        "diff_exts": _diff_extensions(diff),
    }

    matched: List[SkillEntry] = []
    for skill_path in sorted(_SKILLS_DIR.glob("*.md")):
        if skill_path.name.lower() == "readme.md":
            continue
        meta, _body = _parse_frontmatter(skill_path)
        if not isinstance(meta, dict):
            continue
        triggers = meta.get("triggers", {})
        if not _matches(triggers, ctx):
            continue
        name = meta.get("name") or skill_path.stem
        desc = (meta.get("description") or "").strip()
        matched.append(SkillEntry(name=name, description=desc))
    return matched


def load_skill_body(name: str) -> Optional[str]:
    """Return the body of the skill with the given name, or None if not found."""
    safe = re.sub(r"[^a-zA-Z0-9_-]", "", name).lower()
    if not safe:
        return None
    candidates = [_SKILLS_DIR / f"{safe}.md"]
    for path in _SKILLS_DIR.glob("*.md"):
        if path.name.lower() == "readme.md":
            continue
        meta, _body = _parse_frontmatter(path)
        if isinstance(meta, dict) and (meta.get("name") or "").strip().lower() == safe:
            candidates.append(path)
    for path in candidates:
        if path.exists():
            _meta, body = _parse_frontmatter(path)
            return body.strip()
    return None


def format_skills_catalog(skills: Iterable[SkillEntry]) -> str:
    skills = list(skills)
    if not skills:
        return ""
    lines = [
        "",
        "AVAILABLE PLAYBOOKS",
        "=" * 19,
        "",
        "Senior reviewers maintain framework-specific playbooks of bugs that",
        "linters miss. The following match this PR's stack (detected from",
        "package.json / pyproject / Cargo / go.mod and the diff's file types):",
        "",
    ]
    for entry in skills:
        lines.append(f'  load_skill("{entry.name}")')
        lines.append(f"      {entry.description}")
        lines.append("")
    lines.extend(
        [
            "Each playbook is roughly 70 lines. Loading the right one for this",
            "stack early in your review typically reveals 3-5 bug classes you",
            "would otherwise have to spot from raw code reading. A skill you do",
            "not load does not enter your context.",
            "",
        ]
    )
    return "\n".join(lines)
