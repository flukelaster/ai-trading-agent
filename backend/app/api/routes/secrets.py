"""Secrets Vault API — encrypted secrets CRUD with audit logging."""

from datetime import datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from loguru import logger
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import log_audit
from app.auth import require_auth
from app.db.models import AuditLog, Secret
from app.db.session import get_db
from app.vault import VaultUnavailableError, vault

router = APIRouter(prefix="/api/secrets", tags=["secrets"])


# ─── Schemas ──────────────────────────────────────────────────────────────────


class SecretUpsertRequest(BaseModel):
    value: str
    category: str = "general"
    description: str | None = None
    is_required: bool = False


class SecretResponse(BaseModel):
    key: str
    category: str
    description: str | None
    is_required: bool
    has_value: bool
    last_rotated_at: str | None
    created_at: str
    updated_at: str | None


class SecretDetailResponse(SecretResponse):
    masked_value: str


# ─── Vault Status ────────────────────────────────────────────────────────────


@router.get("/vault-status", dependencies=[Depends(require_auth)])
async def get_vault_status():
    """Check if the vault is available (master key configured)."""
    return {"available": vault.is_available}


# ─── List Secrets ────────────────────────────────────────────────────────────


@router.get("", dependencies=[Depends(require_auth)])
async def list_secrets(db: AsyncSession = Depends(get_db)):
    """List all non-deleted secrets (no decryption needed)."""
    result = await db.execute(select(Secret).where(Secret.is_deleted.is_(False)).order_by(Secret.category, Secret.key))
    secrets = result.scalars().all()
    return [
        SecretResponse(
            key=s.key,
            category=s.category,
            description=s.description,
            is_required=s.is_required,
            has_value=True,
            last_rotated_at=s.last_rotated_at.isoformat() if s.last_rotated_at else None,
            created_at=s.created_at.isoformat() if s.created_at else "",
            updated_at=s.updated_at.isoformat() if s.updated_at else None,
        )
        for s in secrets
    ]


# ─── Get Secret (masked) ────────────────────────────────────────────────────


