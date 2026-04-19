"""
Unit tests for Phase E features — learning, session memory, strategy generation, reflector.
"""

import json
from unittest.mock import AsyncMock, patch

import pytest

from mcp_server.tools.strategy_gen import (
    get_strategy_profiles,
    recommend_strategy,
    generate_strategy_config,
    generate_ensemble_config,
    STRATEGY_PROFILES,
)
from mcp_server.tools.session import (
    init_session,
    save_context,
    get_context,
    save_learning,
    get_learnings,
    clear_context,
)


# ─── Strategy Generation Tests ──────────────────────────────────────────────


class TestGetStrategyProfiles:
    def test_returns_all_profiles(self):
        result = get_strategy_profiles()
        assert result["total"] == len(STRATEGY_PROFILES)
        assert "ema_crossover" in result["strategies"]
        assert "ensemble" in result["strategies"]

    def test_profiles_have_required_fields(self):
        result = get_strategy_profiles()
        for name, profile in result["strategies"].items():
            assert "description" in profile
            assert "best_regime" in profile
            assert "params" in profile


class TestRecommendStrategy:
    def test_trending_recommends_ema(self):
        result = recommend_strategy("trending", "GOLD")
        rec_name = result["recommended"]["name"]
        assert rec_name in ("ema_crossover", "breakout")

    def test_ranging_recommends_mean_reversion(self):
        result = recommend_strategy("ranging", "GOLD")
        rec_name = result["recommended"]["name"]
        assert rec_name in ("mean_reversion", "rsi_filter")

    def test_unknown_regime_returns_ensemble(self):
        result = recommend_strategy("unknown_regime", "GOLD")
        assert result["recommended"]["name"] == "ensemble"

    def test_includes_alternatives(self):
        result = recommend_strategy("trending", "GOLD")
        assert "alternatives" in result
        assert "other_strategies" in result


class TestGenerateStrategyConfig:
    def test_basic_config(self):
        result = generate_strategy_config("ema_crossover")
        assert result["base_strategy"] == "ema_crossover"
        assert "params" in result
        assert result["params"]["fast_period"] == 20

    def test_with_overrides(self):
        result = generate_strategy_config("ema_crossover", {"fast_period": 10})
        assert result["params"]["fast_period"] == 10
        assert result["params"]["slow_period"] == 50  # unchanged

    def test_rejects_out_of_range(self):
        result = generate_strategy_config("ema_crossover", {"fast_period": 999})
        assert "error" in result

    def test_rejects_unknown_strategy(self):
        result = generate_strategy_config("nonexistent")
        assert "error" in result

    def test_rejects_unknown_param(self):
        result = generate_strategy_config("ema_crossover", {"unknown_param": 5})
        assert "error" in result

    def test_custom_name(self):
        result = generate_strategy_config("rsi_filter", name="my_rsi")
        assert result["name"] == "my_rsi"


class TestGenerateEnsembleConfig:
    def test_valid_ensemble(self):
        result = generate_ensemble_config(
            {"ema_crossover": 0.4, "breakout": 0.3, "mean_reversion": 0.3}
        )
        assert result["base_strategy"] == "ensemble"
        assert "composition" in result["params"]
        assert "ema_crossover:0.4" in result["params"]["composition"]

    def test_rejects_bad_weights_sum(self):
        result = generate_ensemble_config({"ema_crossover": 0.5, "breakout": 0.1})
        assert "error" in result
        assert "sum" in result["error"].lower()

    def test_rejects_unknown_strategy(self):
        result = generate_ensemble_config({"ema_crossover": 0.5, "nonexistent": 0.5})
        assert "error" in result

    def test_rejects_ensemble_in_ensemble(self):
        result = generate_ensemble_config({"ensemble": 0.5, "ema_crossover": 0.5})
        assert "error" in result


# ─── Session Memory Tests ────────────────────────────────────────────────────


class TestSessionMemory:
    @pytest.fixture(autouse=True)
    def setup_session(self, redis_client):
        init_session(redis_client)

    @pytest.mark.asyncio
    async def test_save_and_get_context(self):
        await save_context("GOLD", {"trend": "bullish", "rsi": 65})
        ctx = await get_context("GOLD")
        assert ctx["trend"] == "bullish"
        assert ctx["rsi"] == 65
        assert "last_updated" in ctx

    @pytest.mark.asyncio
    async def test_context_merges(self):
        await save_context("GOLD", {"trend": "bullish"})
        await save_context("GOLD", {"volatility": "high"})
        ctx = await get_context("GOLD")
        assert ctx["trend"] == "bullish"
        assert ctx["volatility"] == "high"

    @pytest.mark.asyncio
    async def test_get_empty_context(self):
        ctx = await get_context("UNKNOWN_SYMBOL")
        assert ctx == {}

    @pytest.mark.asyncio
    async def test_clear_context(self):
        await save_context("GOLD", {"data": "test"})
        await clear_context("GOLD")
        ctx = await get_context("GOLD")
        assert ctx == {}

    @pytest.mark.asyncio
    async def test_save_and_get_learnings(self):
        await save_learning("EMA crossover works best in trending markets", "strategy")
        await save_learning("Reduce lot size during NFP", "risk")

        all_learnings = await get_learnings()
        assert all_learnings["count"] == 2

        strategy_learnings = await get_learnings(category="strategy")
        assert strategy_learnings["count"] == 1
        assert "EMA" in strategy_learnings["entries"][0]["text"]

    @pytest.mark.asyncio
    async def test_learnings_capped_at_50(self):
        for i in range(55):
            await save_learning(f"Learning {i}")
        result = await get_learnings()
        assert result["count"] == 50

    @pytest.mark.asyncio
    async def test_empty_learnings(self):
        result = await get_learnings()
        assert result["count"] == 0
        assert result["entries"] == []


