import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


with patch.dict("sys.modules", {"requests": Mock()}):
    from stella.agents.agent_runner import AcknowledgementAgent, AgentContext


class AcknowledgementAgentTests(unittest.TestCase):
    def test_posts_comment_after_workspace_exists(self) -> None:
        github = Mock()

        with tempfile.TemporaryDirectory() as directory:
            context = AgentContext(
                issue_url="https://github.com/example/repo/issues/7",
                comments_url="https://api.github.com/repos/example/repo/issues/7/comments",
                repository_path=Path(directory),
            )

            result = AcknowledgementAgent(github).run(context)

        github.post_issue_comment.assert_called_once_with(
            context.comments_url,
            "Stella is working on this issue. The repository workspace is ready.",
        )
        self.assertEqual(result.agent, "stella-acknowledgement")
        self.assertEqual(result.status, "completed")

    def test_rejects_missing_workspace(self) -> None:
        github = Mock()
        context = AgentContext(
            issue_url="https://github.com/example/repo/issues/7",
            comments_url="https://api.github.com/repos/example/repo/issues/7/comments",
            repository_path=Path("missing-workspace"),
        )

        with self.assertRaises(FileNotFoundError):
            AcknowledgementAgent(github).run(context)

        github.post_issue_comment.assert_not_called()


if __name__ == "__main__":
    unittest.main()
