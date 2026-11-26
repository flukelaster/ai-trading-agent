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

    async def test_walk_forward_endpoint(self, client, mock_market_data, make_ohlcv_df):
        # Regression: endpoint crashed with AttributeError (OptimizationResult.results)
        mock_market_data.get_ohlcv.return_value = make_ohlcv_df(rows=1200, trend="up")
        resp = await client.post(
            "/api/backtest/walk-forward",
            json={
                "strategy": "ema_crossover",
                "symbol": "GOLD",
                "source": "mt5",
                "count": 1200,
                "n_splits": 3,
                "param_grid": {"fast_period": [5, 10], "slow_period": [20, 30]},
            },
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["n_splits"] == 3
        assert "windows" in data

    @pytest.mark.parametrize(
        "path,body",
        [
            ("/api/backtest/optimize", {"param_grid": {"fast_period": [5, 10], "slow_period": [20]}, "min_trades": 1}),
            ("/api/backtest/monte-carlo", {"n_simulations": 100}),
            ("/api/backtest/compare", {"strategies": [{"name": "ema_crossover"}, {"name": "breakout"}]}),
            ("/api/backtest/permutation-test", {"n_permutations": 50}),
            ("/api/backtest/overfitting-score", {}),
        ],
    )
    async def test_analysis_endpoints_return_json(self, client, mock_market_data, make_ohlcv_df, path, body):
        # Smoke test: every analysis endpoint must return 200 with JSON-native types
        mock_market_data.get_ohlcv.return_value = make_ohlcv_df(rows=1200, trend="up")
        resp = await client.post(path, json={"strategy": "ema_crossover", "source": "mt5", "count": 1200, **body})
        assert resp.status_code == 200, resp.text
        assert "error" not in resp.json(), resp.json()

    async def test_overfitting_score_includes_walk_forward(self, client, mock_market_data, make_ohlcv_df):
        # Regression: walk-forward crashed inside this endpoint and was silently
        # skipped, dropping its 40% weight from the composite score.
        mock_market_data.get_ohlcv.return_value = make_ohlcv_df(rows=1200, trend="up")
        resp = await client.post(
            "/api/backtest/overfitting-score",
            json={"strategy": "ema_crossover", "source": "mt5", "count": 1200},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "walk_forward" not in data["skipped_tests"], data
        assert data["walk_forward"] is not None
