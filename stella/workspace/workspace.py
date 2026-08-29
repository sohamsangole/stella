import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


class WorkspaceError(RuntimeError):
    """Raised when Stella cannot prepare a repository workspace."""


@dataclass(frozen=True)
class RepositoryWorkspace:
    root: Path
    repository: Path


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

        environment = os.environ.copy()
        if self.token:
            # Pass credentials through the child environment so they are not embedded
            # in the clone URL, command output, Git config, or remote definition.
            import base64
            auth_bytes = f"x-access-token:{self.token}".encode("utf-8")
            encoded_auth = base64.b64encode(auth_bytes).decode("utf-8")
            environment.update(
                {
                    "GIT_CONFIG_COUNT": "1",
                    "GIT_CONFIG_KEY_0": "http.extraHeader",
                    "GIT_CONFIG_VALUE_0": f"AUTHORIZATION: basic {encoded_auth}",
                }
            )

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
