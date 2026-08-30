import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional


class WorkspaceError(RuntimeError):
    """Raised when Stella cannot prepare a repository workspace."""


@dataclass(frozen=True)
class RepositoryWorkspace:
    root: Path
    repository: Path


class RepositoryPublisher:
    """Prepare and publish Stella's reusable issue branch."""

    def __init__(
        self,
        repository: Path,
        token: str = "",
        app_name: str = "coding-agent-stella",
        app_id: str = "",
        bot_name: Optional[str] = None,
        bot_email: Optional[str] = None,
        command_runner: Callable = subprocess.run,
    ) -> None:
        self.repository = repository
        self.token = token
        self.bot_name = bot_name or f"{app_name}[bot]"
        if bot_email:
            self.bot_email = bot_email
        elif app_id:
            self.bot_email = f"{app_id}+{app_name}[bot]@users.noreply.github.com"
        else:
            self.bot_email = f"{app_name}[bot]@users.noreply.github.com"
        self._command_runner = command_runner

    def prepare_branch(self, branch_name: str, default_branch: str) -> str:
        if not default_branch:
            raise WorkspaceError("The webhook payload did not include a default branch.")

        self._run(["git", "fetch", "origin"])
        base_branch = (
            "master" if self._remote_branch_exists("master") else default_branch
        )
        if self._remote_branch_exists(branch_name):
            self._run(
                [
                    "git",
                    "checkout",
                    "-B",
                    branch_name,
                    f"origin/{branch_name}",
                ]
            )
        elif self._remote_branch_exists(base_branch):
            self._run(
                ["git", "checkout", "-b", branch_name, f"origin/{base_branch}"]
            )
        else:
            self._run(["git", "checkout", "-b", branch_name])
        return base_branch

    def commit_and_push(self, branch_name: str, commit_message: str) -> None:
        self._run(["git", "config", "user.name", self.bot_name])
        self._run(["git", "config", "user.email", self.bot_email])
        self._run(["git", "add", "--", "main.py"])
        self._run(["git", "commit", "-m", commit_message])
        self._run(["git", "push", "-u", "origin", branch_name])

    def _remote_branch_exists(self, branch_name: str) -> bool:
        result = self._run(
            [
                "git",
                "show-ref",
                "--verify",
                "--quiet",
                f"refs/remotes/origin/{branch_name}",
            ],
            check=False,
        )
        return result.returncode == 0

    def _run(self, command: list[str], check: bool = True):
        return self._command_runner(
            command,
            cwd=self.repository,
            check=check,
            capture_output=True,
            text=True,
            env=_git_environment(self.token),
        )


def _git_environment(token: str) -> dict[str, str]:
    environment = os.environ.copy()
    if token:
        import base64

        auth_bytes = f"x-access-token:{token}".encode("utf-8")
        encoded_auth = base64.b64encode(auth_bytes).decode("utf-8")
        environment.update(
            {
                "GIT_CONFIG_COUNT": "1",
                "GIT_CONFIG_KEY_0": "http.extraHeader",
                "GIT_CONFIG_VALUE_0": f"AUTHORIZATION: basic {encoded_auth}",
            }
        )
    return environment


class RemoteWorkspace:
    """Create an isolated, temporary clone for one Stella task."""

    def __init__(
        self,
        clone_url: str,
        token: str = "",
        base_directory: Optional[str] = None,
    ) -> None:
        self.clone_url = clone_url
        self.token = token
        self.base_directory = Path(base_directory).resolve() if base_directory else None
        self._temporary_directory: Optional[tempfile.TemporaryDirectory[str]] = None

    def __enter__(self) -> RepositoryWorkspace:
        if not self.clone_url:
            raise WorkspaceError("The webhook payload did not include a repository clone URL.")

        if self.base_directory:
            self.base_directory.mkdir(parents=True, exist_ok=True)

        self._temporary_directory = tempfile.TemporaryDirectory(
            prefix="stella-task-",
            dir=str(self.base_directory) if self.base_directory else None,
        )
        root = Path(self._temporary_directory.name).resolve()
        repository = root / "repository"

        # Pass credentials through the child environment so they are not embedded
        # in the clone URL, command output, Git config, or remote definition.
        environment = _git_environment(self.token)

        try:
            subprocess.run(
                ["git", "clone", "--no-tags", self.clone_url, str(repository)],
                check=True,
                capture_output=True,
                text=True,
                env=environment,
            )
        except (OSError, subprocess.CalledProcessError) as error:
            self._cleanup()
            detail = "Git is unavailable."
            if isinstance(error, subprocess.CalledProcessError):
                detail = (error.stderr or error.stdout or "git clone failed").strip()
            raise WorkspaceError(f"Unable to clone repository: {detail}") from error

        return RepositoryWorkspace(root=root, repository=repository)

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self._cleanup()

    def _cleanup(self) -> None:
        if self._temporary_directory is not None:
            self._temporary_directory.cleanup()
            self._temporary_directory = None
