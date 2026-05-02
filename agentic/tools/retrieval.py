from smolagents import Tool
import os
import requests
import subprocess
import ast

class SemanticSearchTool(Tool):
    name = "semantic_search"
    description = "vector RAG over the chunked codebase index"
    inputs = {
        "query": {"type": "string", "description": "query string"},
        "k": {"type": "integer", "description": "num results", "nullable": True}
    }
    output_type = "string"

    def forward(self, query: str, k: int = 10) -> str:
        rag_url = os.environ.get("RAG_URL", "http://localhost:8000").rstrip("/")
        repo_id = os.environ.get("REPO_ID", "default_repo")
        k = max(1, min(int(k), 20))
        try:
            response = requests.post(
                f"{rag_url}/api/v1/retrieve/{repo_id}",
                json={"query": query, "max_results": k},
                timeout=30,
            )
            response.raise_for_status()
            return str(response.json())
        except Exception as e:
            return f"semantic_search failed: {e}"

class SearchKeywordTool(Tool):
    name = "search_keyword"
    description = "ripgrep across the repo"
    inputs = {
        "pattern": {"type": "string", "description": "pattern to search"},
        "path_glob": {"type": "string", "description": "path glob", "nullable": True},
        "regex": {"type": "boolean", "description": "regex mode", "nullable": True}
    }
    output_type = "string"

    def forward(self, pattern: str, path_glob: str = None, regex: bool = False) -> str:
        try:
            cmd = ["grep", "-rn", pattern, "."]
            if path_glob:
                cmd = ["grep", "-rn", "--include", path_glob, pattern, "."]
            result = subprocess.run(cmd, capture_output=True, text=True)
            return result.stdout or "No matches found"
        except Exception as e:
            return str(e)

class SearchSymbolTool(Tool):
    name = "search_symbol"
    description = "LSP/tree-sitter lookup for definitions of symbols"
    inputs = {
        "name": {"type": "string", "description": "symbol name"},
        "kind": {"type": "string", "description": "symbol kind", "nullable": True}
    }
    output_type = "string"

    def forward(self, name: str, kind: str = None) -> str:
        results = []
        for root_dir, _, files in os.walk("."):
            for f in files:
                if f.endswith(".py"):
                    path = os.path.join(root_dir, f)
                    try:
                        with open(path, "r", encoding="utf-8") as file_obj:
                            tree = ast.parse(file_obj.read())
                            for node in ast.walk(tree):
                                if isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)):
                                    if node.name == name:
                                        results.append(f"{path}:{node.lineno} {node.name}")
                    except Exception:
                        pass
        return "\n".join(results) if results else f"Symbol {name} not found"

class GetFileTool(Tool):
    name = "get_file"
    description = "fetch full file or a span"
    inputs = {
        "path": {"type": "string", "description": "filepath"},
        "line_range": {"type": "string", "description": "line range string like '5-10'", "nullable": True}
    }
    output_type = "string"

    def forward(self, path: str, line_range: str = None) -> str:
        try:
            with open(path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            if line_range:
                start, end = map(int, line_range.split("-"))
                lines = lines[start - 1 : end]
            return "".join(lines)
        except Exception as e:
            return str(e)
