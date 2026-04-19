"""Unit tests for multi-symbol hardening (batch 1 + 3).

Covers:
- get_active_symbols fallback path (no BotManager → SYMBOL_PROFILES keys)
- agent_config raises ValueError when job_input lacks 'symbol'
- prompt_registry sentiment default contains `{symbol}` placeholder, not literal GOLD
"""

import pytest

from app.config import SYMBOL_PROFILES, get_active_symbols


@pytest.fixture(autouse=True)
def restore_profiles():
    snapshot = dict(SYMBOL_PROFILES)
    yield
    SYMBOL_PROFILES.clear()
    SYMBOL_PROFILES.update(snapshot)


def test_get_active_symbols_falls_back_to_profiles_when_no_manager():
    SYMBOL_PROFILES.clear()
    SYMBOL_PROFILES["GOLD"] = {"pip_value": 1}
    SYMBOL_PROFILES["EURUSD"] = {"pip_value": 10}
    # alias entries must be excluded
    SYMBOL_PROFILES["GOLDm#"] = {"pip_value": 1, "canonical": "GOLD"}

    active = get_active_symbols()

    assert "GOLD" in active
    assert "EURUSD" in active
    assert "GOLDm#" not in active


def test_get_active_symbols_returns_list_even_when_empty():
    SYMBOL_PROFILES.clear()
    assert get_active_symbols() == []


def test_agent_config_candle_analysis_requires_symbol():
    from mcp_server.agent_config import _build_user_message

    with pytest.raises(ValueError, match="symbol"):
        _build_user_message("candle_analysis", {})

    with pytest.raises(ValueError, match="symbol"):
        _build_user_message("candle_analysis", None)


def test_agent_config_manual_analysis_requires_symbol():
    from mcp_server.agent_config import _build_user_message

    with pytest.raises(ValueError, match="symbol"):
        _build_user_message("manual_analysis", {"timeframe": "M15"})


def test_agent_config_accepts_valid_symbol():
    from mcp_server.agent_config import _build_user_message

    msg = _build_user_message("candle_analysis", {"symbol": "EURUSD", "timeframe": "M15"})
    assert "EURUSD" in msg
    assert "M15" in msg


def test_agent_config_weekly_review_no_symbol_required():
    from mcp_server.agent_config import _build_user_message

    # weekly_review shouldn't require symbol
    msg = _build_user_message("weekly_review", None)
    assert "weekly trading review" in msg


def test_prompt_registry_sentiment_default_is_symbol_agnostic():
    from mcp_server.agents import prompt_registry

    # Force reload to pick up new default
    prompt_registry._defaults_loaded = False
    prompt_registry._DEFAULTS.clear()

    default = prompt_registry.get_default_prompt("sentiment")

    # Old behavior baked "GOLD" literal; new behavior uses {symbol} placeholder
    assert "{symbol}" in default
    # Must not contain the literal hardcoded "GOLD " in instructional text
    # (the word "GOLD" may still appear in the asset-class framework examples)
    # Key invariant: the target instrument slot is a placeholder.
    assert "headlines for the instrument **{symbol}**" in default
