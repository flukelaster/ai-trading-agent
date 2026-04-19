"""
Unit tests for Phase F — rollout modes, broker enforcement, deploy readiness.
"""

import os
from unittest.mock import AsyncMock, patch

import pytest

from mcp_server.guardrails import (
    MICRO_MAX_LOT,
    GuardrailResult,
    TradingGuardrails,
)


@pytest.fixture
def guardrails(redis_client):
    return TradingGuardrails(redis_client)


# ─── Rollout Mode in Guardrails ─────────────────────────────────────────────


class TestRolloutModeGuardrails:
    def test_default_mode_is_shadow(self, guardrails):
        os.environ.pop("ROLLOUT_MODE", None)
        assert guardrails.get_rollout_mode() == "shadow"

    def test_env_override(self, guardrails):
        with patch.dict(os.environ, {"ROLLOUT_MODE": "live"}):
            assert guardrails.get_rollout_mode() == "live"

    def test_invalid_mode_defaults_to_shadow(self, guardrails):
        with patch.dict(os.environ, {"ROLLOUT_MODE": "invalid"}):
            assert guardrails.get_rollout_mode() == "shadow"

    @pytest.mark.asyncio
    async def test_set_and_get_persisted(self, guardrails):
        await guardrails.set_rollout_mode("micro")
        mode = await guardrails.get_persisted_rollout_mode()
        assert mode == "micro"

    @pytest.mark.asyncio
    async def test_set_invalid_mode_raises(self, guardrails):
        with pytest.raises(ValueError, match="Invalid rollout mode"):
            await guardrails.set_rollout_mode("invalid")

    def test_check_shadow_mode(self, guardrails):
        with patch.dict(os.environ, {"ROLLOUT_MODE": "shadow"}):
            result = guardrails.check_rollout_mode(0.5)
            assert result.allowed is False
            assert "SHADOW" in result.reason

    def test_check_paper_mode(self, guardrails):
        with patch.dict(os.environ, {"ROLLOUT_MODE": "paper"}):
            result = guardrails.check_rollout_mode(0.5)
            assert result.allowed is False
            assert "PAPER" in result.reason

    def test_check_micro_mode_normal_lot(self, guardrails):
        with patch.dict(os.environ, {"ROLLOUT_MODE": "micro"}):
            result = guardrails.check_rollout_mode(0.01)
            assert result.allowed is True

    def test_check_micro_mode_caps_lot(self, guardrails):
        with patch.dict(os.environ, {"ROLLOUT_MODE": "micro"}):
            result = guardrails.check_rollout_mode(0.5)
            assert result.allowed is True
            assert "capped" in result.reason

    def test_check_live_mode(self, guardrails):
        with patch.dict(os.environ, {"ROLLOUT_MODE": "live"}):
            result = guardrails.check_rollout_mode(0.5)
            assert result.allowed is True
            assert result.reason == ""


# ─── Broker Rollout Mode Enforcement ────────────────────────────────────────


