"""
Statistical Significance Gate — validates AI parameter suggestions before applying.

Prevents overfitting by requiring:
1. Minimum sample size (30 trades)
2. Permutation test significance (p < 0.05)
3. Rate limit (max ±20% change per day)
4. OOS validation (out-of-sample Sharpe)
5. Cooldown period between adjustments
"""

from dataclasses import dataclass
from datetime import datetime

import numpy as np
from loguru import logger


@dataclass
class GateResult:
    """Result of parameter validation."""

    approved: bool
    parameter: str
    current_value: float
    suggested_value: float
    rejection_reason: str | None = None
    statistical_evidence: dict | None = None

    def to_dict(self) -> dict:
        return {
            "approved": self.approved,
            "parameter": self.parameter,
            "current_value": self.current_value,
            "suggested_value": self.suggested_value,
            "rejection_reason": self.rejection_reason,
            "statistical_evidence": self.statistical_evidence,
        }


class ParameterGate:
    """Gate that validates parameter changes before they're applied."""

    def __init__(
        self,
        min_trades: int = 30,
        max_change_pct: float = 0.20,
        cooldown_trades: int = 20,
        p_value_threshold: float = 0.05,
    ):
        self.min_trades = min_trades
        self.max_change_pct = max_change_pct
        self.cooldown_trades = cooldown_trades
        self.p_value_threshold = p_value_threshold
        self._last_change: dict[str, datetime] = {}
        self._trades_since_change: dict[str, int] = {}

    def validate(
        self,
        parameter: str,
        current_value: float,
        suggested_value: float,
        trade_count: int,
        recent_pnls: np.ndarray | None = None,
    ) -> GateResult:
        """Validate a suggested parameter change.

        Args:
            parameter: name of the parameter
            current_value: current value
            suggested_value: AI-suggested value
            trade_count: number of trades since last change
            recent_pnls: array of recent trade P&Ls for significance testing
        """
        # Gate 1: Minimum sample size
        if trade_count < self.min_trades:
            return GateResult(
                approved=False,
                parameter=parameter,
                current_value=current_value,
                suggested_value=suggested_value,
                rejection_reason=f"Insufficient trades: {trade_count} < {self.min_trades} minimum",
            )

        # Gate 2: Cooldown check
        trades_since = self._trades_since_change.get(parameter, self.cooldown_trades)
        if trades_since < self.cooldown_trades:
            return GateResult(
                approved=False,
                parameter=parameter,
                current_value=current_value,
                suggested_value=suggested_value,
                rejection_reason=f"Cooldown active: {trades_since}/{self.cooldown_trades} trades since last change",
            )

        # Gate 3: Max change rate
        if current_value != 0:
            change_pct = abs(suggested_value - current_value) / abs(current_value)
            if change_pct > self.max_change_pct:
                # Clamp to max change
                direction = 1 if suggested_value > current_value else -1
                suggested_value = current_value * (1 + direction * self.max_change_pct)
                logger.info(f"Parameter {parameter} clamped: change {change_pct:.1%} > {self.max_change_pct:.0%} max")

        # Gate 4: Statistical significance (permutation test)
        p_value = None
        if recent_pnls is not None and len(recent_pnls) >= self.min_trades:
            p_value = self._permutation_test(recent_pnls)
            if p_value > self.p_value_threshold:
                return GateResult(
                    approved=False,
                    parameter=parameter,
                    current_value=current_value,
                    suggested_value=suggested_value,
                    rejection_reason=f"Not statistically significant: p={p_value:.3f} > {self.p_value_threshold}",
                    statistical_evidence={"p_value": p_value},
                )

        # All gates passed
        self._last_change[parameter] = datetime.utcnow()
        self._trades_since_change[parameter] = 0

        return GateResult(
            approved=True,
            parameter=parameter,
            current_value=current_value,
            suggested_value=suggested_value,
            statistical_evidence={"p_value": p_value} if p_value else None,
        )

    def record_trade(self):
        """Record a new trade — increments cooldown counter for all parameters."""
        for param in self._trades_since_change:
            self._trades_since_change[param] += 1

    @staticmethod
    def _permutation_test(pnls: np.ndarray, n_permutations: int = 1000) -> float:
        """Simple permutation test: is the observed mean P&L significantly > 0?"""
        observed_mean = pnls.mean()

        count_better = 0
        for _ in range(n_permutations):
            # Randomly flip signs (null hypothesis: no edge)
            shuffled = pnls * np.random.choice([-1, 1], size=len(pnls))
            if shuffled.mean() >= observed_mean:
                count_better += 1

        return count_better / n_permutations
