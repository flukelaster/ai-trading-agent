"""
Unit tests for mcp_server/agents/ — multi-agent architecture.

Tests the orchestrator, specialist agents, and base agent loop.
Mocks the Claude API to avoid real API calls.
"""

import sys
import os
import json
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

import pytest

from mcp_server.agents.base import filter_tools, MODEL_ORCHESTRATOR, MODEL_SPECIALIST
from mcp_server.agent_config import TOOLS


class TestFilterTools:
    def test_filter_existing_tools(self):
        tools = filter_tools(["get_tick", "get_ohlcv"])
        assert len(tools) == 2
        names = {t["name"] for t in tools}
        assert names == {"get_tick", "get_ohlcv"}

    def test_filter_nonexistent_tools(self):
        tools = filter_tools(["nonexistent_tool"])
        assert len(tools) == 0

    def test_filter_empty(self):
        tools = filter_tools([])
        assert len(tools) == 0

    def test_all_tools_defined(self):
        """Verify all tool names referenced by agents exist in TOOLS."""
        all_tool_names = {t["name"] for t in TOOLS}

        from mcp_server.agents.technical_analyst import TOOL_NAMES as tech_tools
        from mcp_server.agents.fundamental_analyst import TOOL_NAMES as fund_tools
        from mcp_server.agents.risk_analyst import TOOL_NAMES as risk_tools
        from mcp_server.agents.orchestrator import ORCHESTRATOR_TOOL_NAMES as orch_tools

        for name in tech_tools:
            assert name in all_tool_names, f"Technical tool '{name}' not in TOOLS"
        for name in fund_tools:
            assert name in all_tool_names, f"Fundamental tool '{name}' not in TOOLS"
        for name in risk_tools:
            assert name in all_tool_names, f"Risk tool '{name}' not in TOOLS"
        for name in orch_tools:
            assert name in all_tool_names, f"Orchestrator tool '{name}' not in TOOLS"


class TestToolSubsets:
    """Verify each specialist gets the right tools and no execution tools."""

    def test_technical_has_no_execution_tools(self):
        from mcp_server.agents.technical_analyst import TOOL_NAMES
        execution_tools = {"place_order", "modify_position", "close_position"}
        assert not set(TOOL_NAMES) & execution_tools

    def test_fundamental_has_no_execution_tools(self):
        from mcp_server.agents.fundamental_analyst import TOOL_NAMES
        execution_tools = {"place_order", "modify_position", "close_position"}
        assert not set(TOOL_NAMES) & execution_tools

    def test_risk_has_no_execution_tools(self):
        from mcp_server.agents.risk_analyst import TOOL_NAMES
        execution_tools = {"place_order", "modify_position", "close_position"}
        assert not set(TOOL_NAMES) & execution_tools

    def test_orchestrator_has_execution_tools(self):
        from mcp_server.agents.orchestrator import ORCHESTRATOR_TOOL_NAMES
        assert "place_order" in ORCHESTRATOR_TOOL_NAMES
        assert "log_decision" in ORCHESTRATOR_TOOL_NAMES

    def test_technical_has_indicator_tools(self):
        from mcp_server.agents.technical_analyst import TOOL_NAMES
        assert "run_full_analysis" in TOOL_NAMES
        assert "get_tick" in TOOL_NAMES

    def test_fundamental_has_sentiment_tools(self):
        from mcp_server.agents.fundamental_analyst import TOOL_NAMES
        assert "get_sentiment" in TOOL_NAMES
        assert "get_performance" in TOOL_NAMES

    def test_risk_has_portfolio_tools(self):
        from mcp_server.agents.risk_analyst import TOOL_NAMES
        assert "get_account" in TOOL_NAMES
        assert "validate_trade" in TOOL_NAMES
        assert "check_correlation" in TOOL_NAMES


class TestModelSelection:
    def test_specialist_uses_haiku(self):
        assert "haiku" in MODEL_SPECIALIST.lower()

    def test_orchestrator_uses_sonnet(self):
        assert "sonnet" in MODEL_ORCHESTRATOR.lower()


