"""
Symbol Correlation Monitor — detects conflicting positions across correlated symbols.
"""

from loguru import logger

# Known inverse/positive correlations
CORRELATIONS = {
    ("GOLD", "USDJPY"): -0.7,    # Gold and USDJPY often move inversely
    ("GOLD", "BTCUSD"): 0.3,     # Weak positive (both risk hedges)
    ("OILCash", "USDJPY"): 0.2,  # Weak positive
}


def check_correlation_conflict(
    symbol: str,
    signal: int,
    active_positions: dict[str, list[dict]],
) -> tuple[bool, str]:
    """
    Check if a new trade would conflict with existing positions on correlated symbols.
    Returns (has_conflict, reason).
    """
    for (sym_a, sym_b), corr in CORRELATIONS.items():
        other = None
        if symbol == sym_a:
            other = sym_b
        elif symbol == sym_b:
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
