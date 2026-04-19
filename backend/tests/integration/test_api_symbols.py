"""Integration tests for Symbol Config API."""

from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.routes import symbols as symbols_routes
from app.db.models import SymbolConfig
from app.db.session import get_db


def _sample_create() -> dict:
    return {
        "symbol": "EURUSD",
        "display_name": "Euro/Dollar",
        "broker_alias": "EURUSDm",
        "default_timeframe": "M15",
        "pip_value": 10.0,
        "default_lot": 0.1,
        "max_lot": 2.0,
        "price_decimals": 5,
        "sl_atr_mult": 1.5,
        "tp_atr_mult": 2.0,
        "contract_size": 100000,
        "ml_tp_pips": 0.001,
        "ml_sl_pips": 0.001,
        "ml_forward_bars": 10,
        "ml_timeframe": "M15",
    }


def _build_app(db_session, connector=None, redis_client=None) -> FastAPI:
    app = FastAPI()
    app.include_router(symbols_routes.router)

    async def override_db():
        yield db_session

    app.dependency_overrides[get_db] = override_db
    app.state.connector = connector
    app.state.redis = redis_client
    return app


@pytest_asyncio.fixture
async def client(db_session, redis_client):
    connector = AsyncMock()
    connector.get_symbol_spec.return_value = {
        "success": True,
        "data": {
            "symbol": "EURUSDm",
            "digits": 5,
            "point": 0.00001,
            "volume_min": 0.01,
            "volume_max": 100.0,
            "volume_step": 0.01,
            "trade_contract_size": 100000.0,
            "trade_tick_size": 0.00001,
            "trade_tick_value": 1.0,
            "visible": True,
        },
    }
    app = _build_app(db_session, connector=connector, redis_client=redis_client)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestCRUD:
    @pytest.mark.asyncio
    async def test_list_empty(self, client):
        resp = await client.get("/api/symbols")
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_create_then_list(self, client):
        resp = await client.post("/api/symbols", json=_sample_create())
        assert resp.status_code == 200
        data = resp.json()
        assert data["symbol"] == "EURUSD"
        assert data["is_enabled"] is False
        assert data["ml_status"] == "pending"

        resp = await client.get("/api/symbols")
        assert len(resp.json()) == 1

    @pytest.mark.asyncio
    async def test_duplicate_create_conflicts(self, client):
        payload = _sample_create()
        await client.post("/api/symbols", json=payload)
        resp = await client.post("/api/symbols", json=payload)
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_update(self, client):
        await client.post("/api/symbols", json=_sample_create())
        updated = _sample_create()
        del updated["symbol"]
        updated["display_name"] = "Euro Updated"
        updated["max_lot"] = 5.0
        resp = await client.put("/api/symbols/EURUSD", json=updated)
        assert resp.status_code == 200
        assert resp.json()["display_name"] == "Euro Updated"
        assert resp.json()["max_lot"] == 5.0

    @pytest.mark.asyncio
    async def test_toggle(self, client):
        await client.post("/api/symbols", json=_sample_create())
        resp = await client.post("/api/symbols/EURUSD/toggle")
        assert resp.status_code == 200
        assert resp.json()["is_enabled"] is True
        resp = await client.post("/api/symbols/EURUSD/toggle")
        assert resp.json()["is_enabled"] is False

    @pytest.mark.asyncio
    async def test_soft_delete(self, client):
        await client.post("/api/symbols", json=_sample_create())
        resp = await client.delete("/api/symbols/EURUSD")
        assert resp.status_code == 200
        resp = await client.get("/api/symbols/EURUSD")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_recreate_after_delete_revives_row(self, client):
        # create → delete → create again with different values should succeed
        # (DB has unique constraint on `symbol`, so raw INSERT would fail)
        await client.post("/api/symbols", json=_sample_create())
        await client.delete("/api/symbols/EURUSD")

        revived = _sample_create()
        revived["display_name"] = "Revived EUR"
        revived["max_lot"] = 7.5
        resp = await client.post("/api/symbols", json=revived)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["symbol"] == "EURUSD"
        assert body["display_name"] == "Revived EUR"
        assert body["max_lot"] == 7.5
        assert body["ml_status"] == "pending"

        # visible again in list
        resp = await client.get("/api/symbols")
        assert any(c["symbol"] == "EURUSD" for c in resp.json())

    @pytest.mark.asyncio
    async def test_get_not_found(self, client):
        resp = await client.get("/api/symbols/UNKNOWN")
        assert resp.status_code == 404


