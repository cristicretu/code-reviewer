from agentic.tools.retrieval import SemanticSearchTool, SearchKeywordTool, SearchSymbolTool, GetFileTool
from agentic.tools.execution import RunTestsTool, RunLinterTool, RunTypecheckTool, RunSnippetTool
from agentic.tools.history import CheckHistoryTool, GetPrMetadataTool, GetTeamConventionsTool
from agentic.tools.action import PostCommentTool, RequestChangesTool, ApproveTool, CommentOnlyTool, ProposePatchTool
from agentic.tools.skills import LoadSkillTool

TOOLS = [
    SemanticSearchTool(), SearchKeywordTool(), SearchSymbolTool(), GetFileTool(),
    RunTestsTool(), RunLinterTool(), RunTypecheckTool(), RunSnippetTool(),
    CheckHistoryTool(), GetPrMetadataTool(), GetTeamConventionsTool(),
    LoadSkillTool(),
    PostCommentTool(), RequestChangesTool(), ApproveTool(), CommentOnlyTool(), ProposePatchTool(),
]
