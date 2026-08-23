from abc import ABC, abstractmethod
from typing import Optional, Tuple

from stella.core.state_machine import StateContext, TaskEvent, TaskState


class BaseStateRunner(ABC):
    """Abstract base class for all Stella state runners."""

    @property
    @abstractmethod
    def state(self) -> TaskState:
        """The TaskState handled by this runner."""
        pass

    @abstractmethod
    def execute(self, context: StateContext) -> Tuple[TaskEvent, Optional[str]]:
        """
        Execute the state logic.

        Returns:
            Tuple of (Next TaskEvent to trigger, optional message or summary).
        """
        pass
