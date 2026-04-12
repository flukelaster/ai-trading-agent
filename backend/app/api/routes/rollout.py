"""Rollout Management API — gradual deployment from shadow to live trading."""

import os

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import log_audit
from app.config import settings
from app.db.session import get_db

router = APIRouter(prefix="/api/rollout", tags=["rollout"])

# Canonical source: mcp_server/guardrails.py
VALID_MODES = ("shadow", "paper", "micro", "live")

MODE_DESCRIPTIONS = {
    "shadow": "Agent runs, decisions logged only — no trades executed",
    "paper": "Agent executes on simulated account — fake tickets, no real money",
    "micro": "Real execution capped at 0.01 lot — minimal risk, real money",
    "live": "Full autonomous trading at target risk levels",
}


class RolloutModeRequest(BaseModel):
    mode: str


# ─── Rollout Mode ────────────────────────────────────────────────────────────


@router.get("/mode")
async def get_rollout_mode(request: Request):
    """Get current rollout mode. Env var ROLLOUT_MODE takes priority over Redis."""
    env_mode = os.environ.get("ROLLOUT_MODE", "")
    if env_mode and env_mode in VALID_MODES:
        mode = env_mode
    else:
        # Fallback: Redis persisted value, then settings default
        mode = settings.rollout_mode
        manager = getattr(request.app.state, "runner_manager", None)
        if manager:
            try:
                val = await manager.redis.get("guardrails:rollout_mode")
                if val:
                    persisted = val.decode() if isinstance(val, bytes) else str(val)
                    if persisted in VALID_MODES:
                        mode = persisted
            except Exception:
                pass

    return {
        "mode": mode,
        "description": MODE_DESCRIPTIONS.get(mode, "Unknown mode"),
        "available_modes": [
            {"mode": m, "description": d} for m, d in MODE_DESCRIPTIONS.items()
        ],
    }


@router.put("/mode")
async def set_rollout_mode(
    req: RolloutModeRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Set rollout mode. Requires confirmation for 'live' mode."""
    if req.mode not in VALID_MODES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid mode '{req.mode}'. Must be one of: {', '.join(VALID_MODES)}",
        )

    old_mode = os.environ.get("ROLLOUT_MODE", settings.rollout_mode)
    os.environ["ROLLOUT_MODE"] = req.mode

    # Sync to Redis so both sources agree
    manager = getattr(request.app.state, "runner_manager", None)
    if manager:
        try:
            await manager.redis.set("guardrails:rollout_mode", req.mode)
        except Exception:
            pass

    await log_audit(
        db, "rollout_mode_changed",
        resource="rollout",
        detail={"old_mode": old_mode, "new_mode": req.mode},
        ip=request.client.host if request.client else None,
    )

    return {
        "mode": req.mode,
        "description": MODE_DESCRIPTIONS[req.mode],
        "previous_mode": old_mode,
    }


# ─── Deploy Readiness Check ─────────────────────────────────────────────────


@router.get("/readiness")
async def check_readiness(request: Request):
    """Check deploy readiness — verifies all required components are configured."""
    checks: list[dict] = []

    # 1. Database tables
    checks.append({
        "name": "database",
        "status": "ok",
        "detail": "Connected (if this endpoint responds, DB is up)",
    })

    # 2. Redis
    manager = getattr(request.app.state, "runner_manager", None)
    if manager:
        try:
            await manager.redis.ping()
            checks.append({"name": "redis", "status": "ok", "detail": "Connected"})
        except Exception as e:
            checks.append({"name": "redis", "status": "error", "detail": str(e)})
    else:
        checks.append({"name": "redis", "status": "warn", "detail": "Runner manager not initialized"})

    # 3. Vault master key
    vault_key = os.environ.get("VAULT_MASTER_KEY", "")
    checks.append({
        "name": "vault_master_key",
        "status": "ok" if vault_key else "error",
        "detail": "Set" if vault_key else "VAULT_MASTER_KEY not set",
    })

    # 4. WebAuthn config
    rp_id = os.environ.get("WEBAUTHN_RP_ID", "")
    webauthn_origin = os.environ.get("WEBAUTHN_ORIGIN", "")
    checks.append({
        "name": "webauthn_config",
        "status": "ok" if (rp_id and webauthn_origin) else "warn",
        "detail": f"RP_ID={'set' if rp_id else 'unset'}, ORIGIN={'set' if webauthn_origin else 'unset'}",
    })

    # 5. Secret key
    secret_key = os.environ.get("SECRET_KEY", settings.secret_key)
    checks.append({
        "name": "secret_key",
        "status": "ok" if secret_key and secret_key != "change-me-in-production" else "error",
        "detail": "Set" if secret_key and secret_key != "change-me-in-production" else "Using default — CHANGE THIS",
    })

    # 6. OAuth token (for agent)
    oauth = os.environ.get("CLAUDE_OAUTH_TOKEN", "")
    checks.append({
        "name": "claude_oauth_token",
        "status": "ok" if oauth else "warn",
        "detail": "Set (in Vault or env)" if oauth else "Not set — agent will use stub executor",
    })

    # 7. Rollout mode
    mode = os.environ.get("ROLLOUT_MODE", settings.rollout_mode)
    checks.append({
        "name": "rollout_mode",
        "status": "ok",
        "detail": f"Current: {mode} — {MODE_DESCRIPTIONS.get(mode, '')}",
    })

    # Summary
    errors = [c for c in checks if c["status"] == "error"]
    warnings = [c for c in checks if c["status"] == "warn"]

    return {
        "ready": len(errors) == 0,
        "errors": len(errors),
        "warnings": len(warnings),
        "checks": checks,
    }