# ─── Learning Tools Tests ────────────────────────────────────────────────────


class TestLearningTools:
    @pytest.mark.asyncio
    async def test_detect_regime_calls_indicators(self):
        """detect_regime should call full_analysis and classify the regime."""
        mock_analysis = {
            "adx": 30.0,
            "atr": 15.0,
            "trend": "bullish",
            "trend_strength": "strong",
            "rsi": 62.0,
            "price_vs_bb": "inside",
        }
        with patch("mcp_server.tools.indicators.full_analysis", AsyncMock(return_value=mock_analysis)):
            from mcp_server.tools.learning import detect_regime
            result = await detect_regime("GOLD", "M15")

        assert result["regime"] == "trending"
        assert "ema_crossover" in result["recommended_strategies"]
        assert result["symbol"] == "GOLD"

    @pytest.mark.asyncio
    async def test_detect_regime_ranging(self):
        mock_analysis = {
            "adx": 15.0, "atr": 5.0, "trend": "neutral", "trend_strength": "weak",
            "rsi": 50.0, "price_vs_bb": "inside",
        }
        with patch("mcp_server.tools.indicators.full_analysis", AsyncMock(return_value=mock_analysis)):
            from mcp_server.tools.learning import detect_regime
            result = await detect_regime("GOLD")

        assert result["regime"] == "ranging"
        assert "mean_reversion" in result["recommended_strategies"]

    @pytest.mark.asyncio
    async def test_detect_regime_handles_error(self):
        with patch("mcp_server.tools.indicators.full_analysis", AsyncMock(return_value={"error": "MT5 down"})):
            from mcp_server.tools.learning import detect_regime
            result = await detect_regime("GOLD")
        assert "error" in result


# ─── Reflector Agent Tests ───────────────────────────────────────────────────


class TestReflectorAgent:
    def test_reflector_tool_names(self):
        from mcp_server.agents.reflector import TOOL_NAMES
        assert "analyze_recent_trades" in TOOL_NAMES
        assert "detect_regime" in TOOL_NAMES
        assert "get_learnings" in TOOL_NAMES
        assert "save_context" in TOOL_NAMES
        assert "recommend_strategy" in TOOL_NAMES

    def test_reflector_has_no_execution_tools(self):
        from mcp_server.agents.reflector import TOOL_NAMES
        execution_tools = {"place_order", "modify_position", "close_position"}
        assert not set(TOOL_NAMES) & execution_tools

    def test_all_reflector_tools_are_strings(self):
        from mcp_server.agents.reflector import TOOL_NAMES
        assert len(TOOL_NAMES) > 0
        for name in TOOL_NAMES:
            assert isinstance(name, str), f"Tool name must be str, got {type(name)}"


# ─── Updated Orchestrator Tests ──────────────────────────────────────────────


class TestOrchestratorWithReflection:
    def test_synthesis_message_includes_reflection(self):
        from mcp_server.agents.orchestrator import _build_synthesis_message

        msg = _build_synthesis_message(
            job_type="candle_analysis",
            job_input={"symbol": "GOLD"},
            symbol="GOLD",
            timeframe="M15",
            technical_report="bullish",
            fundamental_report="neutral",
            risk_report="approved",
            reflection_report="Win rate 70% last 7d, trending regime, recommend EMA strategy",
        )

        assert "Reflection" in msg
        assert "Win rate 70%" in msg
        assert "Technical Analysis" in msg

    def test_synthesis_message_without_reflection(self):
        from mcp_server.agents.orchestrator import _build_synthesis_message

        msg = _build_synthesis_message(
            job_type="candle_analysis",
            job_input={"symbol": "GOLD"},
            symbol="GOLD",
            timeframe="M15",
            technical_report="bearish",
            fundamental_report="bearish",
            risk_report="caution",
        )

        # No reflection section when empty
        assert "Reflection" not in msg
        assert "Technical Analysis" in msg

    @pytest.mark.asyncio
    async def test_orchestrator_runs_reflector_before_specialists(self):
        """Multi-agent pipeline should run reflector as Phase 0."""
        from mcp_server.agents.orchestrator import run_multi_agent

        mock_reflector = AsyncMock(return_value={
            "response": "7-day win rate 65%, trending regime",
            "tool_calls": [{"tool": "analyze_recent_trades"}],
            "turns": 3,
        })
        mock_tech = AsyncMock(return_value={"response": "bullish", "tool_calls": [], "turns": 1})
        mock_fund = AsyncMock(return_value={"response": "neutral", "tool_calls": [], "turns": 1})
        mock_risk = AsyncMock(return_value={"response": "approved", "tool_calls": [], "turns": 1})

        mock_orch = {
            "response": "BUY 0.05 GOLD based on confluence",
            "tool_calls": [],
            "turns": 2,
            "duration_s": 1.0,
        }

        with (
            patch("mcp_server.agents.orchestrator.reflector.reflect", mock_reflector),
            patch("mcp_server.agents.orchestrator.technical_analyst.analyze", mock_tech),
            patch("mcp_server.agents.orchestrator.fundamental_analyst.analyze", mock_fund),
            patch("mcp_server.agents.orchestrator.risk_analyst.analyze", mock_risk),
            patch("mcp_server.agents.orchestrator.run_agent_loop", AsyncMock(return_value=mock_orch)),
        ):
            result = await run_multi_agent(
                job_type="candle_analysis",
                job_input={"symbol": "GOLD"},
                oauth_token="test",
            )

        assert "reflector" in result["specialists"]
        assert "65%" in result["specialists"]["reflector"]["report"]
        mock_reflector.assert_awaited_once()
