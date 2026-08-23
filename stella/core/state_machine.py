import time
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


class TaskState(Enum):
    PLAN = "PLAN"
    CODE = "CODE"
    REVIEW = "REVIEW"
    TEST = "TEST"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class TaskEvent(Enum):
    START_PLANNING = "START_PLANNING"
    PLAN_APPROVED = "PLAN_APPROVED"
    CODE_COMPLETED = "CODE_COMPLETED"
    REVIEW_PASSED = "REVIEW_PASSED"
    REVIEW_REJECTED = "REVIEW_REJECTED"
    TEST_PASSED = "TEST_PASSED"
    TEST_FAILED = "TEST_FAILED"
    FAIL = "FAIL"


class StateMachineError(Exception):
    """Base exception for StateMachine errors."""


class InvalidTransitionError(StateMachineError):
    """Raised when an invalid state transition is attempted."""


class MaxReplansExceededError(StateMachineError):
    """Raised when max replan iterations are exceeded."""


@dataclass
class TransitionRecord:
    from_state: TaskState
    to_state: TaskState
    event: TaskEvent
    timestamp: float = field(default_factory=time.time)


@dataclass
class StateContext:
    task_id: str
    issue_url: str
    repository_path: Path
    current_state: TaskState = TaskState.PLAN
    replan_count: int = 0
    max_replans: int = 5
    history: List[TransitionRecord] = field(default_factory=list)
    data: Dict[str, Any] = field(default_factory=dict)
    error_message: Optional[str] = None

    def get_data(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def set_data(self, key: str, value: Any) -> None:
        self.data[key] = value


# Transition mapping: (current_state, event) -> target_state
TRANSITION_TABLE: Dict[tuple[TaskState, TaskEvent], TaskState] = {
    (TaskState.PLAN, TaskEvent.PLAN_APPROVED): TaskState.CODE,
    (TaskState.CODE, TaskEvent.CODE_COMPLETED): TaskState.REVIEW,
    (TaskState.REVIEW, TaskEvent.REVIEW_PASSED): TaskState.TEST,
    (TaskState.REVIEW, TaskEvent.REVIEW_REJECTED): TaskState.PLAN,
    (TaskState.TEST, TaskEvent.TEST_PASSED): TaskState.COMPLETED,
    (TaskState.TEST, TaskEvent.TEST_FAILED): TaskState.PLAN,
}


class StateMachine:
    """State Machine governing Stella's PLAN -> CODE -> REVIEW -> TEST execution loop."""

    def __init__(
        self,
        context: StateContext,
        on_transition: Optional[Callable[[StateContext, TransitionRecord], None]] = None,
    ) -> None:
        self.context = context
        self._on_transition = on_transition

    @property
    def current_state(self) -> TaskState:
        return self.context.current_state

    def can_transition(self, event: TaskEvent) -> bool:
        if event == TaskEvent.FAIL:
            return self.current_state != TaskState.FAILED
        return (self.current_state, event) in TRANSITION_TABLE

    def transition(self, event: TaskEvent, **data_updates: Any) -> TaskState:
        """Advance the state machine via an event, applying any data updates to StateContext."""
        if not self.can_transition(event):
            raise InvalidTransitionError(
                f"Cannot transition from state '{self.current_state.value}' via event '{event.value}'."
            )

        if event == TaskEvent.FAIL:
            target_state = TaskState.FAILED
            if "error" in data_updates:
                self.context.error_message = str(data_updates["error"])
        else:
            target_state = TRANSITION_TABLE[(self.current_state, event)]

        # Handle replan loop limits when transitioning back to PLAN
        if target_state == TaskState.PLAN and self.current_state in (
            TaskState.REVIEW,
            TaskState.TEST,
        ):
            if self.context.replan_count >= self.context.max_replans:
                self.context.error_message = (
                    f"Exceeded maximum allowed replans ({self.context.max_replans})."
                )
                record = TransitionRecord(
                    from_state=self.current_state,
                    to_state=TaskState.FAILED,
                    event=TaskEvent.FAIL,
                )
                self.context.current_state = TaskState.FAILED
                self.context.history.append(record)
                if self._on_transition:
                    self._on_transition(self.context, record)
                raise MaxReplansExceededError(self.context.error_message)

            self.context.replan_count += 1

        # Apply data updates to shared context data store
        for key, value in data_updates.items():
            self.context.set_data(key, value)

        record = TransitionRecord(
            from_state=self.current_state,
            to_state=target_state,
            event=event,
        )
        self.context.current_state = target_state
        self.context.history.append(record)

        if self._on_transition:
            self._on_transition(self.context, record)

        return self.current_state
