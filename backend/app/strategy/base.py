"""
Base Strategy — abstract class for all trading strategies.
"""

from abc import ABC, abstractmethod

import pandas as pd


class BaseStrategy(ABC):
    # Class-level default — subclasses set via self._last_reason in calculate()
    _last_reason: str = ""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def min_bars_required(self) -> int: ...

    @property
    @abstractmethod
    def worst_case(self) -> str:
        """Describe the scenario where this strategy fails catastrophically."""
        ...

    @property
    def last_reason(self) -> str:
        """Human-readable reason for the last signal generated."""
        return self._last_reason

    @abstractmethod
    def calculate(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate indicators and signals on the DataFrame.
        Must add a 'signal' column: 1=BUY, -1=SELL, 0=HOLD.
        """
        ...

    @abstractmethod
    def get_params(self) -> dict: ...
