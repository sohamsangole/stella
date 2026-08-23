from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from stella.clients.github_client import GitHubClient
from stella.core.state_machine import StateContext


@dataclass(frozen=True)
class AgentContext:
    issue_url: str
    comments_url: str
    repository_path: Path
    state_context: Optional[StateContext] = None


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
        if context.comments_url:
            self.github.post_issue_comment(context.comments_url, message)

        if context.state_context is not None:
            context.state_context.set_data("acknowledgement_message", message)

        return AgentResult(agent=self.name, status="completed", message=message)
