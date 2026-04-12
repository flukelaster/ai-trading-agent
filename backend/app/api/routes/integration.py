"""Integration Status API — test connectivity to all external services."""

import time

import httpx
from fastapi import APIRouter, Request  # Request kept for route signatures
from loguru import logger

from app.config import settings

router = APIRouter(prefix="/api/integration", tags=["integration"])


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


def _mask(value: str, show: int = 6) -> str:
    if not value:
        return ""
    if len(value) <= show:
        return "***"
    return value[:show] + "***" + value[-4:]


@router.get("/config")
async def get_integration_config():
    """Get all integration configs (masked sensitive values)."""
    telegram_token = getattr(settings, "telegram_bot_token", "")

    return {
        "integrations": [
            {
                "id": "anthropic",
                "name": "Anthropic API",
                "description": "Claude AI for market analysis and autonomous trading decisions",
                "logo": "anthropic",
                "status": "configured" if settings.anthropic_api_key else "not_configured",
                "tools_count": 36,
                "config": {
                    "api_key": _mask(settings.anthropic_api_key),
                    "model_orchestrator": "claude-sonnet-4-20250514",
                    "model_specialist": "claude-haiku-4-5-20251001",
                },
            },
            {
                "id": "mt5",
                "name": "MT5 Bridge",
                "description": "MetaTrader 5 bridge for GOLD, OILCash, USDJPY order execution",
                "logo": "mt5",
                "status": "configured" if settings.mt5_bridge_url else "not_configured",
                "tools_count": 8,
                "config": {
                    "bridge_url": settings.mt5_bridge_url,
                    "api_key": _mask(getattr(settings, "mt5_bridge_api_key", "")),
                },
            },
            {
                "id": "binance",
                "name": "Binance",
                "description": "Cryptocurrency exchange for BTCUSD trading",
                "logo": "binance",
                "status": "configured" if getattr(settings, "binance_base_url", "") else "not_configured",
                "tools_count": 3,
                "config": {
                    "base_url": getattr(settings, "binance_base_url", ""),
                    "api_key": _mask(getattr(settings, "binance_api_key", "")),
                    "symbols": getattr(settings, "binance_symbols", ""),
                },
            },
            {
                "id": "telegram",
                "name": "Telegram",
                "description": "Send trade alerts and notifications to Telegram",
                "logo": "telegram",
                "status": "configured" if telegram_token else "not_configured",
                "tools_count": 1,
                "config": {
                    "bot_token": _mask(telegram_token),
                    "chat_id": getattr(settings, "telegram_chat_id", ""),
                },
            },
        ]
    }
