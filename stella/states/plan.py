from typing import Optional, Tuple

from stella.core.state_machine import StateContext, TaskEvent, TaskState
from stella.states.base import BaseStateRunner


class PlanStateRunner(BaseStateRunner):
    """Handler for PLAN state: Analyzes issue/repo and creates/refines implementation plan."""

    @property
    def state(self) -> TaskState:
        return TaskState.PLAN

    def execute(self, context: StateContext) -> Tuple[TaskEvent, Optional[str]]:
        print(f"[PlanStateRunner] Planning for task: {context.task_id}")

        # Inspect loopback results if returning from REVIEW or TEST
        review_result = context.get_data("review_result")
        test_result = context.get_data("test_result")

        if review_result and not review_result.get("passed"):
            print(
                f"[PlanStateRunner] Replanning based on review feedback: {review_result.get('feedback')}"
            )
        elif test_result and not test_result.get("passed"):
            print(
                f"[PlanStateRunner] Replanning based on test failure: {test_result.get('traceback')}"
            )

        plan_summary = "Skeleton plan generated."
        context.set_data("plan", {"summary": plan_summary, "target_files": []})

        return TaskEvent.PLAN_APPROVED, "Plan approved and ready for coding."