class TestBrokerRolloutMode:
    @pytest.mark.asyncio
    async def test_shadow_mode_logs_only(self):
        """In shadow mode, place_order should NOT execute and should return would_execute."""
        from mcp_server.guardrails import TradingGuardrails
        from mcp_server.tools import broker

        mock_connector = AsyncMock()
        mock_connector.get_account.return_value = {"success": True, "data": {"balance": 10000, "profit": 0}}
        mock_connector.get_positions.return_value = {"success": True, "data": []}
        mock_connector.get_tick.return_value = {"success": True, "data": {"ask": 2450, "bid": 2449}}

        mock_guardrails = AsyncMock(spec=TradingGuardrails)
        mock_guardrails.validate_order = AsyncMock(return_value=GuardrailResult(True))
        mock_guardrails.get_rollout_mode.return_value = "shadow"
        mock_guardrails.check_rollout_mode.return_value = GuardrailResult(False, "SHADOW MODE: order logged")

        broker._connector = mock_connector
        broker._guardrails = mock_guardrails

        result = await broker.place_order("GOLD", "BUY", 0.1, 2440, 2470)

        assert result["executed"] is False
        assert result["mode"] == "shadow"
        assert "would_execute" in result
        assert result["would_execute"]["lot"] == 0.1
        mock_connector.place_order.assert_not_called()

    @pytest.mark.asyncio
    async def test_paper_mode_simulates(self):
        """Paper mode should simulate execution with a fake ticket."""
        from mcp_server.guardrails import TradingGuardrails
        from mcp_server.tools import broker

        mock_connector = AsyncMock()
        mock_connector.get_account.return_value = {"success": True, "data": {"balance": 10000, "profit": 0}}
        mock_connector.get_positions.return_value = {"success": True, "data": []}
        mock_connector.get_tick.return_value = {"success": True, "data": {"ask": 2450, "bid": 2449}}

        mock_guardrails = AsyncMock(spec=TradingGuardrails)
        mock_guardrails.validate_order = AsyncMock(return_value=GuardrailResult(True))
        mock_guardrails.get_rollout_mode.return_value = "paper"
        mock_guardrails.check_rollout_mode.return_value = GuardrailResult(False, "PAPER MODE")

        broker._connector = mock_connector
        broker._guardrails = mock_guardrails

        result = await broker.place_order("GOLD", "BUY", 0.1, 2440, 2470)

        assert result["executed"] is True
        assert result["mode"] == "paper"
        assert result["order"]["simulated"] is True
        assert result["order"]["ticket"] >= 900000
        mock_connector.place_order.assert_not_called()

    @pytest.mark.asyncio
    async def test_micro_mode_caps_lot(self):
        """Micro mode should cap lot at MICRO_MAX_LOT and execute for real."""
        from mcp_server.guardrails import TradingGuardrails
        from mcp_server.tools import broker

        mock_connector = AsyncMock()
        mock_connector.get_account.return_value = {"success": True, "data": {"balance": 10000, "profit": 0}}
        mock_connector.get_positions.return_value = {"success": True, "data": []}
        mock_connector.get_tick.return_value = {"success": True, "data": {"ask": 2450, "bid": 2449}}
        mock_connector.place_order.return_value = {"success": True, "data": {"ticket": 12345, "lot": 0.01}}

        mock_guardrails = AsyncMock(spec=TradingGuardrails)
        mock_guardrails.validate_order = AsyncMock(return_value=GuardrailResult(True))
        mock_guardrails.get_rollout_mode.return_value = "micro"
        mock_guardrails.check_rollout_mode.return_value = GuardrailResult(True, "MICRO MODE: lot capped")
        mock_guardrails.record_trade = AsyncMock()

        broker._connector = mock_connector
        broker._guardrails = mock_guardrails

        result = await broker.place_order("GOLD", "BUY", 0.5, 2440, 2470)

        assert result["executed"] is True
        assert result["mode"] == "micro"
        # Verify lot was capped in the call to connector
        call_kwargs = mock_connector.place_order.call_args
        actual_lot = call_kwargs.kwargs.get("lot") or call_kwargs.args[2]
        assert actual_lot == MICRO_MAX_LOT

    @pytest.mark.asyncio
    async def test_live_mode_full_execution(self):
        """Live mode should execute at full lot size."""
        from mcp_server.guardrails import TradingGuardrails
        from mcp_server.tools import broker

        mock_connector = AsyncMock()
        mock_connector.get_account.return_value = {"success": True, "data": {"balance": 10000, "profit": 0}}
        mock_connector.get_positions.return_value = {"success": True, "data": []}
        mock_connector.get_tick.return_value = {"success": True, "data": {"ask": 2450, "bid": 2449}}
        mock_connector.place_order.return_value = {"success": True, "data": {"ticket": 12345, "lot": 0.5}}

        mock_guardrails = AsyncMock(spec=TradingGuardrails)
        mock_guardrails.validate_order = AsyncMock(return_value=GuardrailResult(True))
        mock_guardrails.get_rollout_mode.return_value = "live"
        mock_guardrails.check_rollout_mode.return_value = GuardrailResult(True)
        mock_guardrails.record_trade = AsyncMock()

        broker._connector = mock_connector
        broker._guardrails = mock_guardrails

        result = await broker.place_order("GOLD", "BUY", 0.5, 2440, 2470)

        assert result["executed"] is True
        assert result["mode"] == "live"


# ─── Rollout API Integration ────────────────────────────────────────────────


class TestRolloutAPI:
    @pytest.fixture
    def app_and_client(self, db_session, redis_client):
        from unittest.mock import MagicMock

        from fastapi import FastAPI

        from app.api.routes import rollout
        from app.db.session import get_db

        app = FastAPI()
        app.include_router(rollout.router)

        # Mock runner_manager with redis
        manager = MagicMock()
        manager.redis = redis_client
        app.state.runner_manager = manager

        async def override_db():
            yield db_session

        app.dependency_overrides[get_db] = override_db
        return app

    @pytest.mark.asyncio
    async def test_get_rollout_mode(self, app_and_client):
        from httpx import ASGITransport, AsyncClient

        transport = ASGITransport(app=app_and_client)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/rollout/mode")
        assert resp.status_code == 200
        assert "mode" in resp.json()
        assert "available_modes" in resp.json()

    @pytest.mark.asyncio
    async def test_set_rollout_mode(self, app_and_client):
        from httpx import ASGITransport, AsyncClient

        transport = ASGITransport(app=app_and_client)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.put("/api/rollout/mode", json={"mode": "paper"})
        assert resp.status_code == 200
        assert resp.json()["mode"] == "paper"

    @pytest.mark.asyncio
    async def test_set_invalid_mode(self, app_and_client):
        from httpx import ASGITransport, AsyncClient

        transport = ASGITransport(app=app_and_client)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.put("/api/rollout/mode", json={"mode": "invalid"})
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_get_readiness(self, app_and_client):
        from httpx import ASGITransport, AsyncClient

        transport = ASGITransport(app=app_and_client)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/rollout/readiness")
        assert resp.status_code == 200
        data = resp.json()
        assert "ready" in data
        assert "checks" in data
        assert any(c["name"] == "database" for c in data["checks"])
        assert any(c["name"] == "redis" for c in data["checks"])
        assert any(c["name"] == "rollout_mode" for c in data["checks"])
