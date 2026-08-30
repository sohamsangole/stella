import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from stella.core.state_machine import TaskEvent, TaskState
from stella.core.worker import process_stella_task
from stella.states.base import BaseStateRunner
from stella.workspace.workspace import WorkspaceError


class WorkerLoopTests(unittest.TestCase):
    def setUp(self) -> None:
        self.payload = {
            "issue": {
                "html_url": "https://github.com/octocat/Hello-World/issues/42",
                "comments_url": "https://api.github.com/repos/octocat/Hello-World/issues/42/comments",
                "number": 42,
            },
            "comment": {
                "body": "@stella-agent please fix this bug",
            },
            "repository": {
                "clone_url": "https://github.com/octocat/Hello-World.git",
                "url": "https://api.github.com/repos/octocat/Hello-World",
                "default_branch": "main",
                "owner": {"login": "octocat"},
            },
            "installation": {
                "id": 12345,
            },
        }

    @patch("stella.core.worker.get_installation_token", return_value="fake-token")
    @patch("stella.core.worker.GitHubClient")
    @patch("stella.core.worker.AcknowledgementAgent")
    @patch("stella.core.worker.RemoteWorkspace")
    @patch("stella.core.worker.RepositoryPublisher")
    def test_process_stella_task_happy_path(
        self,
        mock_publisher_cls,
        mock_workspace_cls,
        mock_ack_agent_cls,
        mock_github_client_cls,
        mock_get_token,
    ) -> None:
        mock_ack_agent = MagicMock()
        mock_ack_agent.run.return_value = MagicMock(agent="AcknowledgementAgent", status="success")
        mock_ack_agent_cls.return_value = mock_ack_agent

        with TemporaryDirectory() as directory:
            repository = Path(directory)
            (repository / "main.py").write_text("", encoding="utf-8")
            mock_ws = MagicMock(repository=repository)
            mock_workspace_cls.return_value.__enter__.return_value = mock_ws

            process_stella_task(self.payload)

        mock_ack_agent.run.assert_called_once()
        mock_publisher_cls.return_value.commit_and_push.assert_called_once()
        mock_workspace_cls.assert_called_once_with(
            clone_url="https://github.com/octocat/Hello-World.git",
            token="fake-token",
            base_directory=unittest.mock.ANY,
        )

    @patch("stella.core.worker.get_installation_token", return_value="fake-token")
    @patch("stella.core.worker.GitHubClient")
    @patch("stella.core.worker.AcknowledgementAgent")
    @patch("stella.core.worker.RemoteWorkspace")
    @patch("stella.core.worker.RepositoryPublisher")
    @patch("stella.core.worker.get_runner")
    def test_process_stella_task_loopback_and_completion(
        self,
        mock_get_runner,
        mock_publisher_cls,
        mock_workspace_cls,
        mock_ack_agent_cls,
        mock_github_client_cls,
        mock_get_token,
    ) -> None:
        mock_ws = MagicMock()
        mock_ws.repository = Path("/tmp/mock_repo")
        mock_workspace_cls.return_value.__enter__.return_value = mock_ws

        mock_ack_agent = MagicMock()
        mock_ack_agent.run.return_value = MagicMock(agent="AcknowledgementAgent", status="success")
        mock_ack_agent_cls.return_value = mock_ack_agent

        # Simulate Review failing first time, then passing next time
        review_call_count = 0

        def review_execute(ctx):
            nonlocal review_call_count
            review_call_count += 1
            if review_call_count == 1:
                return TaskEvent.REVIEW_REJECTED, "Needs rework"
            return TaskEvent.REVIEW_PASSED, "Approved"

        plan_runner = MagicMock(spec=BaseStateRunner)
        plan_runner.execute.return_value = (TaskEvent.PLAN_APPROVED, "Plan ready")

        code_runner = MagicMock(spec=BaseStateRunner)
        code_runner.execute.return_value = (TaskEvent.CODE_COMPLETED, "Code ready")

        review_runner = MagicMock(spec=BaseStateRunner)
        review_runner.execute.side_effect = review_execute

        test_runner = MagicMock(spec=BaseStateRunner)
        test_runner.execute.return_value = (TaskEvent.TEST_PASSED, "Tests passed")

        def runner_lookup(state):
            if state == TaskState.PLAN:
                return plan_runner
            elif state == TaskState.CODE:
                return code_runner
            elif state == TaskState.REVIEW:
                return review_runner
            elif state == TaskState.TEST:
                return test_runner
            return None

        mock_get_runner.side_effect = runner_lookup

        process_stella_task(self.payload)

        # Plan called twice (initial + after review rejected)
        self.assertEqual(plan_runner.execute.call_count, 2)
        self.assertEqual(code_runner.execute.call_count, 2)
        self.assertEqual(review_runner.execute.call_count, 2)
        self.assertEqual(test_runner.execute.call_count, 1)

    @patch("stella.core.worker.get_installation_token", return_value="fake-token")
    @patch("stella.core.worker.GitHubClient")
    @patch("stella.core.worker.AcknowledgementAgent")
    @patch("stella.core.worker.RemoteWorkspace")
    @patch("stella.core.worker.RepositoryPublisher")
    @patch("stella.core.worker.get_runner")
    def test_process_stella_task_max_replans_exceeded(
        self,
        mock_get_runner,
        mock_publisher_cls,
        mock_workspace_cls,
        mock_ack_agent_cls,
        mock_github_client_cls,
        mock_get_token,
    ) -> None:
        mock_ws = MagicMock()
        mock_ws.repository = Path("/tmp/mock_repo")
        mock_workspace_cls.return_value.__enter__.return_value = mock_ws

        mock_ack_agent = MagicMock()
        mock_ack_agent.run.return_value = MagicMock(agent="AcknowledgementAgent", status="success")
        mock_ack_agent_cls.return_value = mock_ack_agent

        plan_runner = MagicMock(spec=BaseStateRunner)
        plan_runner.execute.return_value = (TaskEvent.PLAN_APPROVED, "Plan ready")

        code_runner = MagicMock(spec=BaseStateRunner)
        code_runner.execute.return_value = (TaskEvent.CODE_COMPLETED, "Code ready")

        # Always reject review
        review_runner = MagicMock(spec=BaseStateRunner)
        review_runner.execute.return_value = (TaskEvent.REVIEW_REJECTED, "Rejected always")

        def runner_lookup(state):
            if state == TaskState.PLAN:
                return plan_runner
            elif state == TaskState.CODE:
                return code_runner
            elif state == TaskState.REVIEW:
                return review_runner
            return None

        mock_get_runner.side_effect = runner_lookup

        process_stella_task(self.payload)

        # Default max_replans in StateContext is 5.
        # So Plan and Code should execute 1 (initial) + 5 (replans) = 6 times.
        self.assertEqual(plan_runner.execute.call_count, 6)
        self.assertEqual(code_runner.execute.call_count, 6)
        self.assertEqual(review_runner.execute.call_count, 6)

    @patch("stella.core.worker.get_installation_token", return_value="fake-token")
    @patch("stella.core.worker.GitHubClient")
    @patch("stella.core.worker.AcknowledgementAgent")
    @patch("stella.core.worker.RemoteWorkspace")
    @patch("stella.core.worker.RepositoryPublisher")
    @patch("stella.core.worker.get_runner")
    def test_process_stella_task_runner_exception(
        self,
        mock_get_runner,
        mock_publisher_cls,
        mock_workspace_cls,
        mock_ack_agent_cls,
        mock_github_client_cls,
        mock_get_token,
    ) -> None:
        mock_ws = MagicMock()
        mock_ws.repository = Path("/tmp/mock_repo")
        mock_workspace_cls.return_value.__enter__.return_value = mock_ws

        mock_ack_agent = MagicMock()
        mock_ack_agent.run.return_value = MagicMock(agent="AcknowledgementAgent", status="success")
        mock_ack_agent_cls.return_value = mock_ack_agent

        plan_runner = MagicMock(spec=BaseStateRunner)
        plan_runner.execute.side_effect = RuntimeError("Fatal runner crash")

        mock_get_runner.return_value = plan_runner

        # Should catch error gracefully and exit loop without raising unhandled exception
        process_stella_task(self.payload)
        self.assertEqual(plan_runner.execute.call_count, 1)

    def test_completed_task_pushes_reusable_branch_and_ensures_pr(self) -> None:
        with TemporaryDirectory() as directory:
            repository = Path(directory)
            (repository / "main.py").write_text(
                'print("existing code")\n', encoding="utf-8"
            )
            workspace = MagicMock(repository=repository)
            acknowledgement = MagicMock()
            acknowledgement.run.return_value = MagicMock(
                agent="AcknowledgementAgent", status="success"
            )
            github = MagicMock()
            publisher = MagicMock()
            publisher.prepare_branch.return_value = "master"

            with (
                patch(
                    "stella.core.worker.get_installation_token",
                    return_value="fake-token",
                ),
                patch("stella.core.worker.GitHubClient", return_value=github),
                patch(
                    "stella.core.worker.AcknowledgementAgent",
                    return_value=acknowledgement,
                ),
                patch("stella.core.worker.RemoteWorkspace") as workspace_class,
                patch(
                    "stella.core.worker.RepositoryPublisher",
                    return_value=publisher,
                    create=True,
                ),
            ):
                workspace_class.return_value.__enter__.return_value = workspace

                process_stella_task(self.payload)

        publisher.prepare_branch.assert_called_once_with(
            branch_name="stella/issue-42",
            default_branch="main",
        )
        publisher.commit_and_push.assert_called_once_with(
            branch_name="stella/issue-42",
            commit_message="Stella update for issue #42",
        )
        github.ensure_pull_request.assert_called_once_with(
            repository_api_url="https://api.github.com/repos/octocat/Hello-World",
            owner="octocat",
            head_branch="stella/issue-42",
            base_branch="master",
            title="Stella: resolve issue #42",
            body="Automated change for #42.\n\nCloses #42.",
        )

    def test_failed_state_posts_issue_comment_without_publishing(self) -> None:
        with TemporaryDirectory() as directory:
            repository = Path(directory)
            workspace = MagicMock(repository=repository)
            acknowledgement = MagicMock()
            acknowledgement.run.return_value = MagicMock(
                agent="AcknowledgementAgent", status="success"
            )
            github = MagicMock()
            publisher = MagicMock()
            publisher.prepare_branch.return_value = "main"
            failing_runner = MagicMock(spec=BaseStateRunner)
            failing_runner.execute.side_effect = RuntimeError(
                "sensitive internal failure details"
            )

            with (
                patch(
                    "stella.core.worker.get_installation_token",
                    return_value="fake-token",
                ),
                patch("stella.core.worker.GitHubClient", return_value=github),
                patch(
                    "stella.core.worker.AcknowledgementAgent",
                    return_value=acknowledgement,
                ),
                patch("stella.core.worker.RemoteWorkspace") as workspace_class,
                patch(
                    "stella.core.worker.RepositoryPublisher",
                    return_value=publisher,
                ),
                patch("stella.core.worker.get_runner", return_value=failing_runner),
            ):
                workspace_class.return_value.__enter__.return_value = workspace

                process_stella_task(self.payload)

        github.post_issue_comment.assert_called_once_with(
            self.payload["issue"]["comments_url"],
            "Stella change failed: the automated workflow did not complete successfully.",
        )
        publisher.commit_and_push.assert_not_called()
        github.ensure_pull_request.assert_not_called()

    def test_publish_failure_posts_sanitized_issue_comment(self) -> None:
        with TemporaryDirectory() as directory:
            repository = Path(directory)
            (repository / "main.py").write_text("", encoding="utf-8")
            workspace = MagicMock(repository=repository)
            acknowledgement = MagicMock()
            acknowledgement.run.return_value = MagicMock(
                agent="AcknowledgementAgent", status="success"
            )
            github = MagicMock()
            publisher = MagicMock()
            publisher.prepare_branch.return_value = "main"
            publisher.commit_and_push.side_effect = WorkspaceError(
                "remote rejected token secret-value"
            )

            with (
                patch(
                    "stella.core.worker.get_installation_token",
                    return_value="fake-token",
                ),
                patch("stella.core.worker.GitHubClient", return_value=github),
                patch(
                    "stella.core.worker.AcknowledgementAgent",
                    return_value=acknowledgement,
                ),
                patch("stella.core.worker.RemoteWorkspace") as workspace_class,
                patch(
                    "stella.core.worker.RepositoryPublisher",
                    return_value=publisher,
                ),
            ):
                workspace_class.return_value.__enter__.return_value = workspace

                process_stella_task(self.payload)

        github.post_issue_comment.assert_called_once_with(
            self.payload["issue"]["comments_url"],
            "Stella change failed: unable to publish the generated branch.",
        )
        github.ensure_pull_request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
