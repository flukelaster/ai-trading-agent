"""
Integration tests for History API routes.
"""

from datetime import datetime

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.db.models import Trade
from app.db.session import get_db


def _make_test_app(db_session):
    from fastapi import FastAPI

    from app.api.routes.history import router

    app = FastAPI()
    app.include_router(router)

    async def override_db():
        yield db_session

    app.dependency_overrides[get_db] = override_db
    return app


@pytest_asyncio.fixture
async def client(db_session):
    app = _make_test_app(db_session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def seeded_db(db_session):
    """Insert sample trades for testing."""
    trades = [
        Trade(
            ticket=1001,
            symbol="GOLD",
            type="BUY",
            lot=0.1,
            open_price=2000.0,
            close_price=2010.0,
            sl=1990.0,
            tp=2020.0,
            open_time=datetime(2025, 1, 1, 10, 0),
            close_time=datetime(2025, 1, 1, 12, 0),
            profit=100.0,
            strategy_name="ema_crossover",
        ),
        Trade(
            ticket=1002,
            symbol="GOLD",
            type="SELL",
            lot=0.1,
            open_price=2010.0,
            close_price=2020.0,
            sl=2020.0,
            tp=2000.0,
            open_time=datetime(2025, 1, 2, 10, 0),
            close_time=datetime(2025, 1, 2, 12, 0),
            profit=-100.0,
            strategy_name="ema_crossover",
        ),
    ]
    for t in trades:
        db_session.add(t)
    await db_session.commit()
    return trades


class TestHistoryRoutes:
    async def test_get_trades(self, client, seeded_db):
        resp = await client.get("/api/history/trades?days=365")
        assert resp.status_code == 200
        data = resp.json()
        assert "trades" in data

    async def test_get_trades_empty(self, client):
        resp = await client.get("/api/history/trades?days=1")
        assert resp.status_code == 200

    async def test_get_daily_pnl(self, client, seeded_db):
        resp = await client.get("/api/history/daily-pnl?days=365")
        assert resp.status_code == 200

    async def test_get_performance(self, client, seeded_db):
        resp = await client.get("/api/history/performance?days=365")
        assert resp.status_code == 200
