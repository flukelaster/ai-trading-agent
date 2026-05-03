"""Shared audit logging utility."""

from loguru import logger
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

    Failures are logged at ERROR (not silenced) so a broken audit pipeline shows
    up in observability. Audit must be best-effort but never invisible — losing
    an audit trail without alarm is itself a compliance event.
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
    except Exception as e:
        logger.error(f"audit_log_write_failed action={action!r} resource={resource!r}: {e!r}")
        # Only roll back when we own the transaction. With auto_commit=False the
        # caller is mid-transaction — a rollback here would discard their pending
        # work. Caller's own except handler is responsible in that mode.
        if auto_commit:
            try:
                await db.rollback()
            except Exception as rb_err:
                logger.error(f"audit_log_rollback_failed action={action!r}: {rb_err!r}")
