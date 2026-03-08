from abc import ABC, abstractmethod

from agent.models import ScoredInstrument, TechnicalScore


class BaseStrategy(ABC):
    """Abstract base class for trading strategies."""

    name: str = ""
    label: str = ""

    @abstractmethod
    def score_match(self, config: dict, tech: TechnicalScore, inst: ScoredInstrument) -> float:
        """Score how well an instrument matches this strategy.

        Returns 0 for no match, higher values for better matches.
        """

    def make_label(self, tech: TechnicalScore) -> str:
        """Return a human-readable label for this strategy match."""
        return self.label
