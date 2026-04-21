from smolagents import CodeAgent, LiteLLMModel
from config import API_BASE, MODEL_ID
from tools import TOOLS

model = LiteLLMModel(model_id=MODEL_ID, api_base=API_BASE)
agent = CodeAgent(tools=TOOLS, model=model)

if __name__ == "__main__":
    result = agent.run("Perform a PR review")
    print(result)
