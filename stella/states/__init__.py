from typing import Dict, Optional

from stella.core.state_machine import TaskState
from stella.states.base import BaseStateRunner
from stella.states.code import CodeStateRunner
from stella.states.plan import PlanStateRunner
from stella.states.review import ReviewStateRunner
from stella.states.test import TestStateRunner

STATE_RUNNERS: Dict[TaskState, BaseStateRunner] = {
    TaskState.PLAN: PlanStateRunner(),
    TaskState.CODE: CodeStateRunner(),
    TaskState.REVIEW: ReviewStateRunner(),
    TaskState.TEST: TestStateRunner(),
}


def get_runner(state: TaskState) -> Optional[BaseStateRunner]:
    """Retrieve the registered BaseStateRunner instance for the given TaskState."""
    return STATE_RUNNERS.get(state)


__all__ = [
    "BaseStateRunner",
    "PlanStateRunner",
    "CodeStateRunner",
    "ReviewStateRunner",
    "TestStateRunner",
    "STATE_RUNNERS",
    "get_runner",
]
