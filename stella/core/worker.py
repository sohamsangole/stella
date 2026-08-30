import time
import jwt
import requests
from celery import Celery
from stella.agents.agent_runner import AcknowledgementAgent, AgentContext
from stella.clients.github_client import GitHubClient
from stella.core.config import settings
from stella.core.state_machine import (
    MaxReplansExceededError,
    StateContext,
    StateMachine,
    TaskEvent,
    TaskState,
)
from stella.states import get_runner
from stella.workspace.workspace import (
    RemoteWorkspace,
    RepositoryPublisher,
    WorkspaceError,
)


def get_installation_token(installation_id: int) -> str:
    if not settings.github_app_id or not settings.github_private_key_path or not installation_id:
        return settings.github_token

    with open(settings.github_private_key_path, "r") as f:
        private_key = f.read()

    payload = {
        "iat": int(time.time()) - 60,  # 60s past to account for clock skew
        "exp": int(time.time()) + (10 * 60),
        "iss": settings.github_app_id,
    }
    encoded_jwt = jwt.encode(payload, private_key, algorithm="RS256")

    headers = {
        "Authorization": f"Bearer {encoded_jwt}",
        "Accept": "application/vnd.github.v3+json",
    }
    url = f"https://api.github.com/app/installations/{installation_id}/access_tokens"
    response = requests.post(url, headers=headers)
    response.raise_for_status()
    return response.json()["token"]


# Initialize Celery
app = Celery(
    "stella",
    broker=settings.redis_url,
    backend=settings.redis_url,
)


def _post_failure_comment(
    github: GitHubClient | None,
    comments_url: str | None,
    message: str,
) -> None:
    if not github or not comments_url:
        return
    try:
        github.post_issue_comment(comments_url, message)
    except requests.RequestException as error:
        print(f"Failed to post Stella failure comment: {error}")


@app.task(name="process_stella_task")
def process_stella_task(webhook_payload: dict):
    """Clone the repository and run Stella's task state machine workflow."""
    issue_url = webhook_payload.get("issue", {}).get("html_url")
    comments_url = webhook_payload.get("issue", {}).get("comments_url")
    comment_body = webhook_payload.get("comment", {}).get("body")
    installation_id = webhook_payload.get("installation", {}).get("id")
    clone_url = webhook_payload.get("repository", {}).get("clone_url")
    repository_api_url = webhook_payload.get("repository", {}).get("url")
    default_branch = webhook_payload.get("repository", {}).get("default_branch")
    repository_owner = (
        webhook_payload.get("repository", {}).get("owner", {}).get("login")
    )
    issue_number = webhook_payload.get("issue", {}).get("number", "unknown")
    comment_author = webhook_payload.get("comment", {}).get("user", {}).get("login", "unknown")
    author_association = webhook_payload.get("comment", {}).get("author_association", "unknown")

    print("--- STELLA WORKER ACTIVATED ---")
    print(f"Received task for issue: {issue_url}")
    print(f"Comment by: {comment_author} (Association: {author_association})")
    print(f"Comment was: {comment_body}")
    print("-------------------------------")

    if not comments_url or not clone_url:
        print("Webhook payload is missing the comments URL or repository clone URL.")
        return

    github = None
    try:
        token = get_installation_token(installation_id)
        github = GitHubClient(token=token)

        with RemoteWorkspace(
            clone_url=clone_url,
            token=token,
            base_directory=settings.workspace_root or None,
        ) as workspace:
            print(f"Repository cloned into temporary workspace: {workspace.repository}")
            branch_name = f"stella/issue-{issue_number}"
            publisher = RepositoryPublisher(
                repository=workspace.repository,
                token=token,
                app_name=getattr(settings, "github_app_name", "coding-agent-stella") or "coding-agent-stella",
                app_id=getattr(settings, "github_app_id", "") or "",
            )
            base_branch = publisher.prepare_branch(
                branch_name=branch_name,
                default_branch=default_branch or "main",
            )

            state_context = StateContext(
                task_id=f"task-issue-{issue_number}",
                issue_url=issue_url or "",
                repository_path=workspace.repository,
            )
            state_machine = StateMachine(
                context=state_context,
                on_transition=lambda ctx, rec: print(
                    f"[State Machine] Transitioned from {rec.from_state.value} -> {rec.to_state.value} via {rec.event.value}"
                ),
            )

            agent = AcknowledgementAgent(github)
            result = agent.run(
                AgentContext(
                    issue_url=issue_url or "",
                    comments_url=comments_url,
                    repository_path=workspace.repository,
                    state_context=state_context,
                )
            )
            print(f"Agent {result.agent} finished with status {result.status}.")

            # Run automated state execution loop: PLAN -> CODE -> REVIEW -> TEST -> COMPLETED
            terminal_states = {TaskState.COMPLETED, TaskState.FAILED}
            while state_machine.current_state not in terminal_states:
                current_state = state_machine.current_state
                runner = get_runner(current_state)
                if not runner:
                    print(
                        f"[Worker] No runner registered for state '{current_state.value}'. Failing task."
                    )
                    state_machine.transition(
                        TaskEvent.FAIL,
                        error=f"No runner registered for state '{current_state.value}'",
                    )
                    break

                try:
                    event, summary = runner.execute(state_context)
                    print(
                        f"[Worker] State '{current_state.value}' produced event '{event.value}' (summary: {summary})"
                    )
                    state_machine.transition(event)
                except MaxReplansExceededError as error:
                    print(f"[Worker] Max replans limit reached: {error}")
                    break
                except Exception as error:
                    print(
                        f"[Worker] Unexpected error in state '{current_state.value}': {error}"
                    )
                    state_machine.transition(TaskEvent.FAIL, error=str(error))
                    break

            print(
                f"[Worker] Task finished in state: {state_machine.current_state.value}"
            )
            if state_machine.current_state == TaskState.COMPLETED:
                publisher.commit_and_push(
                    branch_name=branch_name,
                    commit_message=f"Stella update for issue #{issue_number}",
                )
                github.ensure_pull_request(
                    repository_api_url=repository_api_url or "",
                    owner=repository_owner or "",
                    head_branch=branch_name,
                    base_branch=base_branch,
                    title=f"Stella: resolve issue #{issue_number}",
                    body=(
                        f"Automated change for #{issue_number}.\n\n"
                        f"Closes #{issue_number}."
                    ),
                )
            else:
                github.post_issue_comment(
                    comments_url,
                    "Stella change failed: the automated workflow did not complete successfully.",
                )

    except WorkspaceError as error:
        print(f"Failed to prepare repository workspace: {error}")
        _post_failure_comment(
            github,
            comments_url,
            "Stella change failed: unable to publish the generated branch.",
        )
    except requests.RequestException as error:
        print(f"GitHub request failed: {error}")
        _post_failure_comment(
            github,
            comments_url,
            "Stella change failed: a GitHub operation did not complete successfully.",
        )
    except Exception as error:
        print(f"Stella task failed: {error}")
        _post_failure_comment(
            github,
            comments_url,
            "Stella change failed: an unexpected task error occurred.",
        )
