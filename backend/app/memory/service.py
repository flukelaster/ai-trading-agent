"""
Memory Service — CRUD operations for the layered agent memory system.
"""

import hashlib
from datetime import datetime, timedelta

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AgentMemory, MemoryCategory, MemoryTier

# Limits
MID_TERM_TTL_DAYS = 30
PROMOTE_MIN_HITS = 5
PROMOTE_MIN_CONFIDENCE = 0.7
PROMOTE_MIN_AGE_DAYS = 7
DECAY_CONFIDENCE_THRESHOLD = 0.4
DECAY_MIN_VALIDATIONS = 10
MAX_MID_TERM = 200
MAX_LONG_TERM = 100


def _content_hash(summary: str, symbol: str | None) -> str:
    """Compute SHA256 hash for dedup. Normalizes whitespace and case."""
    normalized = f"{symbol or 'global'}:{summary.strip().lower()}"
    return hashlib.sha256(normalized.encode()).hexdigest()


async def save_memory(
    db: AsyncSession,
    summary: str,
    category: str,
    symbol: str | None = None,
    evidence: dict | None = None,
    source: str = "reflector",
) -> dict:
    """Save a memory. If duplicate exists (same content_hash), merge by incrementing hit_count."""
    content_hash = _content_hash(summary, symbol)

    # Check for existing
    result = await db.execute(select(AgentMemory).where(AgentMemory.content_hash == content_hash))
    existing = result.scalar_one_or_none()

    if existing:
        existing.hit_count += 1
        existing.last_validated_at = datetime.utcnow()
        existing.confidence = existing.hit_count / (existing.hit_count + existing.miss_count)
        existing.updated_at = datetime.utcnow()
        if evidence:
            current_evidence = existing.evidence or {}
            current_evidence.update(evidence)
            existing.evidence = current_evidence
        await db.commit()
        return {
            "action": "merged",
            "id": existing.id,
            "hit_count": existing.hit_count,
            "confidence": round(existing.confidence, 3),
        }

    # Create new mid-term memory
    cat = MemoryCategory(category) if category in MemoryCategory.__members__.values() else MemoryCategory.PATTERN
    memory = AgentMemory(
        tier=MemoryTier.MID,
        category=cat,
        symbol=symbol,
        summary=summary.strip(),
        evidence=evidence,
        confidence=0.5,
        hit_count=1,
        miss_count=0,
        source=source,
        content_hash=content_hash,
        expires_at=datetime.utcnow() + timedelta(days=MID_TERM_TTL_DAYS),
    )
    db.add(memory)
    await db.commit()
    await db.refresh(memory)

    return {
        "action": "created",
        "id": memory.id,
        "tier": memory.tier.value,
        "expires_at": memory.expires_at.isoformat() if memory.expires_at else None,
    }


async def query_memories(
    db: AsyncSession,
    symbol: str | None = None,
    category: str | None = None,
    tier: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """Query memories sorted by confidence (desc), limited to keep context small."""
    query = select(AgentMemory)

    if symbol:
        # Include both symbol-specific and global memories
        query = query.where((AgentMemory.symbol == symbol) | (AgentMemory.symbol.is_(None)))
    if category:
        query = query.where(AgentMemory.category == category)
    if tier:
        query = query.where(AgentMemory.tier == tier)

    # Exclude expired mid-term
    query = query.where((AgentMemory.expires_at.is_(None)) | (AgentMemory.expires_at > datetime.utcnow()))

    query = query.order_by(desc(AgentMemory.confidence), desc(AgentMemory.last_validated_at)).limit(limit)

    result = await db.execute(query)
    memories = result.scalars().all()

    return [
        {
            "id": m.id,
            "tier": m.tier.value,
            "category": m.category.value,
            "symbol": m.symbol,
            "summary": m.summary,
            "confidence": round(m.confidence, 3),
            "hit_count": m.hit_count,
            "miss_count": m.miss_count,
            "created_at": m.created_at.isoformat(),
            "last_validated_at": m.last_validated_at.isoformat(),
        }
        for m in memories
    ]


async def validate_memory(
    db: AsyncSession,
    memory_id: int,
    hit: bool,
) -> dict:
    """Validate a memory — increment hit or miss count, recompute confidence."""
    result = await db.execute(select(AgentMemory).where(AgentMemory.id == memory_id))
    memory = result.scalar_one_or_none()
    if not memory:
        return {"error": "Memory not found", "id": memory_id}

    if hit:
        memory.hit_count += 1
    else:
        memory.miss_count += 1

    memory.confidence = memory.hit_count / (memory.hit_count + memory.miss_count)
    memory.last_validated_at = datetime.utcnow()
    memory.updated_at = datetime.utcnow()
    await db.commit()

    return {
        "id": memory.id,
        "hit_count": memory.hit_count,
        "miss_count": memory.miss_count,
        "confidence": round(memory.confidence, 3),
    }


async def get_stats(db: AsyncSession) -> dict:
    """Get memory system stats."""
    result = await db.execute(
        select(
            AgentMemory.tier,
            func.count(AgentMemory.id),
            func.avg(AgentMemory.confidence),
        ).group_by(AgentMemory.tier)
    )
    rows = result.all()

    stats = {"mid": {"count": 0, "avg_confidence": 0}, "long": {"count": 0, "avg_confidence": 0}}
    for tier, count, avg_conf in rows:
        stats[tier.value] = {
            "count": count,
            "avg_confidence": round(float(avg_conf or 0), 3),
        }

    return stats
