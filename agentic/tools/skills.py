from smolagents import Tool

from agentic.skills.loader import load_skill_body


class LoadSkillTool(Tool):
    name = "load_skill"
    description = (
        "Load the full body of a STACK PLAYBOOK skill into your context. "
        "Use only when you suspect the diff exercises the patterns covered by that skill -- "
        "skill bodies are large and consume context budget. "
        "Pick names from the STACK PLAYBOOK CATALOG in the task prompt."
    )
    inputs = {
        "name": {
            "type": "string",
            "description": "skill name from the catalog (e.g. 'react', 'vite', 'supabase')",
        },
    }
    output_type = "string"

    def forward(self, name: str) -> str:
        body = load_skill_body(name)
        if body is None:
            return f"No skill named '{name}'. Check the STACK PLAYBOOK CATALOG for available names."
        return body
