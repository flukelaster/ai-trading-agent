"""Integration Status API — test connectivity, config management via Vault."""

import time

import httpx
from fastapi import APIRouter, Depends, Request
from loguru import logger
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.session import get_db

router = APIRouter(prefix="/api/integration", tags=["integration"])


# ─── Config helpers (Vault-first, env fallback) ─────────────────────────────

async def _get_vault_value(db: AsyncSession, key: str) -> str | None:
    """Read a value from Secrets Vault."""
    try:
        from sqlalchemy import select
        from app.db.models import Secret
        from app.vault import vault
        result = await db.execute(select(Secret).where(Secret.key == key, Secret.is_deleted == False))  # noqa
        secret = result.scalar_one_or_none()
        if secret and vault and vault._derived_key:
            return vault.decrypt(secret.encrypted_value, secret.nonce)
    except Exception:
        pass
    return None


async def _set_vault_value(db: AsyncSession, key: str, value: str, category: str = "integration") -> None:
    """Save a value to Secrets Vault (encrypted)."""
    try:
        from sqlalchemy import select
        from app.db.models import Secret
        from app.vault import vault
        if not vault or not vault._derived_key:
            return

        encrypted, nonce = vault.encrypt(value)
        result = await db.execute(select(Secret).where(Secret.key == key))
        existing = result.scalar_one_or_none()
        if existing:
            existing.encrypted_value = encrypted
            existing.nonce = nonce
            existing.is_deleted = False
            from datetime import datetime
            existing.updated_at = datetime.utcnow()
            existing.last_rotated_at = datetime.utcnow()
        else:
            secret = Secret(key=key, encrypted_value=encrypted, nonce=nonce, category=category)
            db.add(secret)
        await db.commit()
    except Exception as e:
        logger.warning(f"Failed to save to vault: {e}")
        await db.rollback()


async def _get_config_value(db: AsyncSession, vault_key: str, env_fallback: str) -> str:
    """Get config: Vault first, then env var fallback."""
    val = await _get_vault_value(db, vault_key)
    return val if val else env_fallback


async def _test_anthropic() -> dict:
    """Test Anthropic API connectivity."""
    start = time.time()
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://api.anthropic.com/v1/models",
                headers={"x-api-key": settings.anthropic_api_key, "anthropic-version": "2023-06-01"},
            )
        latency = int((time.time() - start) * 1000)
        if resp.status_code == 200:
            return {"name": "Anthropic API", "status": "connected", "latency_ms": latency, "detail": "Claude AI ready"}
        return {"name": "Anthropic API", "status": "error", "latency_ms": latency, "detail": f"HTTP {resp.status_code}"}
    except Exception as e:
        return {"name": "Anthropic API", "status": "error", "latency_ms": 0, "detail": str(e)}


async def _test_mt5() -> dict:
    """Test MT5 Bridge connectivity."""
    start = time.time()
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(
                f"{settings.mt5_bridge_url}/health",
                headers={"X-Bridge-Key": settings.mt5_bridge_api_key},
            )
        latency = int((time.time() - start) * 1000)
        if resp.status_code == 200:
            return {"name": "MT5 Bridge", "status": "connected", "latency_ms": latency, "detail": f"VPS: {settings.mt5_bridge_url}"}
        return {"name": "MT5 Bridge", "status": "error", "latency_ms": latency, "detail": f"HTTP {resp.status_code}"}
    except Exception as e:
        return {"name": "MT5 Bridge", "status": "error", "latency_ms": 0, "detail": str(e)}


async def _test_binance() -> dict:
    """Test Binance API connectivity."""
    start = time.time()
    try:
        base_url = settings.binance_base_url if hasattr(settings, "binance_base_url") else ""
        if not base_url:
            return {"name": "Binance", "status": "disabled", "latency_ms": 0, "detail": "Not configured"}
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{base_url}/api/v3/ping")
        latency = int((time.time() - start) * 1000)
        if resp.status_code == 200:
            label = "Testnet" if "testnet" in base_url else "Production"
            return {"name": "Binance", "status": "connected", "latency_ms": latency, "detail": f"{label}: {base_url}"}
        return {"name": "Binance", "status": "error", "latency_ms": latency, "detail": f"HTTP {resp.status_code}"}
    except Exception as e:
        return {"name": "Binance", "status": "error", "latency_ms": 0, "detail": str(e)}


