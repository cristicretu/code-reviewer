from smolagents import Tool

from agentic.skills.loader import load_skill_body


class LoadSkillTool(Tool):
    name = "load_skill"
    description = (
        "Pull a senior-reviewer's framework-specific playbook into your context. "
        "Each playbook captures 5-10 framework-specific bugs that linters miss "
        "(e.g. React stale closures, Vite's VITE_ prefix gotcha, Supabase channel cleanup). "
        "Strongly recommended as your FIRST step when AVAILABLE PLAYBOOKS lists a "
        "skill matching the diff -- it's faster than re-deriving framework conventions "
        "from raw code. Pick names from AVAILABLE PLAYBOOKS in the task prompt."
    )
    inputs = {
        "name": {
            "type": "string",
            "description": "skill name from AVAILABLE PLAYBOOKS (e.g. 'react', 'vite', 'supabase')",
        },
    }
    output_type = "string"

    def __init__(self):
        super().__init__()
        self._loaded: set[str] = set()

    def forward(self, name: str) -> str:
        normalized = name.strip().lower()
        if normalized in self._loaded:
            return (
                f"Skill '{name}' was already loaded earlier in this conversation; skipping. "
                "It is still in your context above -- scroll back to consult it."
            )
        body = load_skill_body(name)
        if body is None:
            return f"No skill named '{name}'. Check AVAILABLE PLAYBOOKS for available names."
        self._loaded.add(normalized)
        return body
