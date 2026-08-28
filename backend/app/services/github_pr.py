import httpx


def create_pull_request(
    token: str,
    repo: str,
    title: str,
    body: str,
    head: str,
    base: str,
) -> dict:
    with httpx.Client(timeout=30) as client:
        response = client.post(
            f"https://api.github.com/repos/{repo}/pulls",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            json={
                "title": title,
                "body": body,
                "head": head,
                "base": base,
            },
        )
    response.raise_for_status()
    return response.json()
