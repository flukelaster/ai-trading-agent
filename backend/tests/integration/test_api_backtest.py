"""
Integration tests for Backtest API routes.
"""

from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.api.routes.backtest import set_collector, set_market_data


def _make_test_app():
    from fastapi import FastAPI

    from app.api.routes.backtest import router

    app = FastAPI()
    app.include_router(router)
    return app


@pytest.fixture
def mock_market_data(make_ohlcv_df):
    md = AsyncMock()
    md.get_ohlcv.return_value = make_ohlcv_df(rows=500, trend="up")
    return md


@pytest_asyncio.fixture
async def client(mock_market_data):
    set_market_data(mock_market_data)
    set_collector(None)
    app = _make_test_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    set_market_data(None)


class TestBacktestRoutes:
    async def test_run_backtest(self, client):
        resp = await client.post(
            "/api/backtest/run",
            json={
                "strategy": "ema_crossover",
                "symbol": "GOLD",
                "count": 500,
                "initial_balance": 10000.0,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "total_trades" in data or "trades" in data or "final_balance" in data

    async def test_backtest_validation_rejects_low_count(self, client):
        resp = await client.post(
            "/api/backtest/run",
            json={
                "strategy": "ema_crossover",
                "count": 10,  # < 100 → invalid
            },
        )
        assert resp.status_code == 422

    async def test_backtest_validation_rejects_high_risk(self, client):
        resp = await client.post(
            "/api/backtest/run",
            json={
                "strategy": "ema_crossover",
                "risk_per_trade": 0.5,  # > 0.10 → invalid
            },
        )
        assert resp.status_code == 422