class TestBaseAgentLoop:
    @pytest.mark.asyncio
    async def test_returns_error_without_token(self):
        from mcp_server.agents.base import run_agent_loop
        with patch.dict(os.environ, {}, clear=True):
            # Remove CLAUDE_OAUTH_TOKEN if set
            os.environ.pop("CLAUDE_OAUTH_TOKEN", None)
            result = await run_agent_loop(
                system_prompt="test",
                user_message="test",
                tools=[],
                oauth_token=None,
            )
            assert "No OAuth token" in result["response"]
            assert result["turns"] == 0

    @pytest.mark.asyncio
    async def test_handles_end_turn_response(self):
        """When Claude responds with end_turn (no tool calls), return the text."""
        from mcp_server.agents.base import run_agent_loop

        mock_text_block = MagicMock()
        mock_text_block.type = "text"
        mock_text_block.text = "Analysis complete: HOLD recommended"

        mock_response = MagicMock()
        mock_response.content = [mock_text_block]
        mock_response.stop_reason = "end_turn"

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        with patch("mcp_server.agents.base.AsyncAnthropic", return_value=mock_client):
            result = await run_agent_loop(
                system_prompt="test",
                user_message="Analyze GOLD",
                tools=[],
                oauth_token="test-token",
            )

        assert "HOLD recommended" in result["response"]
        assert result["turns"] == 1
        assert result["tool_calls"] == []

    @pytest.mark.asyncio
    async def test_handles_tool_use_then_end(self):
        """Simulate: Claude calls a tool, gets result, then gives final answer."""
        from mcp_server.agents.base import run_agent_loop

        # First response: tool_use
        mock_tool_block = MagicMock()
        mock_tool_block.type = "tool_use"
        mock_tool_block.name = "get_tick"
        mock_tool_block.input = {"symbol": "GOLD"}
        mock_tool_block.id = "tool_1"

        mock_response1 = MagicMock()
        mock_response1.content = [mock_tool_block]
        mock_response1.stop_reason = "tool_use"

        # Second response: end_turn
        mock_text_block = MagicMock()
        mock_text_block.type = "text"
        mock_text_block.text = "GOLD is at 2450, BUY signal"

        mock_response2 = MagicMock()
        mock_response2.content = [mock_text_block]
        mock_response2.stop_reason = "end_turn"

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(side_effect=[mock_response1, mock_response2])

        with (
            patch("mcp_server.agents.base.AsyncAnthropic", return_value=mock_client),
            patch("mcp_server.agents.base._execute_tool", return_value='{"ask": 2451, "bid": 2450}'),
        ):
            result = await run_agent_loop(
                system_prompt="test",
                user_message="Analyze GOLD",
                tools=filter_tools(["get_tick"]),
                oauth_token="test-token",
            )

        assert "BUY signal" in result["response"]
        assert result["turns"] == 2
        assert len(result["tool_calls"]) == 1
        assert result["tool_calls"][0]["tool"] == "get_tick"

    @pytest.mark.asyncio
    async def test_handles_api_error(self):
        """Claude API error should be caught and returned gracefully."""
        from mcp_server.agents.base import run_agent_loop

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(side_effect=Exception("rate limited"))

        with patch("mcp_server.agents.base.AsyncAnthropic", return_value=mock_client):
            result = await run_agent_loop(
                system_prompt="test",
                user_message="test",
                tools=[],
                oauth_token="test-token",
            )

        assert "error" in result
        assert "rate limited" in result["error"]


class TestOrchestratorSynthesis:
    def test_build_synthesis_message(self):
        from mcp_server.agents.orchestrator import _build_synthesis_message

        msg = _build_synthesis_message(
            job_type="candle_analysis",
            job_input={"symbol": "GOLD", "timeframe": "M15"},
            symbol="GOLD",
            timeframe="M15",
            technical_report="RSI: 65, EMA bullish crossover",
            fundamental_report="Sentiment: bullish 0.72",
            risk_report="APPROVED, 0.05 lot recommended",
        )

        assert "Technical Analysis Report" in msg
        assert "Fundamental Analysis Report" in msg
        assert "Risk Assessment Report" in msg
        assert "RSI: 65" in msg
        assert "bullish 0.72" in msg
        assert "APPROVED" in msg
        assert "GOLD" in msg

    def test_synthesis_message_for_manual_analysis(self):
        from mcp_server.agents.orchestrator import _build_synthesis_message

        msg = _build_synthesis_message(
            job_type="manual_analysis",
            job_input={"symbol": "BTCUSD"},
            symbol="BTCUSD",
            timeframe="H1",
            technical_report="bearish",
            fundamental_report="neutral",
            risk_report="caution",
        )
        assert "manual analysis" in msg.lower()
        assert "BTCUSD" in msg


