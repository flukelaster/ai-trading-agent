"""
Memory Consolidator — nightly job to promote, expire, and decay agent memories.

Runs daily at 02:00 UTC via APScheduler.
No LLM calls — pure SQL operations.
"""

from datetime import datetime, timedelta

from loguru import logger
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AgentMemory, MemoryTier
from app.memory.service import (
    DECAY_CONFIDENCE_THRESHOLD,
    DECAY_MIN_VALIDATIONS,
    MAX_LONG_TERM,
    MAX_MID_TERM,
    PROMOTE_MIN_AGE_DAYS,
    PROMOTE_MIN_CONFIDENCE,
    PROMOTE_MIN_HITS,
)


async def run_consolidation(db: AsyncSession) -> dict:
    """Run the full memory consolidation cycle."""
    promoted = await _promote_memories(db)
    expired = await _expire_memories(db)
    decayed = await _decay_memories(db)
    evicted = await _enforce_limits(db)

    summary = {
        "promoted": promoted,
        "expired": expired,
        "decayed": decayed,
        "evicted": evicted,
        "run_at": datetime.utcnow().isoformat(),
    }
    logger.info(f"Memory consolidation complete: {summary}")
    return summary


async def _promote_memories(db: AsyncSession) -> int:
    """Promote mid-term memories to long-term when criteria are met."""
    cutoff = datetime.utcnow() - timedelta(days=PROMOTE_MIN_AGE_DAYS)
    result = await db.execute(
        select(AgentMemory).where(
            AgentMemory.tier == MemoryTier.MID,
            AgentMemory.hit_count >= PROMOTE_MIN_HITS,
            AgentMemory.confidence >= PROMOTE_MIN_CONFIDENCE,
            AgentMemory.created_at <= cutoff,
        )
    )
    memories = result.scalars().all()

    for m in memories:
        m.tier = MemoryTier.LONG
        m.expires_at = None
        m.promoted_at = datetime.utcnow()
        m.updated_at = datetime.utcnow()

    if memories:
        await db.commit()
        logger.info(f"Promoted {len(memories)} memories to long-term")

    return len(memories)


async def _expire_memories(db: AsyncSession) -> int:
    """Delete mid-term memories past their expiry date."""
    result = await db.execute(
        delete(AgentMemory).where(
            AgentMemory.tier == MemoryTier.MID,
            AgentMemory.expires_at.isnot(None),
            AgentMemory.expires_at < datetime.utcnow(),
        )
    )
    count = result.rowcount
    if count:
        await db.commit()
        logger.info(f"Expired {count} mid-term memories")
    return count


async def _decay_memories(db: AsyncSession) -> int:
    """Demote long-term memories with low confidence back to mid-term."""
    result = await db.execute(
        select(AgentMemory).where(
            AgentMemory.tier == MemoryTier.LONG,
            AgentMemory.confidence < DECAY_CONFIDENCE_THRESHOLD,
            (AgentMemory.hit_count + AgentMemory.miss_count) >= DECAY_MIN_VALIDATIONS,
        )
    )
    memories = result.scalars().all()

    for m in memories:
        m.tier = MemoryTier.MID
        m.expires_at = datetime.utcnow() + timedelta(days=14)  # 14-day grace period
        m.promoted_at = None
        m.updated_at = datetime.utcnow()

    if memories:
        await db.commit()
        logger.info(f"Decayed {len(memories)} long-term memories to mid-term")

    return len(memories)


async def _enforce_limits(db: AsyncSession) -> int:
    """Evict lowest-confidence memories if over hard caps."""
    evicted = 0

    for tier, limit in [(MemoryTier.MID, MAX_MID_TERM), (MemoryTier.LONG, MAX_LONG_TERM)]:
        result = await db.execute(
            select(AgentMemory)
            .where(AgentMemory.tier == tier)
            .order_by(AgentMemory.confidence.desc())
        )
        all_memories = result.scalars().all()

        if len(all_memories) > limit:
            to_remove = all_memories[limit:]
            for m in to_remove:
                await db.delete(m)
            evicted += len(to_remove)

    if evicted:
        await db.commit()
        logger.info(f"Evicted {evicted} memories to enforce limits")

    return evicted
