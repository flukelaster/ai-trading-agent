"""
Baseline Anchor + Auto Reset — prevents compounding errors from AI self-learning.

Maintains a "safe harbor" of known-good parameters from walk-forward optimization.
Auto-resets when rolling Sharpe drops below baseline threshold.
"""

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np
from loguru import logger


@dataclass
class BaselineSnapshot:
    """Snapshot of baseline parameters."""

    params: dict  # strategy parameters
    sharpe_ratio: float  # Sharpe at time of baseline
    created_at: str  # ISO timestamp
    source: str  # "walk_forward", "manual", "initial"

    def to_dict(self) -> dict:
        return {
            "params": self.params,
            "sharpe_ratio": round(self.sharpe_ratio, 4),
            "created_at": self.created_at,
            "source": self.source,
        }


@dataclass
class ResetEvent:
    """Record of an auto-reset event."""

    timestamp: str
    reason: str
    baseline_sharpe: float
    rolling_sharpe: float
    params_before: dict
    params_after: dict

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "reason": self.reason,
            "baseline_sharpe": round(self.baseline_sharpe, 4),
            "rolling_sharpe": round(self.rolling_sharpe, 4),
        }


class BaselineManager:
    """Manages parameter baseline and auto-reset logic."""

    def __init__(
        self,
        reset_threshold: float = 0.70,
        cooldown_days: int = 7,
        min_trades_for_sharpe: int = 20,
    ):
        """
        Args:
            reset_threshold: if rolling_sharpe < baseline * threshold → reset
            cooldown_days: days after reset before AI can modify params again
            min_trades_for_sharpe: min trades to compute rolling Sharpe
        """
        self.reset_threshold = reset_threshold
        self.cooldown_days = cooldown_days
        self.min_trades_for_sharpe = min_trades_for_sharpe

        self._baseline: BaselineSnapshot | None = None
        self._reset_history: list[ResetEvent] = []
        self._last_reset: datetime | None = None
        self._current_params: dict = {}

    def set_baseline(self, params: dict, sharpe: float, source: str = "initial") -> None:
        """Set or update the baseline parameters."""
        self._baseline = BaselineSnapshot(
            params=deepcopy(params),
            sharpe_ratio=sharpe,
            created_at=datetime.utcnow().isoformat(),
            source=source,
        )
        self._current_params = deepcopy(params)
        logger.info(f"Baseline set: Sharpe={sharpe:.4f}, source={source}")

    def update_params(self, params: dict) -> bool:
        """Update current params (from AI suggestion). Returns False if in cooldown."""
        if self.is_in_cooldown():
            logger.warning("Parameter update blocked: cooldown active")
            return False

        self._current_params = deepcopy(params)
        return True

    def check_reset(self, recent_pnls: np.ndarray) -> ResetEvent | None:
        """Check if auto-reset should trigger.

        Args:
            recent_pnls: array of recent trade P&Ls

        Returns:
            ResetEvent if reset was triggered, None otherwise
        """
        if self._baseline is None:
            return None

        if len(recent_pnls) < self.min_trades_for_sharpe:
            return None

        # Compute rolling Sharpe
        mean_pnl = recent_pnls.mean()
        std_pnl = recent_pnls.std()
        rolling_sharpe = (mean_pnl / std_pnl) * np.sqrt(252) if std_pnl > 0 else 0

        # Check threshold
        threshold = self._baseline.sharpe_ratio * self.reset_threshold

        if rolling_sharpe < threshold:
            event = ResetEvent(
                timestamp=datetime.utcnow().isoformat(),
                reason=f"Rolling Sharpe {rolling_sharpe:.4f} < threshold {threshold:.4f} "
                f"(baseline {self._baseline.sharpe_ratio:.4f} × {self.reset_threshold})",
                baseline_sharpe=self._baseline.sharpe_ratio,
                rolling_sharpe=rolling_sharpe,
                params_before=deepcopy(self._current_params),
                params_after=deepcopy(self._baseline.params),
            )

            # Execute reset
            self._current_params = deepcopy(self._baseline.params)
            self._last_reset = datetime.utcnow()
            self._reset_history.append(event)

            logger.warning(
                f"AUTO RESET triggered: Sharpe {rolling_sharpe:.4f} < {threshold:.4f}. "
                f"Reverting to baseline params. Cooldown: {self.cooldown_days} days."
            )

            return event

        return None

    def is_in_cooldown(self) -> bool:
        """Check if cooldown is active (after a reset)."""
        if self._last_reset is None:
            return False
        elapsed = datetime.utcnow() - self._last_reset
        return elapsed < timedelta(days=self.cooldown_days)

    def get_cooldown_remaining(self) -> timedelta | None:
        """Get remaining cooldown time, or None if not in cooldown."""
        if not self.is_in_cooldown():
            return None
        return timedelta(days=self.cooldown_days) - (datetime.utcnow() - self._last_reset)

    @property
    def current_params(self) -> dict:
        return deepcopy(self._current_params)

    @property
    def baseline(self) -> BaselineSnapshot | None:
        return self._baseline

    def get_status(self) -> dict:
        """Get current baseline manager status."""
        return {
            "has_baseline": self._baseline is not None,
            "baseline": self._baseline.to_dict() if self._baseline else None,
            "in_cooldown": self.is_in_cooldown(),
            "cooldown_remaining": str(self.get_cooldown_remaining()) if self.is_in_cooldown() else None,
            "reset_count": len(self._reset_history),
            "last_reset": self._reset_history[-1].to_dict() if self._reset_history else None,
            "params_diverged": self._current_params != (self._baseline.params if self._baseline else {}),
        }
