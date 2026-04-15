"""
AI Insights API routes — sentiment and optimization.
"""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth import require_auth
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.bot import _get_engine, get_manager
from app.db.models import AIOptimizationLog, NewsSentiment
from app.db.session import get_db

router = APIRouter(prefix="/api/ai", tags=["ai"])


@router.get("/sentiment")
async def get_latest_sentiment(symbol: str | None = Query(None)):
    bot = _get_engine(symbol)
    if not bot.sentiment_analyzer:
        return {"label": "neutral", "score": 0, "confidence": 0, "key_factors": [], "source_count": 0}
    sentiment = await bot.sentiment_analyzer.get_latest_sentiment(symbol=bot.symbol)
    return {**sentiment.to_dict(), "symbol": bot.symbol}


@router.get("/sentiment/history")
async def get_sentiment_history(
    days: int = Query(7, ge=1, le=30),
    db: AsyncSession = Depends(get_db),
):
    cutoff = datetime.utcnow() - timedelta(days=days)
    result = await db.execute(
        select(NewsSentiment)
        .where(NewsSentiment.created_at >= cutoff)
        .order_by(desc(NewsSentiment.created_at))
        .limit(500)
    )
    records = result.scalars().all()

    return {
        "history": [
            {
                "headline": r.headline,
                "source": r.source,
                "sentiment_label": r.sentiment_label,
                "sentiment_score": r.sentiment_score,
                "confidence": r.confidence,
                "created_at": r.created_at.isoformat(),
            }
            for r in records
        ]
    }


@router.get("/optimization/latest")
async def get_latest_optimization(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(AIOptimizationLog).order_by(desc(AIOptimizationLog.created_at)).limit(1)
    )
    log = result.scalar_one_or_none()
    if not log:
        return {"message": "No optimization runs yet"}
    import json
    return {
        "id": log.id,
        "period_start": log.period_start.isoformat(),
        "period_end": log.period_end.isoformat(),
        "current_params": json.loads(log.current_params),
        "suggested_params": json.loads(log.suggested_params),
        "rationale": log.rationale,
        "confidence": log.confidence,
        "applied": log.applied,
        "created_at": log.created_at.isoformat(),
    }


@router.get("/context")
async def get_ai_context():
    """Return the current AI context enrichment data."""
    bot = _get_engine()
    context = await bot.context_builder.build_full_context(bot.symbol, bot.timeframe)
    return context


@router.post("/optimization/run", dependencies=[Depends(require_auth)])
async def run_optimization():
    bot = _get_engine()
    if not hasattr(bot, "_optimizer") or bot._optimizer is None:
        raise HTTPException(status_code=503, detail="Optimizer not configured")
    if bot.strategy is None:
        raise HTTPException(status_code=400, detail="Cannot optimize in AI Autonomous mode — select a strategy first")
    result = await bot._optimizer.optimize(bot.strategy.get_params())
    if result is None:
        raise HTTPException(status_code=500, detail="Optimization failed")
    return result.to_dict()


@router.post("/optimization/{log_id}/apply", dependencies=[Depends(require_auth)])
async def apply_optimization(log_id: int, db: AsyncSession = Depends(get_db)):
    bot = _get_engine()
    if bot.state.value == "RUNNING":
        raise HTTPException(status_code=400, detail="Stop the bot before applying optimization")

    result = await db.execute(select(AIOptimizationLog).where(AIOptimizationLog.id == log_id))
    log = result.scalar_one_or_none()
    if not log:
        raise HTTPException(status_code=404, detail="Optimization log not found")

    import json
    suggested = json.loads(log.suggested_params)
    if bot.strategy is None:
        raise HTTPException(status_code=400, detail="Cannot apply optimization in AI Autonomous mode")
    await bot.update_strategy(bot.strategy.name, suggested)
    log.applied = True
    await db.commit()

    return {"status": "applied", "params": suggested}