async def _test_telegram() -> dict:
    """Test Telegram bot connectivity."""
    start = time.time()
    token = getattr(settings, "telegram_bot_token", "")
    if not token:
        return {"name": "Telegram", "status": "not_configured", "latency_ms": 0, "detail": "No bot token configured"}
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"https://api.telegram.org/bot{token}/getMe")
        latency = int((time.time() - start) * 1000)
        if resp.status_code == 200:
            data = resp.json()
            bot_name = data.get("result", {}).get("username", "unknown")
            return {"name": "Telegram", "status": "connected", "latency_ms": latency, "detail": f"Bot: @{bot_name}"}
        return {"name": "Telegram", "status": "error", "latency_ms": latency, "detail": f"HTTP {resp.status_code}"}
    except Exception as e:
        return {"name": "Telegram", "status": "error", "latency_ms": 0, "detail": str(e)}


@router.get("/status")
async def get_integration_status(request: Request):
    """Test all integrations and return status."""
    import asyncio
    results = await asyncio.gather(
        _test_anthropic(),
        _test_mt5(),
        _test_binance(),
        _test_telegram(),
    )
    return {"services": list(results)}


@router.get("/test/{service}")
async def test_service(service: str, request: Request):
    """Test a single service."""
    testers = {
        "anthropic": _test_anthropic,
        "mt5": _test_mt5,
        "binance": _test_binance,
        "telegram": _test_telegram,
    }
    tester = testers.get(service)
    if not tester:
        return {"name": service, "status": "error", "detail": f"Unknown service: {service}"}
    return await tester()


class SaveConfigRequest(BaseModel):
    integration_id: str
    config: dict[str, str]


# Mapping: integration config field → Vault key
_CONFIG_VAULT_KEYS: dict[str, dict[str, str]] = {
    "anthropic": {"API Key": "ANTHROPIC_API_KEY"},
    "mt5": {"Bridge URL": "MT5_BRIDGE_URL", "API Key": "MT5_BRIDGE_API_KEY"},
    "binance": {"Base URL": "BINANCE_BASE_URL", "API Key": "BINANCE_API_KEY", "Symbols": "BINANCE_SYMBOLS"},
    "telegram": {"Bot Token": "TELEGRAM_BOT_TOKEN", "Chat ID": "TELEGRAM_CHAT_ID"},
}


@router.put("/config")
async def save_integration_config(req: SaveConfigRequest, db: AsyncSession = Depends(get_db)):
    """Save integration config to Secrets Vault (encrypted)."""
    vault_keys = _CONFIG_VAULT_KEYS.get(req.integration_id, {})
    saved = []
    for field_name, value in req.config.items():
        if not value or not value.strip():
            continue
        vault_key = vault_keys.get(field_name)
        if vault_key:
            await _set_vault_value(db, vault_key, value.strip(), category="integration")
            saved.append(field_name)
    return {"saved": saved, "integration_id": req.integration_id}


def _mask(value: str, show: int = 6) -> str:
    if not value:
        return ""
    if len(value) <= show:
        return "***"
    return value[:show] + "***" + value[-4:]


