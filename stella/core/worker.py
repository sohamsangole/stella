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
from stella.workspace.workspace import RemoteWorkspace, WorkspaceError


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


@app.task(name="process_stella_task")
def process_stella_task(webhook_payload: dict):
    """Clone the repository and run Stella's task state machine workflow."""
    issue_url = webhook_payload.get("issue", {}).get("html_url")
    comments_url = webhook_payload.get("issue", {}).get("comments_url")
    comment_body = webhook_payload.get("comment", {}).get("body")
    installation_id = webhook_payload.get("installation", {}).get("id")
    clone_url = webhook_payload.get("repository", {}).get("clone_url")
    issue_number = webhook_payload.get("issue", {}).get("number", "unknown")

    print("--- STELLA WORKER ACTIVATED ---")
    print(f"Received task for issue: {issue_url}")
    print(f"Comment was: {comment_body}")
    print("-------------------------------")

    if not comments_url or not clone_url:
        print("Webhook payload is missing the comments URL or repository clone URL.")
        return

    try:
        token = get_installation_token(installation_id)
        github = GitHubClient(token=token)

        with RemoteWorkspace(
            clone_url=clone_url,
            token=token,
            base_directory=settings.workspace_root or None,
        ) as workspace:
            print(f"Repository cloned into temporary workspace: {workspace.repository}")

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

    except WorkspaceError as error:
        print(f"Failed to prepare repository workspace: {error}")
    except requests.RequestException as error:
        print(f"GitHub request failed: {error}")
    except Exception as error:
        print(f"Stella task failed: {error}")
