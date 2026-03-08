from abc import ABC, abstractmethod

import pandas as pd


class BaseBroker(ABC):
    """Abstract base class for all broker implementations."""

    @property
    @abstractmethod
    def connected(self) -> bool: ...

    @abstractmethod
    def connect(self) -> bool: ...

    @abstractmethod
    def disconnect(self) -> None: ...

    @abstractmethod
    def get_historical_bars(
        self, symbol: str, duration: str = "50 D", bar_size: str = "1 day"
    ) -> pd.DataFrame | None: ...

    @abstractmethod
    def get_current_price(self, symbol: str) -> dict | None:
        """Return {open, high, low, close} for the latest bar, or None."""
        ...

    @abstractmethod
    def ping(self) -> bool: ...
