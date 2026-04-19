"""
Admin routes — destructive/maintenance operations.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_auth
from app.db.models import Trade
from app.db.session import get_db

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.post("/trades/archive")
async def archive_trades_before(
    before: str = Query(..., description="Archive trades opened before this date (YYYY-MM-DD)"),
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_auth),
):
    """Mark all trades opened before `before` as archived (excluded from stats)."""
    try:
        cutoff = datetime.strptime(before, "%Y-%m-%d")
    except ValueError as exc:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD") from exc

    result = await db.execute(
        update(Trade).where(Trade.open_time < cutoff, Trade.is_archived.is_(False)).values(is_archived=True)
    )
    await db.commit()

    return {
        "archived": result.rowcount,
        "before": before,
        "message": f"Archived {result.rowcount} trades before {before}",
    }


@router.post("/trades/unarchive")
async def unarchive_trades_before(
    before: str = Query(..., description="Unarchive trades opened before this date (YYYY-MM-DD)"),
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_auth),
):
    """Restore archived trades (undo archive)."""
    try:
        cutoff = datetime.strptime(before, "%Y-%m-%d")
    except ValueError as exc:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD") from exc

    result = await db.execute(
        update(Trade).where(Trade.open_time < cutoff, Trade.is_archived.is_(True)).values(is_archived=False)
    )
    await db.commit()

    return {
        "unarchived": result.rowcount,
        "before": before,
        "message": f"Unarchived {result.rowcount} trades before {before}",
    }


@router.get("/trades/archive-count")
async def get_archive_count(
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_auth),
):
    """Count archived vs active trades."""
    from sqlalchemy import func, select

    result = await db.execute(select(Trade.is_archived, func.count(Trade.id)).group_by(Trade.is_archived))
    rows = result.all()
    counts = {str(r[0]): r[1] for r in rows}
    return {
        "active": counts.get("False", 0),
        "archived": counts.get("True", 0),
    }
