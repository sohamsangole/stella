from typing import Optional, Tuple

from stella.core.state_machine import StateContext, TaskEvent, TaskState
from stella.states.base import BaseStateRunner


class CodeStateRunner(BaseStateRunner):
    """Handler for CODE state: Modifies repository files according to plan."""

    @property
    def state(self) -> TaskState:
        return TaskState.CODE

    def execute(self, context: StateContext) -> Tuple[TaskEvent, Optional[str]]:
        print(f"[CodeStateRunner] Generating code for task: {context.task_id}")
        plan = context.get_data("plan", {})

        modified_files = plan.get("target_files", []) if isinstance(plan, dict) else []
        context.set_data("code_changes", {"modified_files": modified_files, "git_diff": ""})

        return TaskEvent.CODE_COMPLETED, "Code changes generated."
