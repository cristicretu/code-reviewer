from smolagents import Tool
import subprocess
import os

class RunTestsTool(Tool):
    name = "run_tests"
    description = "run the test suite against the patch"
    inputs = {
        "target": {"type": "string", "description": "target subset", "nullable": True},
        "changed_only": {"type": "boolean", "description": "only changed", "nullable": True}
    }
    output_type = "string"

    def forward(self, target: str = None, changed_only: bool = True) -> str:
        try:
            cmd = ["pytest"]
            if target:
                cmd.append(target)
            result = subprocess.run(cmd, capture_output=True, text=True)
            return result.stdout or result.stderr
        except Exception as e:
            return str(e)

class RunLinterTool(Tool):
    name = "run_linter"
    description = "static analysis on the patch"
    inputs = {
        "path": {"type": "string", "description": "path to run", "nullable": True}
    }
    output_type = "string"

    def forward(self, path: str = None) -> str:
        try:
            cmd = ["ruff", "check"]
            if path:
                cmd.append(path)
            else:
                cmd.append(".")
            result = subprocess.run(cmd, capture_output=True, text=True)
            return result.stdout or result.stderr
        except Exception as e:
            return str(e)

class RunTypecheckTool(Tool):
    name = "run_typecheck"
    description = "run typecheck"
    inputs = {
        "path": {"type": "string", "description": "path to typecheck", "nullable": True}
    }
    output_type = "string"

    def forward(self, path: str = None) -> str:
        try:
            cmd = ["mypy"]
            if path:
                cmd.append(path)
            else:
                cmd.append(".")
            result = subprocess.run(cmd, capture_output=True, text=True)
            return result.stdout or result.stderr
        except Exception as e:
            return str(e)

class RunSnippetTool(Tool):
    name = "run_snippet"
    description = "sandboxed REPL/exec for tiny reproductions"
    inputs = {
        "language": {"type": "string", "description": "programming language"},
        "code": {"type": "string", "description": "code to run"}
    }
    output_type = "string"

    def forward(self, language: str, code: str) -> str:
        if language not in ("python", "python3"):
            return "Unsupported language"
        filepath = "/tmp/snippet.py"
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(code)
            result = subprocess.run(["python3", filepath], capture_output=True, text=True, timeout=5)
            return result.stdout or result.stderr
        except Exception as e:
            return str(e)
        finally:
            if os.path.exists(filepath):
                os.remove(filepath)
