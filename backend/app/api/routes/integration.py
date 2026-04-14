"""Integration Status API — test connectivity, config management via Vault."""

import os
import shutil
import subprocess
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
    """Test Claude AI connectivity via Agent SDK (Max subscription)."""
    import os
    start = time.time()
    token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "")
    if token:
        return {"name": "Claude AI (Max)", "status": "connected", "latency_ms": 0, "detail": "OAuth token configured"}
    return {"name": "Claude AI (Max)", "status": "error", "latency_ms": 0, "detail": "CLAUDE_CODE_OAUTH_TOKEN not set"}


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
        _test_telegram(),
    )
    return {"services": list(results)}


async def _test_economic_calendar() -> dict:
    """Test Forex Factory economic calendar API."""
    start = time.time()
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get("https://nfs.faireconomy.media/ff_calendar_thisweek.json")
        latency = int((time.time() - start) * 1000)
        if resp.status_code == 200:
            events = resp.json()
            count = len(events) if isinstance(events, list) else 0
            return {"name": "Economic Calendar", "status": "connected", "latency_ms": latency, "detail": f"{count} events this week"}
        return {"name": "Economic Calendar", "status": "error", "latency_ms": latency, "detail": f"HTTP {resp.status_code}"}
    except Exception as e:
        return {"name": "Economic Calendar", "status": "error", "latency_ms": 0, "detail": str(e)}


@router.get("/test/{service}")
async def test_service(service: str, request: Request):
    """Test a single service."""
    testers = {
        "anthropic": _test_anthropic,
        "mt5": _test_mt5,
        "telegram": _test_telegram,
        "economic_calendar": _test_economic_calendar,
        "tradingview": lambda: {"name": "TradingView", "status": "configured" if os.environ.get("TRADINGVIEW_WEBHOOK_KEY") else "not_configured", "latency_ms": 0, "detail": "Webhook receiver — no outbound connection to test"},
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
    "anthropic": {"OAuth Token": "CLAUDE_CODE_OAUTH_TOKEN"},
    "mt5": {"Bridge URL": "MT5_BRIDGE_URL", "API Key": "MT5_BRIDGE_API_KEY"},
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
    import os
    claude_token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "")
    mt5_url = await _get_config_value(db, "MT5_BRIDGE_URL", settings.mt5_bridge_url)
    mt5_key = await _get_config_value(db, "MT5_BRIDGE_API_KEY", getattr(settings, "mt5_bridge_api_key", ""))
    telegram_token = await _get_config_value(db, "TELEGRAM_BOT_TOKEN", getattr(settings, "telegram_bot_token", ""))
    telegram_chat = await _get_config_value(db, "TELEGRAM_CHAT_ID", getattr(settings, "telegram_chat_id", ""))

    return {
        "integrations": [
            {
                "id": "anthropic",
                "name": "Claude AI (Max Subscription)",
                "description": "Claude AI for market analysis and autonomous trading decisions",
                "status": "configured" if claude_token else "not_configured",
                "config": {
                    "Auth": "Max Subscription (OAuth)" if claude_token else "Not configured",
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
                "description": "MetaTrader 5 bridge for GOLD, OILCash, BTCUSD, USDJPY order execution",
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
            {
                "id": "economic_calendar",
                "name": "Economic Calendar",
                "description": "Forex Factory economic events — auto-fetched hourly, reduces lot before high-impact events",
                "status": "connected",
                "config": {},
                "tools": [
                    {"name": "get_upcoming_events", "description": "Get upcoming high-impact USD events"},
                    {"name": "is_near_event", "description": "Check if near a high-impact event"},
                ],
            },
            {
                "id": "tradingview",
                "name": "TradingView",
                "description": "Receive webhook alerts from TradingView Pine Script strategies",
                "status": "configured" if os.environ.get("TRADINGVIEW_WEBHOOK_KEY") else "not_configured",
                "config": {
                    "Webhook URL": f"{os.environ.get('FRONTEND_URL', 'https://your-domain')}/api/webhooks/tradingview",
                    "Webhook Key": _mask(os.environ.get("TRADINGVIEW_WEBHOOK_KEY", "")),
                },
                "tools": [
                    {"name": "webhook_receiver", "description": "Receive BUY/SELL signals from TradingView alerts"},
                ],
            },
        ]
    }


@router.get("/diag/claude-cli")
async def diagnose_claude_cli():
    """Diagnose Claude CLI availability and auth — helps debug SDK agent failures."""
    result: dict = {"checks": []}

    # 1. Check claude binary
    claude_path = shutil.which("claude")
    result["checks"].append({
        "name": "claude_binary",
        "ok": claude_path is not None,
        "detail": claude_path or "NOT FOUND in PATH",
    })

    # 2. Check node
    node_path = shutil.which("node")
    result["checks"].append({
        "name": "node_binary",
        "ok": node_path is not None,
        "detail": node_path or "NOT FOUND",
    })

    # 3. Check token env
    token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "")
    has_space = " " in token
    result["checks"].append({
        "name": "oauth_token",
        "ok": bool(token) and not has_space,
        "detail": f"set ({len(token)} chars, has_space={has_space})" if token else "NOT SET",
    })

    # 4. Check current user (must NOT be root)
    uid = os.getuid()
    result["checks"].append({
        "name": "non_root_user",
        "ok": uid != 0,
        "detail": f"uid={uid} user={os.environ.get('USER', 'unknown')}",
    })

    # 5. Try running claude --version
    if claude_path:
        try:
            proc = subprocess.run(
                [claude_path, "--version"],
                capture_output=True, text=True, timeout=10,
            )
            result["checks"].append({
                "name": "claude_version",
                "ok": proc.returncode == 0,
                "detail": (proc.stdout.strip() or proc.stderr.strip())[:200],
            })
        except Exception as e:
            result["checks"].append({
                "name": "claude_version",
                "ok": False,
                "detail": str(e)[:200],
            })

    # 6. Try a minimal SDK query
    try:
        from claude_agent_sdk import query, ClaudeAgentOptions, AssistantMessage
        from claude_agent_sdk.types import TextBlock

        stderr_out: list[str] = []
        text_out: list[str] = []
        async for msg in query(
            prompt="Reply with exactly: OK",
            options=ClaudeAgentOptions(
                max_turns=1,
                model="claude-haiku-4-5-20251001",
                permission_mode="bypassPermissions",
                stderr=lambda line: stderr_out.append(line),
            ),
        ):
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        text_out.append(block.text)

        result["checks"].append({
            "name": "sdk_query",
            "ok": bool(text_out),
            "detail": "".join(text_out)[:200] or "empty response",
        })
    except Exception as e:
        result["checks"].append({
            "name": "sdk_query",
            "ok": False,
            "detail": str(e)[:300],
            "stderr": "".join(stderr_out[-5:])[:500] if stderr_out else "empty",
        })

    result["all_ok"] = all(c["ok"] for c in result["checks"])
    return result
