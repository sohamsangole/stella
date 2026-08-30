from datetime import datetime, timezone
from typing import Callable, Optional, Tuple

from stella.core.state_machine import StateContext, TaskEvent, TaskState
from stella.states.base import BaseStateRunner


class CodeStateRunner(BaseStateRunner):
    """Handler for CODE state: Modifies repository files according to plan."""

    def __init__(self, clock: Optional[Callable[[], datetime]] = None) -> None:
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    @property
    def state(self) -> TaskState:
        return TaskState.CODE

    def execute(self, context: StateContext) -> Tuple[TaskEvent, Optional[str]]:
        print(f"[CodeStateRunner] Generating code for task: {context.task_id}")
        main_file = context.repository_path / "main.py"
        existing_content = main_file.read_text(encoding="utf-8") if main_file.exists() else ""
        if existing_content and not existing_content.endswith("\n"):
            existing_content += "\n"

        update_line = 'print("Updated automatically by Stella")\n'
        if update_line not in existing_content:
            existing_content += update_line

        timestamp = self._clock().astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        existing_content += f"# Stella update: {timestamp}\n"
        main_file.write_text(existing_content, encoding="utf-8")

        context.set_data("code_changes", {"modified_files": ["main.py"], "git_diff": ""})

        return TaskEvent.CODE_COMPLETED, "Code changes generated."
