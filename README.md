# code-reviewer

The scope of our project is to create a Code Review Agent that is triggered as a Github Action when a pull request is opened or a new commit is pushed to an existing pull request. 

## Model 
We pick the open source [Qwen3.5-9B](https://huggingface.co/Qwen/Qwen3.5-9B) model, the 9B parameters large language model series developed by Qwen team, Alibaba Cloud. 

## Finetuning
We finetune our model on the [CodeReviewer dataset](https://zenodo.org/records/6900648), which contains data for 3 tasks -- Quality Estimation, Comment Generation and Code Refinement. We work with the Comment Generation split. As a finetuning strategy, we use QLoRA (Quantized Low-Rank Adaptation). 

## RAG
We incorporate RAG within our agent in order to obtain more reliable answers, grounded in the codebase. 
When integrating the agent, we chunk the repository using language-aware, recursive splitting by LangChain, which splits at class and function boundaries before falling back to lines splits. Afterwards, we generate embeddings using [nomic-ai/CodeRankEmbed](https://huggingface.co/nomic-ai/CodeRankEmbed), which we store inside a ChromaDB vector database. At query time, we embed the PR diff and use it as a query against the indexed codebase, retrieving the 5 most relevant code chunks to inject as context into the review prompt.

## Team
Name of the team is Messi. Members are (alphabetically) Cretu Cristian, Cretu Luca, Greholea Denis, Gosa Bogdan, Hiticas Paul.