class TestMultiAgentIntegration:
    @pytest.mark.asyncio
    async def test_orchestrator_runs_specialists_and_synthesizes(self):
        """Full multi-agent pipeline with mocked Claude responses."""
        from mcp_server.agents.orchestrator import run_multi_agent

        # Mock all specialist analyze functions
        mock_tech = AsyncMock(return_value={
            "response": "RSI 65, EMA bullish, ADX strong. Signal: BUY 0.7 confidence",
            "tool_calls": [{"tool": "run_full_analysis"}],
            "turns": 2,
        })
        mock_fund = AsyncMock(return_value={
            "response": "Sentiment bullish 0.72, 5-day win streak. Bias: BULLISH 0.7",
            "tool_calls": [{"tool": "get_sentiment"}],
            "turns": 2,
        })
        mock_risk = AsyncMock(return_value={
            "response": "Balance 10k, 1 position, no correlation. Verdict: APPROVED 0.8",
            "tool_calls": [{"tool": "get_account"}],
            "turns": 3,
        })

        # Mock orchestrator's agent loop
        mock_orch_result = {
            "response": "Based on aligned technical+fundamental bullish signals and risk approval, executing BUY 0.05 GOLD",
            "tool_calls": [{"tool": "place_order"}, {"tool": "log_decision"}],
            "turns": 3,
            "duration_s": 2.5,
        }

        with (
            patch("mcp_server.agents.orchestrator.technical_analyst.analyze", mock_tech),
            patch("mcp_server.agents.orchestrator.fundamental_analyst.analyze", mock_fund),
            patch("mcp_server.agents.orchestrator.risk_analyst.analyze", mock_risk),
            patch("mcp_server.agents.orchestrator.run_agent_loop", AsyncMock(return_value=mock_orch_result)),
        ):
            result = await run_multi_agent(
                job_type="candle_analysis",
                job_input={"symbol": "GOLD", "timeframe": "M15"},
                oauth_token="test-token",
            )

        # Verify structure
        assert "decision" in result
        assert "specialists" in result
        assert "technical" in result["specialists"]
        assert "fundamental" in result["specialists"]
        assert "risk" in result["specialists"]
        assert "orchestrator_turns" in result
        assert "total_tool_calls" in result
        assert "total_duration_s" in result

        # Verify specialist reports are included
        assert "RSI 65" in result["specialists"]["technical"]["report"]
        assert "bullish 0.72" in result["specialists"]["fundamental"]["report"]
        assert "APPROVED" in result["specialists"]["risk"]["report"]

    @pytest.mark.asyncio
    async def test_specialist_error_handled_gracefully(self):
        """If one specialist fails, the orchestrator still runs with available data."""
        from mcp_server.agents.orchestrator import run_multi_agent

        mock_tech = AsyncMock(side_effect=Exception("MT5 Bridge timeout"))
        mock_fund = AsyncMock(return_value={
            "response": "Sentiment neutral", "tool_calls": [], "turns": 1,
        })
        mock_risk = AsyncMock(return_value={
            "response": "CAUTION", "tool_calls": [], "turns": 1,
        })

        mock_orch_result = {
            "response": "Technical analysis unavailable, holding due to incomplete data",
            "tool_calls": [{"tool": "log_decision"}],
            "turns": 2,
            "duration_s": 1.0,
        }

        with (
            patch("mcp_server.agents.orchestrator.technical_analyst.analyze", mock_tech),
            patch("mcp_server.agents.orchestrator.fundamental_analyst.analyze", mock_fund),
            patch("mcp_server.agents.orchestrator.risk_analyst.analyze", mock_risk),
            patch("mcp_server.agents.orchestrator.run_agent_loop", AsyncMock(return_value=mock_orch_result)),
        ):
            result = await run_multi_agent(
                job_type="candle_analysis",
                job_input={"symbol": "GOLD"},
                oauth_token="test-token",
            )

        # Should still complete
        assert "decision" in result
        # Error should be recorded
        assert result.get("errors") is not None
        assert "technical" in result["errors"]
        # Technical report should contain error
        assert "ERROR" in result["specialists"]["technical"]["report"]


class TestAgentEntrypointMultiMode:
    @pytest.mark.asyncio
    async def test_multi_mode_env_var(self):
        """When AGENT_MODE=multi, entrypoint should use run_multi_agent."""
        from app.runner.agent_entrypoint import execute_job

        mock_result = {"decision": "HOLD", "total_duration_s": 5.0, "orchestrator_turns": 3, "total_tool_calls": 8}

        with (
            patch.dict(os.environ, {"CLAUDE_OAUTH_TOKEN": "test", "AGENT_MODE": "multi"}),
            patch("app.runner.agent_entrypoint._MULTI_AGENT_AVAILABLE", True),
            patch("app.runner.agent_entrypoint._AGENT_AVAILABLE", True),
            patch("app.runner.agent_entrypoint.run_multi_agent", create=True, new=AsyncMock(return_value=mock_result)),
            patch("app.runner.agent_entrypoint.init_broker", create=True),
        ):
            result = await execute_job(1, "candle_analysis", {"symbol": "GOLD"}, 1)
            assert result["decision"] == "HOLD"

    @pytest.mark.asyncio
    async def test_single_mode_default(self):
        """Without AGENT_MODE=multi, entrypoint should use run_agent (single)."""
        from app.runner.agent_entrypoint import execute_job

        mock_result = {"decision": "BUY GOLD", "turns": 5, "duration_s": 3.0, "tool_calls": []}

        with (
            patch.dict(os.environ, {"CLAUDE_OAUTH_TOKEN": "test"}, clear=False),
            patch("app.runner.agent_entrypoint._AGENT_AVAILABLE", True),
            patch("app.runner.agent_entrypoint.run_agent", create=True, new=AsyncMock(return_value=mock_result)),
            patch("app.runner.agent_entrypoint.init_broker", create=True),
        ):
            os.environ.pop("AGENT_MODE", None)
            result = await execute_job(1, "candle_analysis", {"symbol": "GOLD"}, 1)
            assert result["decision"] == "BUY GOLD"
