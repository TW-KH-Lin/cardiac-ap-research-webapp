from __future__ import annotations

from abc import ABC, abstractmethod

from app.core.schemas import SimulationRequest


class SimulationBackend(ABC):
    @abstractmethod
    def simulate(self, entry: dict, request: SimulationRequest) -> dict:
        raise NotImplementedError
