import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from stella.workspace.workspace import RemoteWorkspace, WorkspaceError


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


if __name__ == "__main__":
    unittest.main()
