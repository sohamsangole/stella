import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from stella.core.state_machine import TaskEvent, TaskState
from stella.core.worker import process_stella_task
from stella.states.base import BaseStateRunner


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
            },
            "installation": {
                "id": 12345,
            },
        }

    @patch("stella.core.worker.get_installation_token", return_value="fake-token")
    @patch("stella.core.worker.GitHubClient")
    @patch("stella.core.worker.AcknowledgementAgent")
    @patch("stella.core.worker.RemoteWorkspace")
    def test_process_stella_task_happy_path(
        self,
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

        process_stella_task(self.payload)

        mock_ack_agent.run.assert_called_once()
        mock_workspace_cls.assert_called_once_with(
            clone_url="https://github.com/octocat/Hello-World.git",
            token="fake-token",
            base_directory=unittest.mock.ANY,
        )

    @patch("stella.core.worker.get_installation_token", return_value="fake-token")
    @patch("stella.core.worker.GitHubClient")
    @patch("stella.core.worker.AcknowledgementAgent")
    @patch("stella.core.worker.RemoteWorkspace")
    @patch("stella.core.worker.get_runner")
    def test_process_stella_task_loopback_and_completion(
        self,
        mock_get_runner,
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
    @patch("stella.core.worker.get_runner")
    def test_process_stella_task_max_replans_exceeded(
        self,
        mock_get_runner,
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
    @patch("stella.core.worker.get_runner")
    def test_process_stella_task_runner_exception(
        self,
        mock_get_runner,
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


if __name__ == "__main__":
    unittest.main()
