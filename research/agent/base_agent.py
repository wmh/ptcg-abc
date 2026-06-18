"""Base agent interface all agents must implement."""
from __future__ import annotations
from abc import ABC, abstractmethod
from env.game_state import Observation
from env.actions import Action


class BaseAgent(ABC):
    @abstractmethod
    def act(self, observation: Observation) -> Action:
        """Choose an action given the current observation."""
        ...

    def reset(self) -> None:
        """Called at the start of each new game."""
        pass
