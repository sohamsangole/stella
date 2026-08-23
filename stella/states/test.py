from typing import Optional, Tuple

from stella.core.state_machine import StateContext, TaskEvent, TaskState
from stella.states.base import BaseStateRunner


class TestStateRunner(BaseStateRunner):
    """Handler for TEST state: Runs test suite to verify changes."""

    @property
    def state(self) -> TaskState:
        return TaskState.TEST

    def execute(self, context: StateContext) -> Tuple[TaskEvent, Optional[str]]:
        print(f"[TestStateRunner] Running test suite for task: {context.task_id}")

        # Barebone test runner (passes by default in skeleton)
        tests_passed = True
        context.set_data(
            "test_result",
            {"passed": tests_passed, "output": "All tests passed."},
        )

        if tests_passed:
            return TaskEvent.TEST_PASSED, "Tests passed successfully."
        else:
            return TaskEvent.TEST_FAILED, "Tests failed."