@router.get("/config")
async def get_integration_config(db: AsyncSession = Depends(get_db)):
    """Get all integration configs (masked, Vault-first then env fallback)."""
    # Read from Vault first, fallback to env
    anthropic_key = await _get_config_value(db, "ANTHROPIC_API_KEY", settings.anthropic_api_key)
    mt5_url = await _get_config_value(db, "MT5_BRIDGE_URL", settings.mt5_bridge_url)
    mt5_key = await _get_config_value(db, "MT5_BRIDGE_API_KEY", getattr(settings, "mt5_bridge_api_key", ""))
    binance_url = await _get_config_value(db, "BINANCE_BASE_URL", getattr(settings, "binance_base_url", ""))
    binance_key = await _get_config_value(db, "BINANCE_API_KEY", getattr(settings, "binance_api_key", ""))
    binance_symbols = await _get_config_value(db, "BINANCE_SYMBOLS", getattr(settings, "binance_symbols", ""))
    telegram_token = await _get_config_value(db, "TELEGRAM_BOT_TOKEN", getattr(settings, "telegram_bot_token", ""))
    telegram_chat = await _get_config_value(db, "TELEGRAM_CHAT_ID", getattr(settings, "telegram_chat_id", ""))

    return {
        "integrations": [
            {
                "id": "anthropic",
                "name": "Anthropic API",
                "description": "Claude AI for market analysis and autonomous trading decisions",
                "status": "configured" if anthropic_key else "not_configured",
                "config": {
                    "API Key": _mask(anthropic_key),
                    "Orchestrator Model": "claude-sonnet-4-20250514",
                    "Specialist Model": "claude-haiku-4-5-20251001",
                },
                "tools": [
                    {"name": "run_full_analysis", "description": "Comprehensive technical analysis (EMA, RSI, ATR, ADX, Bollinger)"},
                    {"name": "get_tick", "description": "Get current bid/ask price"},
                    {"name": "get_ohlcv", "description": "Get OHLCV candlestick data"},
                    {"name": "calculate_ema", "description": "Calculate Exponential Moving Average"},
                    {"name": "calculate_rsi", "description": "Calculate Relative Strength Index"},
                    {"name": "calculate_atr", "description": "Calculate Average True Range"},
                    {"name": "validate_trade", "description": "Check trade against risk rules"},
                    {"name": "calculate_lot_size", "description": "Calculate optimal position size"},
                    {"name": "calculate_sl_tp", "description": "Calculate stop-loss and take-profit"},
                    {"name": "get_sentiment", "description": "Get latest AI sentiment analysis"},
                    {"name": "get_account", "description": "Get account balance and equity"},
                    {"name": "get_exposure", "description": "Get portfolio exposure by symbol"},
                    {"name": "check_correlation", "description": "Check correlation conflicts"},
                    {"name": "get_trade_history", "description": "Get recent trade history"},
                    {"name": "get_performance", "description": "Get performance statistics"},
                    {"name": "detect_regime", "description": "Detect market regime (trending/ranging)"},
                    {"name": "recommend_strategy", "description": "Recommend strategy for current regime"},
                    {"name": "log_decision", "description": "Log trading decision with reasoning"},
                ],
            },
            {
                "id": "mt5",
                "name": "MT5 Bridge",
                "description": "MetaTrader 5 bridge for GOLD, OILCash, USDJPY order execution",
                "status": "configured" if mt5_url else "not_configured",
                "config": {
                    "Bridge URL": mt5_url,
                    "API Key": _mask(mt5_key),
                },
                "tools": [
                    {"name": "place_order", "description": "Place BUY/SELL order (guardrail-gated)"},
                    {"name": "modify_position", "description": "Modify SL/TP of existing position"},
                    {"name": "close_position", "description": "Close a position by ticket"},
                    {"name": "get_positions", "description": "Get all open positions"},
                    {"name": "get_tick", "description": "Get current bid/ask price"},
                    {"name": "get_ohlcv", "description": "Get OHLCV candlestick data"},
                ],
            },
            {
                "id": "binance",
                "name": "Binance",
                "description": "Cryptocurrency exchange for BTCUSD trading",
                "status": "configured" if binance_url else "not_configured",
                "config": {
                    "Base URL": binance_url,
                    "API Key": _mask(binance_key),
                    "Symbols": binance_symbols,
                },
                "tools": [
                    {"name": "place_order", "description": "Place BUY/SELL order on Binance"},
                    {"name": "get_positions", "description": "Get open positions"},
                    {"name": "get_account", "description": "Get Binance account balance"},
                ],
            },
            {
                "id": "telegram",
                "name": "Telegram",
                "description": "Send trade alerts and notifications to Telegram",
                "status": "configured" if telegram_token else "not_configured",
                "config": {
                    "Bot Token": _mask(telegram_token),
                    "Chat ID": telegram_chat,
                },
                "tools": [
                    {"name": "send_notification", "description": "Send trade alert to Telegram channel"},
                ],
            },
        ]
    }