class TestValidation:
    @pytest.mark.asyncio
    async def test_rejects_bad_timeframe(self, client):
        payload = _sample_create()
        payload["default_timeframe"] = "W1"
        resp = await client.post("/api/symbols", json=payload)
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_rejects_negative_lot(self, client):
        payload = _sample_create()
        payload["default_lot"] = -0.1
        resp = await client.post("/api/symbols", json=payload)
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_rejects_default_greater_than_max(self, client):
        payload = _sample_create()
        payload["default_lot"] = 10.0
        payload["max_lot"] = 1.0
        resp = await client.post("/api/symbols", json=payload)
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_rejects_bad_symbol_name(self, client):
        payload = _sample_create()
        payload["symbol"] = "EUR USD!"
        resp = await client.post("/api/symbols", json=payload)
        assert resp.status_code == 422


class TestRetrain:
    @pytest.mark.asyncio
    async def test_retrain_requires_manager(self, client):
        await client.post("/api/symbols", json=_sample_create())
        resp = await client.post("/api/symbols/EURUSD/retrain")
        assert resp.status_code == 503

    @pytest.mark.asyncio
    async def test_retrain_queues_task_and_sets_training(self, db_session, redis_client):
        from unittest.mock import AsyncMock, MagicMock
        connector = AsyncMock()

        retrain_started = False

        async def fake_retrain(symbol, engine):
            nonlocal retrain_started
            retrain_started = True

        scheduler = MagicMock()
        scheduler._ml_retrain_symbol = fake_retrain
        manager = MagicMock()
        engine_mock = MagicMock()
        manager.get_engine.return_value = engine_mock

        app = _build_app(db_session, connector=connector, redis_client=redis_client)
        app.state.scheduler = scheduler
        app.state.manager = manager
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            await c.post("/api/symbols", json=_sample_create())
            resp = await c.post("/api/symbols/EURUSD/retrain")
            assert resp.status_code == 200
            assert resp.json()["status"] == "training"

            resp2 = await c.get("/api/symbols/EURUSD")
            assert resp2.json()["ml_status"] == "training"

            # Retrain already running: second call should 409
            resp3 = await c.post("/api/symbols/EURUSD/retrain")
            assert resp3.status_code == 409

        # Give the background task a moment to run
        import asyncio
        await asyncio.sleep(0.05)
        assert retrain_started is True


class TestValidateBroker:
    @pytest.mark.asyncio
    async def test_validate_calls_mt5(self, client):
        await client.post("/api/symbols", json=_sample_create())
        resp = await client.post("/api/symbols/EURUSD/validate")
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["spec"]["digits"] == 5


class TestHotReload:
    @pytest.mark.asyncio
    async def test_toggle_publishes_redis_event(self, client, redis_client):
        from app.services.symbol_config_service import RELOAD_CHANNEL

        pubsub = redis_client.pubsub()
        await pubsub.subscribe(RELOAD_CHANNEL)
        # consume the subscribe confirmation
        await pubsub.get_message(timeout=0.1)

        await client.post("/api/symbols", json=_sample_create())

        # Drain any pending messages and confirm at least one reload event emitted
        seen = []
        for _ in range(5):
            msg = await pubsub.get_message(timeout=0.2)
            if msg and msg.get("type") == "message":
                seen.append(msg)
        assert seen, "expected a reload event on Redis channel"
        await pubsub.unsubscribe(RELOAD_CHANNEL)
        await pubsub.aclose()


class TestFallback:
    @pytest.mark.asyncio
    async def test_db_empty_uses_static_profiles(self, db_session):
        from app.config import SYMBOL_PROFILES, apply_db_symbol_profiles
        from app.services.symbol_config_service import load_profiles_from_db

        profiles = await load_profiles_from_db(db_session)
        assert profiles == {}
        # Static fallback retained
        assert "GOLD" in SYMBOL_PROFILES
        apply_db_symbol_profiles({})
        assert "GOLD" in SYMBOL_PROFILES


class TestProfileMerge:
    @pytest.mark.asyncio
    async def test_db_profile_overrides_static(self, db_session):
        from app.config import SYMBOL_PROFILES, apply_db_symbol_profiles
        from app.services.symbol_config_service import load_profiles_from_db

        cfg = SymbolConfig(
            symbol="GOLD",
            display_name="Gold Override",
            broker_alias="GOLDx",
            is_enabled=True,
            default_timeframe="M15",
            pip_value=1.0,
            default_lot=0.05,
            max_lot=0.5,
            price_decimals=2,
            sl_atr_mult=1.5,
            tp_atr_mult=2.0,
            contract_size=100,
            ml_tp_pips=10.0,
            ml_sl_pips=10.0,
            ml_forward_bars=10,
            ml_timeframe="M15",
        )
        db_session.add(cfg)
        await db_session.commit()

        db_profiles = await load_profiles_from_db(db_session)
        apply_db_symbol_profiles(db_profiles)
        assert SYMBOL_PROFILES["GOLD"]["display_name"] == "Gold Override"
        assert SYMBOL_PROFILES["GOLD"]["default_lot"] == 0.05
        assert SYMBOL_PROFILES["GOLDx"]["canonical"] == "GOLD"

        # Restore static profiles so later tests are not polluted
        apply_db_symbol_profiles({})


