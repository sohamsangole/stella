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
