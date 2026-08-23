import unittest
from pathlib import Path
from stella.core.state_machine import (
    InvalidTransitionError,
    MaxReplansExceededError,
    StateContext,
    StateMachine,
    TaskEvent,
    TaskState,
)


class StateMachineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.context = StateContext(
            task_id="test-task-1",
            issue_url="https://github.com/example/repo/issues/1",
            repository_path=Path("/tmp/fake_repo"),
            max_replans=2,
        )
        self.transitions_logged = []
        self.sm = StateMachine(
            context=self.context,
            on_transition=lambda ctx, rec: self.transitions_logged.append(
                (rec.from_state, rec.to_state, rec.event)
            ),
        )

    def test_happy_path_flow(self) -> None:
        # Initial state is PLAN
        self.assertEqual(self.sm.current_state, TaskState.PLAN)

        # 1. PLAN -> CODE
        self.sm.transition(
            TaskEvent.PLAN_APPROVED,
            plan={"summary": "Fix login bug", "files": ["auth.py"]},
        )
        self.assertEqual(self.sm.current_state, TaskState.CODE)
        self.assertEqual(
            self.context.get_data("plan"),
            {"summary": "Fix login bug", "files": ["auth.py"]},
        )

        # 2. CODE -> REVIEW
        self.sm.transition(
            TaskEvent.CODE_COMPLETED,
            code_changes={"modified_files": ["auth.py"], "diff": "+ fixed"},
        )
        self.assertEqual(self.sm.current_state, TaskState.REVIEW)
        self.assertEqual(
            self.context.get_data("code_changes"),
            {"modified_files": ["auth.py"], "diff": "+ fixed"},
        )

        # 3. REVIEW -> TEST
        self.sm.transition(
            TaskEvent.REVIEW_PASSED,
            review_result={"passed": True, "comments": "Looks clean"},
        )
        self.assertEqual(self.sm.current_state, TaskState.TEST)
        self.assertEqual(
            self.context.get_data("review_result"),
            {"passed": True, "comments": "Looks clean"},
        )

        # 4. TEST -> COMPLETED
        self.sm.transition(
            TaskEvent.TEST_PASSED,
            test_result={"passed": True, "tests_run": 10},
        )
        self.assertEqual(self.sm.current_state, TaskState.COMPLETED)
        self.assertEqual(
            self.context.get_data("test_result"),
            {"passed": True, "tests_run": 10},
        )

        # Verify transition history length and logged transitions
        self.assertEqual(len(self.context.history), 4)
        self.assertEqual(len(self.transitions_logged), 4)

    def test_review_rejected_loopback_to_plan(self) -> None:
        self.sm.transition(TaskEvent.PLAN_APPROVED)
        self.sm.transition(TaskEvent.CODE_COMPLETED)

        # REVIEW -> PLAN (Rejection loop-back)
        self.sm.transition(
            TaskEvent.REVIEW_REJECTED,
            review_result={"passed": False, "feedback": "Missing error handling"},
        )
        self.assertEqual(self.sm.current_state, TaskState.PLAN)
        self.assertEqual(self.context.replan_count, 1)
        self.assertEqual(
            self.context.get_data("review_result")["feedback"],
            "Missing error handling",
        )

    def test_test_failed_loopback_to_plan(self) -> None:
        self.sm.transition(TaskEvent.PLAN_APPROVED)
        self.sm.transition(TaskEvent.CODE_COMPLETED)
        self.sm.transition(TaskEvent.REVIEW_PASSED)

        # TEST -> PLAN (Test failure loop-back)
        self.sm.transition(
            TaskEvent.TEST_FAILED,
            test_result={"passed": False, "traceback": "AssertionError: expected 200 got 500"},
        )
        self.assertEqual(self.sm.current_state, TaskState.PLAN)
        self.assertEqual(self.context.replan_count, 1)
        self.assertEqual(
            self.context.get_data("test_result")["traceback"],
            "AssertionError: expected 200 got 500",
        )

    def test_max_replans_exceeded(self) -> None:
        # Max replans set to 2 in setUp
        # 1st loopback
        self.sm.transition(TaskEvent.PLAN_APPROVED)
        self.sm.transition(TaskEvent.CODE_COMPLETED)
        self.sm.transition(TaskEvent.REVIEW_REJECTED)  # replan_count = 1

        # 2nd loopback
        self.sm.transition(TaskEvent.PLAN_APPROVED)
        self.sm.transition(TaskEvent.CODE_COMPLETED)
        self.sm.transition(TaskEvent.REVIEW_REJECTED)  # replan_count = 2

        # 3rd loopback attempt should raise MaxReplansExceededError and transition to FAILED
        self.sm.transition(TaskEvent.PLAN_APPROVED)
        self.sm.transition(TaskEvent.CODE_COMPLETED)
        with self.assertRaises(MaxReplansExceededError):
            self.sm.transition(TaskEvent.REVIEW_REJECTED)

        self.assertEqual(self.sm.current_state, TaskState.FAILED)
        self.assertIn("Exceeded maximum allowed replans", self.context.error_message)

    def test_invalid_transition_throws(self) -> None:
        # From PLAN, attempting TEST_PASSED is invalid
        with self.assertRaises(InvalidTransitionError):
            self.sm.transition(TaskEvent.TEST_PASSED)

    def test_fail_event_transitions_to_failed(self) -> None:
        self.sm.transition(TaskEvent.FAIL, error="Unexpected network error")
        self.assertEqual(self.sm.current_state, TaskState.FAILED)
        self.assertEqual(self.context.error_message, "Unexpected network error")


if __name__ == "__main__":
    unittest.main()
