import requests
from loguru import logger
from src.config_manager import settings

API_URL = f"http://{settings.DEFAULT.HOST}:{settings.DEFAULT.PORT}/api/v1/ingest"
REPO_ID = "calico-ai"
GITHUB_OWNER = "bogdangosa"
GITHUB_REPO = "calico-ai"
GITHUB_BRANCH = "master"
SUPPORTED_EXTENSIONS = tuple(settings.INGESTION.SUPPORTED_EXTENSIONS)
GITHUB_TOKEN = ""


def fetch_repository_tree(owner, repo, branch, token):
    tree_url = f"https://api.github.com/repos/{owner}/{repo}/git/trees/{branch}?recursive=1"
    headers = {"Authorization": f"token {token}"} if token else {}

    response = requests.get(tree_url, headers=headers)
    if response.status_code != 200:
        logger.error(f"Failed to fetch tree. Status: {response.status_code}, Body: {response.text}")
        return []

    return response.json().get("tree", [])


def fetch_raw_file_content(owner, repo, branch, file_path, token):
    raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{file_path}"
    headers = {"Authorization": f"token {token}"} if token else {}

    response = requests.get(raw_url, headers=headers)
    if response.status_code == 200:
        return response.text
    return None


def ingest_from_github():
    logger.info(f"Fetching repository tree from GitHub: {GITHUB_OWNER}/{GITHUB_REPO}")
    repository_tree = fetch_repository_tree(GITHUB_OWNER, GITHUB_REPO, GITHUB_BRANCH, GITHUB_TOKEN)

    if not repository_tree:
        logger.error("No files found or unable to access repository tree.")
        return

    files_found = 0

    for item in repository_tree:
        if item["type"] != "blob":
            continue

        file_path = item["path"]

        if file_path.endswith(SUPPORTED_EXTENSIONS):
            files_found += 1
            logger.debug(f"Downloading candidate: {file_path}")

            code_content = fetch_raw_file_content(GITHUB_OWNER, GITHUB_REPO, GITHUB_BRANCH, file_path, GITHUB_TOKEN)

            if not code_content or not code_content.strip():
                logger.warning(f"Skipping empty or inaccessible file: {file_path}")
                continue

            payload = {
                "snippets": [
                    {
                        "file_path": file_path,
                        "content": code_content,
                        "metadata": {
                            "language": file_path.split('.')[-1],
                            "document_id": file_path
                        }
                    }
                ]
            }

            response = requests.post(f"{API_URL}/{REPO_ID}", json=payload)

            if response.status_code == 200:
                logger.success(f"Ingested: {file_path}")
            else:
                logger.error(f"Failed to ingest {file_path}: {response.text}")

    logger.info(f"Total supported files downloaded and scanned: {files_found}")


if __name__ == "__main__":
    logger.info(f"Starting direct GitHub ingestion for {REPO_ID}...")
    ingest_from_github()
    logger.info("Ingestion complete!")