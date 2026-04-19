"""Market session + daily-reset rules derived from asset class.

Replaces hardcoded MARKET_SCHEDULE and MARKET_RESET_HOURS dicts so new user-added
symbols inherit the correct session behavior from their asset class.

Asset classes:
- forex / metal / energy — Mon-Fri, MT5 daily close 22:00-23:00 UTC, P&L reset 22:00 UTC
- index — Mon-Fri, MT5 daily close 21:00-22:00 UTC, P&L reset 22:00 UTC
- crypto — 24/7, no daily close, P&L reset midnight UTC
- stock — Mon-Fri, closed outside US cash session (approx.), P&L reset 21:00 UTC
- unknown — defaults to forex behavior (safest conservative default)
"""

from __future__ import annotations

from datetime import datetime, timedelta

_RULES: dict[str, dict] = {
    "forex": {"weekend": True, "daily_close": (22, 23), "reset_hour_utc": 22},
    "metal": {"weekend": True, "daily_close": (22, 23), "reset_hour_utc": 22},
    "energy": {"weekend": True, "daily_close": (22, 23), "reset_hour_utc": 22},
    "index": {"weekend": True, "daily_close": (21, 22), "reset_hour_utc": 22},
    "crypto": {"weekend": False, "daily_close": None, "reset_hour_utc": 0},
    "stock": {"weekend": True, "daily_close": (21, 14), "reset_hour_utc": 21},
}

_DEFAULT_CLASS = "forex"


def _rules_for(asset_class: str | None) -> dict:
    key = (asset_class or _DEFAULT_CLASS).lower()
    return _RULES.get(key, _RULES[_DEFAULT_CLASS])


def get_reset_hour(asset_class: str | None) -> int:
    """UTC hour when daily P&L / trade counters reset."""
    return _rules_for(asset_class)["reset_hour_utc"]


def seconds_until_reset(asset_class: str | None, now: datetime | None = None) -> int:
    """Seconds until the next daily reset given the asset-class rules.

    Always returns a positive value (min 60s) so Redis TTLs never go to 0.
    """
    n = now or datetime.utcnow()
    reset_hour = get_reset_hour(asset_class)
    next_reset = n.replace(hour=reset_hour, minute=0, second=0, microsecond=0)
    if n >= next_reset:
        next_reset = next_reset + timedelta(days=1)
    return max(int((next_reset - n).total_seconds()), 60)


def is_market_open(asset_class: str | None, now: datetime | None = None) -> bool:
    """True when MT5 should accept trading for this asset class."""
    n = now or datetime.utcnow()
    rules = _rules_for(asset_class)

    # Weekend check — Saturday 00:00 UTC → Sunday 23:59 UTC (approximate).
    # Forex reopens Sunday 22:00 UTC; we accept some false negatives for simplicity.
    if rules["weekend"] and n.weekday() >= 5:
        return False

    dc = rules.get("daily_close")
    if dc is not None:
        start, end = dc
        if start <= end:
            if start <= n.hour < end:
                return False
        else:
            # Wraps across midnight (e.g. stock 21:00 → 14:00 next day)
            if n.hour >= start or n.hour < end:
                return False

    return True


def supported_asset_classes() -> list[str]:
    """Return the list of supported asset classes for UI dropdowns."""
    return sorted(_RULES.keys())
