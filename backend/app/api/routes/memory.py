"""
Agent Memory API — layered memory system for AI agents.
"""

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_auth
from app.db.session import get_db
from app.memory.service import get_stats, query_memories, save_memory, validate_memory

router = APIRouter(prefix="/api/memory", tags=["memory"])


class SaveMemoryRequest(BaseModel):
    summary: str
    category: str = "pattern"
    symbol: str | None = None
    evidence: dict | None = None
    source: str = "reflector"


class ValidateRequest(BaseModel):
    hit: bool


@router.post("", dependencies=[Depends(require_auth)])
async def create_memory(req: SaveMemoryRequest, db: AsyncSession = Depends(get_db)):
    """Create or merge a memory."""
    return await save_memory(
        db,
        summary=req.summary,
        category=req.category,
        symbol=req.symbol,
        evidence=req.evidence,
        source=req.source,
    )


@router.get("", dependencies=[Depends(require_auth)])
async def list_memories(
    symbol: str | None = Query(None),
    category: str | None = Query(None),
    tier: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Query memories with filters."""
    memories = await query_memories(db, symbol=symbol, category=category, tier=tier, limit=limit)
    return {"memories": memories, "count": len(memories)}


@router.patch("/{memory_id}/validate", dependencies=[Depends(require_auth)])
async def validate(memory_id: int, req: ValidateRequest, db: AsyncSession = Depends(get_db)):
    """Validate a memory — hit or miss."""
    return await validate_memory(db, memory_id=memory_id, hit=req.hit)


@router.get("/stats", dependencies=[Depends(require_auth)])
async def memory_stats(db: AsyncSession = Depends(get_db)):
    """Get memory system stats."""
    return await get_stats(db)
