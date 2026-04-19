"""Unit tests for app.market.sessions — asset-class-driven session + reset rules."""

from datetime import datetime

import pytest

from app.market.sessions import (
    get_reset_hour,
    is_market_open,
    seconds_until_reset,
    supported_asset_classes,
)


# ─── Reset hour ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "asset_class,expected_hour",
    [
        ("forex", 22),
        ("metal", 22),
        ("energy", 22),
        ("index", 22),
        ("crypto", 0),
        ("stock", 21),
        (None, 22),  # None → forex default
        ("unknown_class", 22),  # unknown → forex default
        ("FOREX", 22),  # case-insensitive
    ],
)
def test_get_reset_hour(asset_class, expected_hour):
    assert get_reset_hour(asset_class) == expected_hour


# ─── seconds_until_reset ────────────────────────────────────────────────────


def test_seconds_until_reset_same_day_future():
    # Forex reset at 22:00; at 10:00 → 12 hours away = 43200s
    now = datetime(2026, 4, 20, 10, 0, 0)
    assert seconds_until_reset("forex", now=now) == 12 * 3600


def test_seconds_until_reset_after_reset_rolls_to_next_day():
    # At 22:00 exactly → reset already happened, next reset in 24h
    now = datetime(2026, 4, 20, 22, 0, 0)
    assert seconds_until_reset("forex", now=now) == 24 * 3600


def test_seconds_until_reset_crypto_midnight():
    now = datetime(2026, 4, 20, 23, 0, 0)
    # Crypto resets at 00:00; 1h away
    assert seconds_until_reset("crypto", now=now) == 3600


def test_seconds_until_reset_minimum_60():
    # Just past reset hour → still at least 60s buffer
    now = datetime(2026, 4, 20, 22, 0, 1)
    assert seconds_until_reset("forex", now=now) >= 60


# ─── is_market_open ─────────────────────────────────────────────────────────


def test_forex_closed_on_saturday():
    saturday_noon = datetime(2026, 4, 18, 12, 0, 0)  # Saturday
    assert is_market_open("forex", now=saturday_noon) is False


def test_forex_closed_on_sunday():
    sunday_noon = datetime(2026, 4, 19, 12, 0, 0)  # Sunday
    assert is_market_open("forex", now=sunday_noon) is False


def test_forex_open_weekday_noon():
    monday_noon = datetime(2026, 4, 20, 12, 0, 0)  # Monday
    assert is_market_open("forex", now=monday_noon) is True


def test_forex_closed_during_daily_maintenance():
    # 22:30 on a weekday → inside 22-23 maintenance window
    monday_maint = datetime(2026, 4, 20, 22, 30, 0)
    assert is_market_open("forex", now=monday_maint) is False


def test_crypto_open_on_weekend():
    saturday_noon = datetime(2026, 4, 18, 12, 0, 0)
    assert is_market_open("crypto", now=saturday_noon) is True


def test_crypto_open_24h():
    # Even at 3am on Sunday
    sunday_3am = datetime(2026, 4, 19, 3, 0, 0)
    assert is_market_open("crypto", now=sunday_3am) is True


def test_index_uses_21_22_maintenance():
    monday_2130 = datetime(2026, 4, 20, 21, 30, 0)
    assert is_market_open("index", now=monday_2130) is False
    # Just before maintenance window
    monday_2059 = datetime(2026, 4, 20, 20, 59, 0)
    assert is_market_open("index", now=monday_2059) is True


def test_unknown_class_defaults_to_forex():
    monday_noon = datetime(2026, 4, 20, 12, 0, 0)
    assert is_market_open("something_weird", now=monday_noon) is True

    saturday = datetime(2026, 4, 18, 12, 0, 0)
    assert is_market_open("something_weird", now=saturday) is False


def test_stock_wrap_around_close_window():
    # Stock: closed 21:00 → 14:00 next day (wraps midnight).
    monday_22 = datetime(2026, 4, 20, 22, 0, 0)
    assert is_market_open("stock", now=monday_22) is False
    tuesday_13 = datetime(2026, 4, 21, 13, 0, 0)
    assert is_market_open("stock", now=tuesday_13) is False
    tuesday_15 = datetime(2026, 4, 21, 15, 0, 0)
    assert is_market_open("stock", now=tuesday_15) is True


# ─── supported_asset_classes ────────────────────────────────────────────────


def test_supported_asset_classes_includes_all():
    classes = supported_asset_classes()
    assert set(classes) == {"forex", "metal", "energy", "index", "crypto", "stock"}
