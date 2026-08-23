from dataclasses import dataclass
from pathlib import Path

from github_client import GitHubClient


@dataclass(frozen=True)
class AgentContext:
    issue_url: str
    comments_url: str
    repository_path: Path


@dataclass(frozen=True)
class AgentResult:
    agent: str
    status: str
    message: str


class AcknowledgementAgent:
    """Deterministic first agent; it performs no model or LLM calls."""

    name = "stella-acknowledgement"

    def __init__(self, github: GitHubClient) -> None:
        self.github = github

    def run(self, context: AgentContext) -> AgentResult:
        if not context.repository_path.is_dir():
            raise FileNotFoundError(
                f"Repository workspace does not exist: {context.repository_path}"
            )

        message = "Stella is working on this issue. The repository workspace is ready."
        self.github.post_issue_comment(context.comments_url, message)
        return AgentResult(agent=self.name, status="completed", message=message)
