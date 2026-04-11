"""Shared audit logging utility."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLog


async def log_audit(
    db: AsyncSession,
    action: str,
    actor: str = "owner",
    resource: str | None = None,
    detail: dict | None = None,
    ip: str | None = None,
    success: bool = True,
    auto_commit: bool = True,
):
    """Log an audit event.

    Args:
        auto_commit: If True (default), commits immediately.
                     Set False to let the caller commit as part of a larger transaction.
    """
    try:
        log = AuditLog(
            action=action,
            actor=actor,
            resource=resource,
            detail=detail,
            ip_address=ip,
            success=success,
        )
        db.add(log)
        if auto_commit:
            await db.commit()
    except Exception:
        try:
            await db.rollback()
        except Exception:
            pass
