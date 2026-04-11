"""
OAuth Token Health Monitor — periodic checks on Claude OAuth token validity.

No API key fallback: if the token is invalid, the agent must pause.
"""

from datetime import UTC, datetime

import httpx
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Secret
from app.vault import vault


async def check_oauth_health(db: AsyncSession, notifier=None) -> dict:
    """Check Claude OAuth token validity.

    Called by BotScheduler every 5 minutes.
    Returns status dict: {status, message, latency_ms, checked_at}
    """
    if not vault.is_available:
        return {
            "status": "unavailable",
            "message": "Vault not configured",
            "checked_at": datetime.now(UTC).isoformat(),
        }

    # Find the Claude token in vault
    result = await db.execute(
        select(Secret).where(
            Secret.category == "auth",
            Secret.is_deleted.is_(False),
        )
    )
    secret = result.scalar_one_or_none()
    if not secret:
        return {
            "status": "missing",
            "message": "No auth token in vault",
            "checked_at": datetime.now(UTC).isoformat(),
        }

    try:
        token = vault.decrypt(secret.encrypted_value, secret.nonce)
    except Exception as e:
        logger.error(f"Vault health: failed to decrypt token — {e}")
        return {
            "status": "error",
            "message": "Failed to decrypt token",
            "checked_at": datetime.now(UTC).isoformat(),
        }

    # Test the token
    start = datetime.now(UTC)
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://api.anthropic.com/v1/models",
                headers={
                    "x-api-key": token,
                    "anthropic-version": "2023-06-01",
                },
            )
        latency_ms = int((datetime.now(UTC) - start).total_seconds() * 1000)

        if resp.status_code == 200:
            logger.debug(f"Vault health: OAuth token valid ({latency_ms}ms)")
            return {
                "status": "ok",
                "message": "Token valid",
                "latency_ms": latency_ms,
                "checked_at": datetime.now(UTC).isoformat(),
            }

        status_map = {
            401: ("invalid", "Token expired or revoked"),
            403: ("forbidden", "Token lacks required permissions"),
            429: ("rate_limited", "Token rate limited"),
        }
        status, message = status_map.get(
            resp.status_code,
            ("error", f"Unexpected status: {resp.status_code}"),
        )

        logger.warning(f"Vault health: OAuth token {status} — {message}")

        # Send alert for critical failures
        if status in ("invalid", "forbidden") and notifier:
            await _send_alert(notifier, status, message)

        return {
            "status": status,
            "message": message,
            "latency_ms": latency_ms,
            "checked_at": datetime.now(UTC).isoformat(),
        }

    except httpx.TimeoutException:
        logger.warning("Vault health: OAuth token check timed out")
        return {
            "status": "timeout",
            "message": "API check timed out",
            "checked_at": datetime.now(UTC).isoformat(),
        }
    except Exception as e:
        logger.error(f"Vault health: check failed — {e}")
        return {
            "status": "error",
            "message": str(e),
            "checked_at": datetime.now(UTC).isoformat(),
        }


async def _send_alert(notifier, status: str, message: str):
    """Send alert via Telegram."""
    try:
        alert_text = (
            f"🔴 OAuth Token Alert\n"
            f"Status: {status}\n"
            f"Message: {message}\n"
            f"Action: Check Secrets Vault and rotate token if needed."
        )
        await notifier.send(alert_text)
    except Exception as e:
        logger.error(f"Vault health: failed to send alert — {e}")