def _bridge_symbols_payload() -> dict:
    return {
        "success": True,
        "data": {
            "count": 4,
            "items": [
                {
                    "symbol": "EURUSD#",
                    "path": "Forex\\Majors\\EURUSD",
                    "description": "Euro vs US Dollar",
                    "digits": 5,
                    "point": 0.00001,
                    "volume_min": 0.01,
                    "volume_max": 100.0,
                    "volume_step": 0.01,
                    "trade_contract_size": 100000.0,
                    "trade_tick_size": 0.00001,
                    "trade_tick_value": 1.0,
                    "currency_base": "EUR",
                    "currency_profit": "USD",
                },
                {
                    "symbol": "USDJPY#",
                    "path": "Forex\\Majors\\USDJPY",
                    "description": "US Dollar vs Japanese Yen",
                    "digits": 3,
                    "point": 0.001,
                    "volume_min": 0.01,
                    "volume_max": 100.0,
                    "volume_step": 0.01,
                    "trade_contract_size": 100000.0,
                    "trade_tick_size": 0.001,
                    "trade_tick_value": 0.67,
                    "currency_base": "USD",
                    "currency_profit": "JPY",
                },
                {
                    "symbol": "ENJUSD#",
                    "path": "Crypto\\ENJUSD",
                    "description": "Enjin Coin",
                    "digits": 5,
                    "point": 0.00001,
                    "volume_min": 1.0,
                    "volume_max": 1000.0,
                    "volume_step": 0.1,
                    "trade_contract_size": 1.0,
                    "trade_tick_size": 0.00001,
                    "trade_tick_value": 0.00001,
                    "currency_base": "ENJ",
                    "currency_profit": "USD",
                },
                {
                    "symbol": "XAUUSD",
                    "path": "CFD Metals\\XAUUSD",
                    "description": "Gold vs US Dollar",
                    "digits": 2,
                    "point": 0.01,
                    "volume_min": 0.01,
                    "volume_max": 50.0,
                    "volume_step": 0.01,
                    "trade_contract_size": 100.0,
                    "trade_tick_size": 0.01,
                    "trade_tick_value": 1.0,
                    "currency_base": "XAU",
                    "currency_profit": "USD",
                },
            ],
        },
    }


class TestBrokerCatalog:
    @pytest_asyncio.fixture
    async def catalog_client(self, db_session, redis_client):
        connector = AsyncMock()
        connector.list_symbols.return_value = _bridge_symbols_payload()
        app = _build_app(db_session, connector=connector, redis_client=redis_client)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c, connector

    @pytest.mark.asyncio
    async def test_returns_mapped_catalog(self, catalog_client):
        client, _ = catalog_client
        resp = await client.get("/api/symbols/broker-catalog")
        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 4
        items = {it["symbol"]: it for it in body["items"]}

        eur = items["EURUSD#"]
        assert eur["asset_class"] == "forex"
        assert eur["price_decimals"] == 5
        assert eur["pip_value"] == pytest.approx(0.0001)  # 5-digit: point*10
        assert eur["contract_size"] == 100000.0
        assert eur["volume_min"] == 0.01

        jpy = items["USDJPY#"]
        assert jpy["pip_value"] == pytest.approx(0.01)  # 3-digit: point*10

        enj = items["ENJUSD#"]
        assert enj["asset_class"] == "crypto"
        assert enj["pip_value"] == pytest.approx(0.0001)

        gold = items["XAUUSD"]
        assert gold["asset_class"] == "metal"
        assert gold["price_decimals"] == 2
        assert gold["pip_value"] == pytest.approx(0.01)  # 2-digit: pip = point

    @pytest.mark.asyncio
    async def test_second_call_hits_redis_cache(self, catalog_client):
        client, connector = catalog_client
        r1 = await client.get("/api/symbols/broker-catalog")
        r2 = await client.get("/api/symbols/broker-catalog")
        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r1.json()["items"] == r2.json()["items"]
        # Bridge called only once — second response served from Redis cache
        assert connector.list_symbols.call_count == 1

    @pytest.mark.asyncio
    async def test_bridge_failure_returns_502(self, db_session, redis_client):
        connector = AsyncMock()
        connector.list_symbols.return_value = {
            "success": False,
            "data": None,
            "error": "MT5 not connected",
        }
        app = _build_app(db_session, connector=connector, redis_client=redis_client)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get("/api/symbols/broker-catalog")
            assert resp.status_code == 502

    @pytest.mark.asyncio
    async def test_connector_missing_returns_503(self, db_session, redis_client):
        app = _build_app(db_session, connector=None, redis_client=redis_client)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get("/api/symbols/broker-catalog")
            assert resp.status_code == 503
