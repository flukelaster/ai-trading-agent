"""Resolve canonical symbol (e.g. GOLD) to broker alias (e.g. GOLDm#) at the MT5 boundary.

Distinct from `config.resolve_broker_symbol`, which normalizes user input to engine.symbol
(canonical). This helper is the last-mile mapping applied immediately before calling MT5 Bridge.
"""

from app.config import SYMBOL_PROFILES


def to_broker_alias(symbol: str) -> str:
    """Return broker_alias for symbol if set in SYMBOL_PROFILES, else symbol itself.

    Idempotent: passing an alias returns it unchanged when SYMBOL_PROFILES also keys it.
    Safe pre-DB-load: returns symbol when profile or alias missing.
    """
    if not symbol:
        return symbol
    profile = SYMBOL_PROFILES.get(symbol)
    if profile is None:
        return symbol
    alias = profile.get("broker_alias")
    return alias if alias else symbol
