from dataclasses import dataclass

import requests


@dataclass(frozen=True)
class GitHubClient:
    token: str
    api_version: str = "2022-11-28"

    def post_issue_comment(self, comments_url: str, body: str) -> None:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": self.api_version,
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        response = requests.post(
            comments_url,
            headers=headers,
            json={"body": body},
            timeout=30,
        )
        response.raise_for_status()

    def ensure_pull_request(
        self,
        repository_api_url: str,
        owner: str,
        head_branch: str,
        base_branch: str,
        title: str,
        body: str,
    ) -> dict:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": self.api_version,
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        response = requests.get(
            f"{repository_api_url}/pulls",
            headers=headers,
            params={
                "state": "open",
                "head": f"{owner}:{head_branch}",
                "base": base_branch,
            },
            timeout=30,
        )
        response.raise_for_status()
        pull_requests = response.json()
        if pull_requests:
            return pull_requests[0]

        response = requests.post(
            f"{repository_api_url}/pulls",
            headers=headers,
            json={
                "title": title,
                "head": head_branch,
                "base": base_branch,
                "body": body,
            },
            timeout=30,
        )
        response.raise_for_status()
        return response.json()
