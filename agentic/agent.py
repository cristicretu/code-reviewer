from smolagents import CodeAgent, LiteLLMModel

from agentic.config import API_BASE, MODEL_ID
from agentic.tools import TOOLS


def build_model():
    return LiteLLMModel(model_id=MODEL_ID, api_base=API_BASE)


def build_agent():
    return CodeAgent(tools=TOOLS, model=build_model())


if __name__ == "__main__":
    agent = build_agent()
    result = agent.run("Perform a PR review")
    print(result)
