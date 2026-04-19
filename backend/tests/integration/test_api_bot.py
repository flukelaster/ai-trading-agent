"""
Integration tests for Bot API routes.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.api.routes.bot import set_manager


def _make_test_app():
    """Create a minimal FastAPI app for testing."""
    from fastapi import FastAPI

    from app.api.routes.bot import router
    from app.db.session import get_db

    app = FastAPI()
    app.include_router(router)

    async def _fake_db():
        db = AsyncMock()
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.rollback = AsyncMock()
        yield db

    app.dependency_overrides[get_db] = _fake_db
    return app


@pytest.fixture
def mock_engine():
    engine = MagicMock()
    engine.state = MagicMock()
    engine.state.value = "STOPPED"
    engine.strategy = MagicMock()
    engine.strategy.name = "ema_crossover"
    engine.strategy.get_params.return_value = {"fast_period": 20, "slow_period": 50}
    engine.symbol = "GOLD"
    engine.timeframe = "M15"
    engine.started_at = None
    engine.paper_trade = False
    engine._paper_positions = []
    engine._paper_balance = 10000.0
    engine.risk_manager = MagicMock()
    engine.risk_manager.use_ai_filter = True
    engine.risk_manager.max_risk_per_trade = 0.01
    engine.risk_manager.max_daily_loss = 0.03
    engine.risk_manager.max_concurrent_trades = 3
    engine.risk_manager.max_lot = 1.0
    engine.sentiment_analyzer = None
    engine.redis = AsyncMock()
    engine.connector = AsyncMock()
    engine.connector.get_account.return_value = {
        "success": True,
        "data": {"balance": 10000, "equity": 10000, "margin": 0, "free_margin": 10000, "profit": 0, "currency": "USD"},
    }
    engine.start = AsyncMock()
    engine.stop = AsyncMock()
    engine.emergency_stop = AsyncMock(return_value={"success": True})
    engine.update_strategy = AsyncMock()
    engine.update_settings = AsyncMock()
    engine.get_status = MagicMock(
        return_value={
            "state": "STOPPED",
            "strategy": "ema_crossover",
            "strategy_params": {"fast_period": 20, "slow_period": 50},
            "symbol": "GOLD",
            "timeframe": "M15",
            "started_at": None,
            "use_ai_filter": True,
            "paper_trade": False,
            "max_risk_per_trade": 0.01,
            "max_daily_loss": 0.03,
            "max_concurrent_trades": 3,
            "max_lot": 1.0,
        }
    )
    return engine


@pytest.fixture
def mock_manager(mock_engine):
    manager = MagicMock()
    manager.engines = {"GOLD": mock_engine}
    manager.get_engine.return_value = mock_engine
    manager.start = AsyncMock()
    manager.stop = AsyncMock()
    manager.emergency_stop = AsyncMock(return_value={"success": True})
    manager.get_status = MagicMock(
        return_value={
            "GOLD": mock_engine.get_status(),
        }
    )
    return manager


@pytest_asyncio.fixture
async def client(mock_manager):
    set_manager(mock_manager)
    app = _make_test_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    set_manager(None)


class TestBotRoutes:
    async def test_start_bot(self, client, mock_manager):
        resp = await client.post("/api/bot/start")
        assert resp.status_code == 200
        assert resp.json()["status"] == "started"
        mock_manager.start.assert_called_once()

    async def test_stop_bot(self, client, mock_manager):
        resp = await client.post("/api/bot/stop")
        assert resp.status_code == 200
        assert resp.json()["status"] == "stopped"

    async def test_emergency_stop(self, client, mock_manager):
        resp = await client.post("/api/bot/emergency-stop")
        assert resp.status_code == 200
        assert resp.json()["status"] == "emergency_stopped"

    async def test_get_status(self, client):
        resp = await client.get("/api/bot/status")
        assert resp.status_code == 200

    async def test_get_status_by_symbol(self, client):
        resp = await client.get("/api/bot/status?symbol=GOLD")
        assert resp.status_code == 200
        data = resp.json()
        assert data["symbol"] == "GOLD"

    async def test_update_strategy(self, client, mock_engine):
        resp = await client.put(
            "/api/bot/strategy",
            json={
                "name": "breakout",
                "symbol": "GOLD",
            },
        )
        assert resp.status_code == 200
        mock_engine.update_strategy.assert_called_once()

    async def test_update_settings(self, client, mock_engine):
        resp = await client.put(
            "/api/bot/settings",
            json={
                "symbol": "GOLD",
                "max_risk_per_trade": 0.02,
                "ai_confidence_threshold": 0.8,
            },
        )
        assert resp.status_code == 200
        mock_engine.update_settings.assert_called_once()

    async def test_settings_validation_rejects_invalid(self, client):
        resp = await client.put(
            "/api/bot/settings",
            json={
                "max_risk_per_trade": 0.5,  # > 0.10 → invalid
            },
        )
        assert resp.status_code == 422

    async def test_settings_validation_rejects_negative(self, client):
        resp = await client.put(
            "/api/bot/settings",
            json={
                "ai_confidence_threshold": -0.1,  # < 0 → invalid
            },
        )
        assert resp.status_code == 422


class TestBotNotInitialized:
    async def test_503_when_no_manager(self):
        set_manager(None)
        app = _make_test_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/bot/start")
            assert resp.status_code == 503
