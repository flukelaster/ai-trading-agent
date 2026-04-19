"""Tests for canonical → broker alias resolution at the MT5 boundary."""

import pytest

from app.config import SYMBOL_PROFILES
from app.mt5.symbol_resolver import to_broker_alias


@pytest.fixture(autouse=True)
def restore_profiles():
    snapshot = dict(SYMBOL_PROFILES)
    yield
    SYMBOL_PROFILES.clear()
    SYMBOL_PROFILES.update(snapshot)


def test_returns_broker_alias_when_set():
    SYMBOL_PROFILES["GOLD"] = {"broker_alias": "GOLDm#"}
    assert to_broker_alias("GOLD") == "GOLDm#"


def test_returns_symbol_when_alias_empty():
    SYMBOL_PROFILES["EURUSD"] = {"broker_alias": ""}
    assert to_broker_alias("EURUSD") == "EURUSD"


def test_returns_symbol_when_alias_none():
    SYMBOL_PROFILES["EURUSD"] = {"broker_alias": None}
    assert to_broker_alias("EURUSD") == "EURUSD"


def test_returns_symbol_when_no_alias_key():
    SYMBOL_PROFILES["EURUSD"] = {"pip_value": 10}
    assert to_broker_alias("EURUSD") == "EURUSD"


def test_returns_symbol_when_profile_missing():
    SYMBOL_PROFILES.pop("UNKNOWN", None)
    assert to_broker_alias("UNKNOWN") == "UNKNOWN"


def test_idempotent_on_alias_input():
    SYMBOL_PROFILES["GOLDm#"] = {"broker_alias": "GOLDm#"}
    assert to_broker_alias("GOLDm#") == "GOLDm#"


def test_empty_input_returns_empty():
    assert to_broker_alias("") == ""


def test_none_input_returns_none():
    assert to_broker_alias(None) is None