@router.get("/{key}", dependencies=[Depends(require_auth)])
async def get_secret(
    key: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Get a secret with masked value."""
    secret = await _get_secret_or_404(db, key)

    try:
        plaintext = vault.decrypt(secret.encrypted_value, secret.nonce)
        masked = vault.mask_value(plaintext)
    except VaultUnavailableError:
        raise
    except Exception:
        masked = "*** (decryption error)"

    await log_audit(
        db,
        "secret_read",
        resource=f"secret:{key}",
        ip=request.client.host if request.client else None,
    )

    return SecretDetailResponse(
        key=secret.key,
        category=secret.category,
        description=secret.description,
        is_required=secret.is_required,
        has_value=True,
        masked_value=masked,
        last_rotated_at=secret.last_rotated_at.isoformat() if secret.last_rotated_at else None,
        created_at=secret.created_at.isoformat() if secret.created_at else "",
        updated_at=secret.updated_at.isoformat() if secret.updated_at else None,
    )


# ─── Upsert Secret ──────────────────────────────────────────────────────────


@router.put("/{key}", dependencies=[Depends(require_auth)])
async def upsert_secret(
    key: str,
    req: SecretUpsertRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Create or update a secret (encrypt + audit log)."""
    ciphertext, nonce = vault.encrypt(req.value)

    result = await db.execute(select(Secret).where(Secret.key == key))
    existing = result.scalar_one_or_none()

    if existing:
        existing.encrypted_value = ciphertext
        existing.nonce = nonce
        existing.category = req.category
        existing.description = req.description
        existing.is_required = req.is_required
        existing.is_deleted = False
        existing.last_rotated_at = datetime.utcnow()
        existing.updated_at = datetime.utcnow()
        action = "secret_updated"
    else:
        secret = Secret(
            key=key,
            encrypted_value=ciphertext,
            nonce=nonce,
            category=req.category,
            description=req.description,
            is_required=req.is_required,
        )
        db.add(secret)
        action = "secret_created"

    await log_audit(
        db,
        action,
        resource=f"secret:{key}",
        detail={"category": req.category},
        ip=request.client.host if request.client else None,
        auto_commit=False,
    )
    await db.commit()

    logger.info(f"Vault: {action} — {key} (category: {req.category})")
    return {"status": action, "key": key}


# ─── Delete Secret (soft) ───────────────────────────────────────────────────


@router.delete("/{key}", dependencies=[Depends(require_auth)])
async def delete_secret(
    key: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Soft-delete a secret."""
    secret = await _get_secret_or_404(db, key)
    secret.is_deleted = True
    secret.updated_at = datetime.utcnow()

    await log_audit(
        db,
        "secret_deleted",
        resource=f"secret:{key}",
        ip=request.client.host if request.client else None,
        auto_commit=False,
    )
    await db.commit()

    logger.info(f"Vault: secret deleted — {key}")
    return {"status": "deleted", "key": key}


# ─── Test Secret Connectivity ───────────────────────────────────────────────


@router.post("/{key}/test", dependencies=[Depends(require_auth)])
async def test_secret(
    key: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Test a secret's connectivity (e.g., validate an API key)."""
    secret = await _get_secret_or_404(db, key)
    plaintext = vault.decrypt(secret.encrypted_value, secret.nonce)

    tester = _SECRET_TESTERS.get(secret.category)
    if not tester:
        return {"testable": False, "message": f"No test available for category '{secret.category}'"}

    start = datetime.utcnow()
    try:
        result = await tester(plaintext)
        latency_ms = int((datetime.utcnow() - start).total_seconds() * 1000)
        status = "ok" if result["ok"] else "error"

        await log_audit(
            db,
            "secret_tested",
            resource=f"secret:{key}",
            detail={"status": status, "latency_ms": latency_ms},
            ip=request.client.host if request.client else None,
            success=result["ok"],
        )
        return {"status": status, "message": result["message"], "latency_ms": latency_ms}
    except Exception as e:
        latency_ms = int((datetime.utcnow() - start).total_seconds() * 1000)
        await log_audit(
            db,
            "secret_tested",
            resource=f"secret:{key}",
            detail={"status": "error", "error": str(e)},
            ip=request.client.host if request.client else None,
            success=False,
        )
        return {"status": "error", "message": str(e), "latency_ms": latency_ms}


# ─── Secret History ──────────────────────────────────────────────────────────


@router.get("/{key}/history", dependencies=[Depends(require_auth)])
async def get_secret_history(
    key: str,
    db: AsyncSession = Depends(get_db),
):
    """Get audit log entries for a specific secret."""
    result = await db.execute(
        select(AuditLog).where(AuditLog.resource == f"secret:{key}").order_by(AuditLog.created_at.desc()).limit(50)
    )
    entries = result.scalars().all()
    return [
        {
            "id": e.id,
            "action": e.action,
            "actor": e.actor,
            "detail": e.detail,
            "ip_address": e.ip_address,
            "success": e.success,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in entries
    ]


# ─── Helpers ─────────────────────────────────────────────────────────────────


async def _get_secret_or_404(db: AsyncSession, key: str) -> Secret:
    result = await db.execute(select(Secret).where(Secret.key == key, Secret.is_deleted.is_(False)))
    secret = result.scalar_one_or_none()
    if not secret:
        raise HTTPException(status_code=404, detail=f"Secret '{key}' not found")
    return secret


# ─── Connectivity Testers ────────────────────────────────────────────────────


async def _test_anthropic(token: str) -> dict:
    """Test Claude AI via Agent SDK (Max subscription)."""
    try:
        from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, query
        from claude_agent_sdk.types import TextBlock

        text = ""
        async for msg in query(
            prompt="Say OK",
            options=ClaudeAgentOptions(max_turns=1, model="claude-haiku-4-5-20251001"),
        ):
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        text = block.text
        if text:
            return {"ok": True, "message": "Claude (Max subscription) connected via Agent SDK"}
    except Exception as e:
        if "rate_limit" in str(e).lower():
            return {"ok": True, "message": "Claude (Max subscription) connected (rate limited)"}
        return {"ok": False, "message": f"Agent SDK error: {e}"}


async def _test_telegram(token: str) -> dict:
    """Test Telegram bot token via getMe."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(f"https://api.telegram.org/bot{token}/getMe")
        data = resp.json()
        if data.get("ok"):
            bot_name = data.get("result", {}).get("username", "unknown")
            return {"ok": True, "message": f"Telegram bot: @{bot_name}"}
        return {"ok": False, "message": f"Telegram error: {data.get('description', 'unknown')}"}


async def _test_fred(api_key: str) -> dict:
    """Test FRED API key."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            "https://api.stlouisfed.org/fred/series",
            params={"series_id": "DGS10", "api_key": api_key, "file_type": "json"},
        )
        if resp.status_code == 200:
            return {"ok": True, "message": "FRED API key valid"}
        return {"ok": False, "message": f"FRED API error: {resp.status_code}"}


_SECRET_TESTERS = {
    "auth": _test_anthropic,
    "notification": _test_telegram,
    "macro": _test_fred,
}
