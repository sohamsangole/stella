import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from stella.workspace.workspace import RemoteWorkspace, RepositoryPublisher, WorkspaceError


class RemoteWorkspaceTests(unittest.TestCase):
    def test_clones_repository_and_cleans_up_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace_root = Path(directory) / "workspaces"
            clone = Mock()

            def create_clone(command, **kwargs) -> None:
                repository = Path(command[-1])
                repository.mkdir(parents=True)
                (repository / ".git").mkdir()
                (repository / "README.md").write_text(
                    "workspace fixture\n", encoding="utf-8"
                )

            clone.side_effect = create_clone
            with patch("stella.workspace.workspace.subprocess.run", clone):
                with RemoteWorkspace(
                    clone_url="https://github.com/example/repo.git",
                    base_directory=str(workspace_root),
                ) as workspace:
                    task_root = workspace.root
                    self.assertEqual(
                        (workspace.repository / "README.md").read_text(encoding="utf-8"),
                        "workspace fixture\n",
                    )
                    self.assertTrue((workspace.repository / ".git").is_dir())

            self.assertFalse(task_root.exists())
            command = clone.call_args.args[0]
            self.assertEqual(command[:3], ["git", "clone", "--no-tags"])
            self.assertEqual(command[3], "https://github.com/example/repo.git")

    def test_requires_clone_url(self) -> None:
        with self.assertRaises(WorkspaceError):
            with RemoteWorkspace(clone_url=""):
                pass


class RepositoryPublisherTests(unittest.TestCase):
    def test_prefers_master_and_reuses_existing_issue_branch(self) -> None:
        commands = []

        def run(command, **kwargs):
            commands.append(command)
            if command[-1] == "refs/remotes/origin/master":
                return subprocess.CompletedProcess(command, 0)
            if command[-1] == "refs/remotes/origin/stella/issue-7":
                return subprocess.CompletedProcess(command, 0)
            return subprocess.CompletedProcess(command, 0)

        publisher = RepositoryPublisher(
            repository=Path("C:/workspace/repository"),
            token="installation-token",
            command_runner=run,
        )

        base_branch = publisher.prepare_branch(
            branch_name="stella/issue-7",
            default_branch="main",
        )

        self.assertEqual(base_branch, "master")
        self.assertIn(
            [
                "git",
                "checkout",
                "-B",
                "stella/issue-7",
                "origin/stella/issue-7",
            ],
            commands,
        )

    def test_uses_default_branch_when_master_is_missing(self) -> None:
        commands = []

        def run(command, **kwargs):
            commands.append(command)
            if command[-1] in {
                "refs/remotes/origin/master",
                "refs/remotes/origin/stella/issue-8",
            }:
                return subprocess.CompletedProcess(command, 1)
            return subprocess.CompletedProcess(command, 0)

        publisher = RepositoryPublisher(
            repository=Path("C:/workspace/repository"),
            command_runner=run,
        )

        base_branch = publisher.prepare_branch(
            branch_name="stella/issue-8",
            default_branch="develop",
        )

        self.assertEqual(base_branch, "develop")
        self.assertIn(
            ["git", "checkout", "-b", "stella/issue-8", "origin/develop"],
            commands,
        )

    def test_falls_back_to_local_branch_when_base_branch_does_not_exist_remotely(self) -> None:
        commands = []

        def run(command, **kwargs):
            commands.append(command)
            return subprocess.CompletedProcess(command, 1)

        publisher = RepositoryPublisher(
            repository=Path("C:/workspace/repository"),
            command_runner=run,
        )

        base_branch = publisher.prepare_branch(
            branch_name="stella/issue-9",
            default_branch="main",
        )

        self.assertEqual(base_branch, "main")
        self.assertIn(
            ["git", "checkout", "-b", "stella/issue-9"],
            commands,
        )

    def test_commits_main_file_and_pushes_reusable_branch(self) -> None:
        calls = []

        def run(command, **kwargs):
            calls.append((command, kwargs))
            return subprocess.CompletedProcess(command, 0)

        publisher = RepositoryPublisher(
            repository=Path("C:/workspace/repository"),
            token="installation-token",
            app_name="coding-agent-stella",
            app_id="12345",
            command_runner=run,
        )

        publisher.commit_and_push(
            branch_name="stella/issue-7",
            commit_message="Stella update for issue #7",
        )

        commands = [command for command, _ in calls]
        self.assertEqual(
            commands,
            [
                ["git", "config", "user.name", "coding-agent-stella[bot]"],
                [
                    "git",
                    "config",
                    "user.email",
                    "12345+coding-agent-stella[bot]@users.noreply.github.com",
                ],
                ["git", "add", "--", "main.py"],
                ["git", "commit", "-m", "Stella update for issue #7"],
                ["git", "push", "-u", "origin", "stella/issue-7"],
            ],
        )
        self.assertNotIn("installation-token", repr(commands))


if __name__ == "__main__":
    unittest.main()

