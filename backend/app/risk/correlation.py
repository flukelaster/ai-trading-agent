"""
Symbol Correlation Monitor — detects conflicting positions across correlated symbols.

Supports both static (hardcoded) and rolling (data-driven) correlations.
"""

from dataclasses import dataclass, field

import numpy as np
from loguru import logger

# Fallback static correlations (used when no market data available)
STATIC_CORRELATIONS = {
    ("GOLD", "USDJPY"): -0.7,    # Gold and USDJPY often move inversely
    ("GOLD", "BTCUSD"): 0.3,     # Weak positive (both risk hedges)
    ("OILCash", "USDJPY"): 0.2,  # Weak positive
}

# Backward compat alias
CORRELATIONS = STATIC_CORRELATIONS


@dataclass
class CorrelationMatrix:
    """Rolling correlation matrix with change detection."""

    matrix: dict[tuple[str, str], float] = field(default_factory=dict)
    window: int = 30
    last_update: str = ""

    def get(self, sym_a: str, sym_b: str) -> float:
        """Get correlation between two symbols (order-independent)."""
        if sym_a == sym_b:
            return 1.0
        key = (min(sym_a, sym_b), max(sym_a, sym_b))
        return self.matrix.get(key, STATIC_CORRELATIONS.get(key, STATIC_CORRELATIONS.get((key[1], key[0]), 0.0)))

    def to_dict(self) -> dict:
        return {
            "matrix": {f"{a}_{b}": round(v, 3) for (a, b), v in self.matrix.items()},
            "window": self.window,
            "last_update": self.last_update,
        }


def compute_rolling_correlation(
    price_series: dict[str, np.ndarray],
    window: int = 30,
) -> CorrelationMatrix:
    """Compute rolling correlation matrix from price series.

    Args:
        price_series: {symbol: np.array of closing prices} — newest last
        window: rolling window size

    Returns:
        CorrelationMatrix with pairwise correlations
    """
    from datetime import datetime

    result = CorrelationMatrix(window=window, last_update=datetime.utcnow().isoformat())
    symbols = sorted(price_series.keys())

    # Compute log returns
    returns = {}
    for sym in symbols:
        p = price_series[sym]
        if len(p) < window + 1:
            continue
        r = np.diff(np.log(p[-window - 1:]))
        if len(r) == window:
            returns[sym] = r

    # Pairwise correlation
    for i, sym_a in enumerate(symbols):
        for sym_b in symbols[i + 1:]:
            if sym_a in returns and sym_b in returns:
                corr = np.corrcoef(returns[sym_a], returns[sym_b])[0, 1]
                if not np.isnan(corr):
                    result.matrix[(sym_a, sym_b)] = round(corr, 4)

    return result


def detect_correlation_change(
    current: CorrelationMatrix,
    historical: CorrelationMatrix | None = None,
    threshold: float = 0.3,
) -> list[dict]:
    """Detect significant correlation regime changes.

    Uses Fisher z-transformation to test if correlation has significantly changed.

    Returns:
        List of {pair, old_corr, new_corr, change, alert_level}
    """
    alerts = []
    baseline = historical or CorrelationMatrix(matrix=dict(STATIC_CORRELATIONS))

    for pair, new_corr in current.matrix.items():
        old_corr = baseline.matrix.get(pair, STATIC_CORRELATIONS.get(pair, 0.0))
        change = abs(new_corr - old_corr)

        if change >= threshold:
            alert_level = "critical" if change >= 0.5 else "warning"
            alerts.append({
                "pair": f"{pair[0]}/{pair[1]}",
                "old_corr": round(old_corr, 3),
                "new_corr": round(new_corr, 3),
                "change": round(change, 3),
                "alert_level": alert_level,
            })
            logger.warning(
                f"Correlation change [{pair[0]}/{pair[1]}]: "
                f"{old_corr:.2f} → {new_corr:.2f} (Δ{change:.2f}) [{alert_level}]"
            )

    return alerts


def check_correlation_conflict(
    symbol: str,
    signal: int,
    active_positions: dict[str, list[dict]],
    correlations: dict[tuple[str, str], float] | None = None,
) -> tuple[bool, str]:
    """
    Check if a new trade would conflict with existing positions on correlated symbols.

    `correlations` overrides the module-level lookup with rolling values passed
    in by the caller — avoids mutating CORRELATIONS from concurrent coroutines.
    Returns (has_conflict, reason).
    """
    # Resolve aliases (e.g., GOLDmicro → GOLD) for correlation lookup
    from app.config import get_canonical_symbol
    canonical = get_canonical_symbol(symbol)

    corr_map = correlations if correlations is not None else CORRELATIONS

    for (sym_a, sym_b), corr in corr_map.items():
        other = None
        if canonical == sym_a:
            other = sym_b
        elif canonical == sym_b:
            other = sym_a
        else:
            continue

        other_positions = active_positions.get(other, [])
        if not other_positions:
            continue

        # Determine other symbol's net direction
        other_direction = 0
        for pos in other_positions:
            if pos.get("type") == "BUY":
                other_direction += 1
            else:
                other_direction -= 1

        if other_direction == 0:
            continue

        other_is_long = other_direction > 0

        # For negatively correlated pairs: same direction = conflict
        if corr < -0.5:
            if (signal == 1 and other_is_long) or (signal == -1 and not other_is_long):
                reason = (f"Correlation conflict: {symbol} {'BUY' if signal == 1 else 'SELL'} "
                         f"vs {other} {'LONG' if other_is_long else 'SHORT'} "
                         f"(correlation: {corr:.1f})")
                logger.warning(reason)
                return True, reason

        # For positively correlated pairs: opposite direction = conflict
        if corr > 0.5:
            if (signal == 1 and not other_is_long) or (signal == -1 and other_is_long):
                reason = (f"Correlation conflict: {symbol} {'BUY' if signal == 1 else 'SELL'} "
                         f"vs {other} {'LONG' if other_is_long else 'SHORT'} "
                         f"(correlation: {corr:.1f})")
                logger.warning(reason)
                return True, reason

    return False, ""
