# Skills

Each skill is a single markdown file that captures the gotchas a careful reviewer
would check for when reviewing code touching a specific framework or pattern.

The agent does not load all skills on every PR. At task setup, `loader.py` reads
the consumer repo's manifest files (`package.json`, `pyproject.toml`, `Cargo.toml`,
`go.mod`) plus the changed-file extensions, matches them against each skill's
frontmatter triggers, and injects the bodies of matching skills into the system
prompt under a `STACK PLAYBOOK` section. The agent log records which skills loaded.

## File format

```markdown
---
name: react
description: React lifecycle, effects, closures, and rendering gotchas
triggers:
  package_json_dep: ["react"]
  diff_extensions: [".tsx", ".jsx"]
---

# React

[skill content -- aim for ~80 lines, not exhaustive, focus on the bugs a
careful senior reviewer would actually flag and a basic linter would not.]

## Sources

- [React docs: ...](https://react.dev/...)
```

## Trigger fields

| Field | Matches when |
| --- | --- |
| `package_json_dep` | Any listed string is a key under `dependencies` or `devDependencies` in `package.json`. |
| `package_json_dep_prefix` | Any dep key starts with the listed prefix (e.g. `@supabase/`). |
| `pyproject_dep` | Any listed string is a top-level dependency in `pyproject.toml`. |
| `cargo_dep` | Any listed string is a key under `[dependencies]` in `Cargo.toml`. |
| `go_mod_module` | Any listed string appears as a `require` path in `go.mod`. |
| `files` | Any listed file exists at the consumer-repo root. |
| `diff_extensions` | Any changed file in the diff has the listed extension. |

A skill matches if **any** trigger matches (OR semantics, not AND).

## Adding a new skill

1. Drop `agentic/skills/<name>.md` with the frontmatter above.
2. Keep it tight (~60–120 lines). Fewer, sharper bullets beat exhaustive coverage.
3. Cite official sources at the bottom so future authors can update from the source of truth.
4. The skill loads automatically on the next run -- no code changes required.
