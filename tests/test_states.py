import unittest
from pathlib import Path

from stella.core.state_machine import StateContext, TaskEvent, TaskState
from stella.states import (
    CodeStateRunner,
    PlanStateRunner,
    ReviewStateRunner,
    TestStateRunner,
)


class StateRunnersTests(unittest.TestCase):
    def setUp(self) -> None:
        self.context = StateContext(
            task_id="test-task-states",
            issue_url="https://github.com/example/repo/issues/10",
            repository_path=Path("/tmp/fake_repo"),
        )

    def test_plan_runner(self) -> None:
        runner = PlanStateRunner()
        self.assertEqual(runner.state, TaskState.PLAN)
        event, message = runner.execute(self.context)
        self.assertEqual(event, TaskEvent.PLAN_APPROVED)
        self.assertIn("plan", self.context.data)

    def test_code_runner(self) -> None:
        runner = CodeStateRunner()
        self.assertEqual(runner.state, TaskState.CODE)
        event, message = runner.execute(self.context)
        self.assertEqual(event, TaskEvent.CODE_COMPLETED)
        self.assertIn("code_changes", self.context.data)

    def test_review_runner(self) -> None:
        runner = ReviewStateRunner()
        self.assertEqual(runner.state, TaskState.REVIEW)
        event, message = runner.execute(self.context)
        self.assertEqual(event, TaskEvent.REVIEW_PASSED)
        self.assertIn("review_result", self.context.data)

    def test_test_runner(self) -> None:
        runner = TestStateRunner()
        self.assertEqual(runner.state, TaskState.TEST)
        event, message = runner.execute(self.context)
        self.assertEqual(event, TaskEvent.TEST_PASSED)
        self.assertIn("test_result", self.context.data)


if __name__ == "__main__":
    unittest.main()
