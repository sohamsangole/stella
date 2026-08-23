from typing import Optional, Tuple

from stella.core.state_machine import StateContext, TaskEvent, TaskState
from stella.states.base import BaseStateRunner


class ReviewStateRunner(BaseStateRunner):
    """Handler for REVIEW state: Reviews generated code diffs against criteria."""

    @property
    def state(self) -> TaskState:
        return TaskState.REVIEW

    def execute(self, context: StateContext) -> Tuple[TaskEvent, Optional[str]]:
        print(f"[ReviewStateRunner] Reviewing code changes for task: {context.task_id}")

        # Barebone review check (passes by default in skeleton)
        review_passed = True
        context.set_data(
            "review_result",
            {"passed": review_passed, "comments": "Code review passed."},
        )

        if review_passed:
            return TaskEvent.REVIEW_PASSED, "Code review passed."
        else:
            return TaskEvent.REVIEW_REJECTED, "Code review rejected."
