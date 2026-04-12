"""
Unit tests for mcp_server/agents/ — multi-agent architecture.
Tests with mocked AsyncAnthropic (Anthropic API).
"""

import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcp_server.agents.base import MODEL_ORCHESTRATOR, MODEL_SPECIALIST


class TestToolSubsets:
    def test_all_tools_defined(self):
        from mcp_server.agent_config import TOOLS
        all_names = {t["name"] for t in TOOLS}

        from mcp_server.agents.technical_analyst import TOOL_NAMES as tech
        from mcp_server.agents.fundamental_analyst import TOOL_NAMES as fund
        from mcp_server.agents.risk_analyst import TOOL_NAMES as risk_t
        from mcp_server.agents.orchestrator import ORCHESTRATOR_TOOL_NAMES as orch

        for n in tech: assert n in all_names, f"'{n}' missing"
        for n in fund: assert n in all_names, f"'{n}' missing"
        for n in risk_t: assert n in all_names, f"'{n}' missing"
        for n in orch: assert n in all_names, f"'{n}' missing"

    def test_technical_no_execution(self):
        from mcp_server.agents.technical_analyst import TOOL_NAMES
        assert not {"place_order", "modify_position", "close_position"} & set(TOOL_NAMES)

    def test_fundamental_no_execution(self):
        from mcp_server.agents.fundamental_analyst import TOOL_NAMES
        assert not {"place_order", "modify_position", "close_position"} & set(TOOL_NAMES)

    def test_risk_no_execution(self):
        from mcp_server.agents.risk_analyst import TOOL_NAMES
        assert not {"place_order", "modify_position", "close_position"} & set(TOOL_NAMES)

    def test_orchestrator_has_execution(self):
        from mcp_server.agents.orchestrator import ORCHESTRATOR_TOOL_NAMES
        assert "place_order" in ORCHESTRATOR_TOOL_NAMES


class TestModelSelection:
    def test_specialist_uses_haiku(self):
        assert "haiku" in MODEL_SPECIALIST.lower()

    def test_orchestrator_uses_sonnet(self):
        assert "sonnet" in MODEL_ORCHESTRATOR.lower()


class TestBaseAgentLoop:
    @pytest.mark.asyncio
    async def test_returns_error_without_key(self):
        from mcp_server.agents.base import run_agent_loop
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}):
            result = await run_agent_loop(system_prompt="test", user_message="test")
            assert "No ANTHROPIC_API_KEY" in result["response"]

    @pytest.mark.asyncio
    async def test_handles_text_response(self):
        from mcp_server.agents.base import run_agent_loop

        mock_block = MagicMock()
        mock_block.type = "text"
        mock_block.text = "HOLD recommended"

        mock_response = MagicMock()
        mock_response.content = [mock_block]
        mock_response.stop_reason = "end_turn"

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        with (
            patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}),
            patch("mcp_server.agents.base.AsyncAnthropic", return_value=mock_client),
        ):
            result = await run_agent_loop(system_prompt="test", user_message="Analyze")

        assert "HOLD recommended" in result["response"]
        assert result["turns"] == 1

    @pytest.mark.asyncio
    async def test_handles_api_error(self):
        from mcp_server.agents.base import run_agent_loop

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(side_effect=Exception("rate limited"))

        with (
            patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}),
            patch("mcp_server.agents.base.AsyncAnthropic", return_value=mock_client),
        ):
            result = await run_agent_loop(system_prompt="test", user_message="test")

        assert "error" in result


class TestOrchestratorSynthesis:
    def test_build_synthesis_message(self):
        from mcp_server.agents.orchestrator import _build_synthesis_message
        msg = _build_synthesis_message(
            job_type="candle_analysis", job_input={"symbol": "GOLD"},
            symbol="GOLD", timeframe="M15",
            technical_report="bullish", fundamental_report="neutral", risk_report="approved",
        )
        assert "Technical Analysis" in msg
        assert "bullish" in msg

    def test_synthesis_with_reflection(self):
        from mcp_server.agents.orchestrator import _build_synthesis_message
        msg = _build_synthesis_message(
            job_type="candle_analysis", job_input={"symbol": "GOLD"},
            symbol="GOLD", timeframe="M15",
            technical_report="b", fundamental_report="n", risk_report="a",
            reflection_report="Win rate 70%",
        )
        assert "Reflection" in msg
        assert "Win rate 70%" in msg


class TestMultiAgentIntegration:
    @pytest.mark.asyncio
    async def test_orchestrator_full_pipeline(self):
        from mcp_server.agents.orchestrator import run_multi_agent

        mock_result = {"response": "analysis done", "tool_calls": [], "turns": 2}

        with (
            patch("mcp_server.agents.orchestrator.reflector.reflect", AsyncMock(return_value={"response": "65% win rate", "tool_calls": [], "turns": 1})),
            patch("mcp_server.agents.orchestrator.technical_analyst.analyze", AsyncMock(return_value={"response": "bullish", "tool_calls": [], "turns": 1})),
            patch("mcp_server.agents.orchestrator.fundamental_analyst.analyze", AsyncMock(return_value={"response": "neutral", "tool_calls": [], "turns": 1})),
            patch("mcp_server.agents.orchestrator.risk_analyst.analyze", AsyncMock(return_value={"response": "approved", "tool_calls": [], "turns": 1})),
            patch("mcp_server.agents.orchestrator.run_agent_loop", AsyncMock(return_value=mock_result)),
        ):
            result = await run_multi_agent(job_type="candle_analysis", job_input={"symbol": "GOLD"})

        assert "decision" in result
        assert "specialists" in result

    @pytest.mark.asyncio
    async def test_specialist_error_graceful(self):
        from mcp_server.agents.orchestrator import run_multi_agent

        with (
            patch("mcp_server.agents.orchestrator.reflector.reflect", AsyncMock(return_value={"response": "", "tool_calls": [], "turns": 0})),
            patch("mcp_server.agents.orchestrator.technical_analyst.analyze", AsyncMock(side_effect=Exception("timeout"))),
            patch("mcp_server.agents.orchestrator.fundamental_analyst.analyze", AsyncMock(return_value={"response": "n", "tool_calls": [], "turns": 1})),
            patch("mcp_server.agents.orchestrator.risk_analyst.analyze", AsyncMock(return_value={"response": "a", "tool_calls": [], "turns": 1})),
            patch("mcp_server.agents.orchestrator.run_agent_loop", AsyncMock(return_value={"response": "HOLD", "tool_calls": [], "turns": 1, "duration_s": 1})),
        ):
            result = await run_multi_agent(job_type="candle_analysis", job_input={"symbol": "GOLD"})

        assert "decision" in result
        assert result.get("errors") is not None
