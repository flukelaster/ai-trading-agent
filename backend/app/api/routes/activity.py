"""
AI Activity Log — unified timeline of all AI actions (sentiment, trades, optimization, signals).
"""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, select, union_all, literal, cast, String, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_auth
from app.db.models import BotEvent, NewsSentiment, AIOptimizationLog, Trade
from app.db.session import get_db

router = APIRouter(prefix="/api/ai/activity", tags=["activity"])


# Event type → category mapping (includes system events for visibility)
_AI_EVENT_MAP: dict[str, str] = {
    "TRADE_OPENED": "trade",
    "TRADE_CLOSED": "trade",
    "SIGNAL_DETECTED": "signal",
    "TRADE_BLOCKED": "signal",
    "SENTIMENT_CHANGE": "sentiment",
    "OPTIMIZATION_RUN": "optimization",
    "CIRCUIT_BREAKER": "risk",
    "ORDER_FAILED": "error",
    "STRATEGY_CHANGED": "optimization",
    "STARTED": "system",
    "STOPPED": "system",
    "ERROR": "error",
    "SETTINGS_CHANGED": "system",
}


@router.get("", dependencies=[Depends(require_auth)])
async def get_activity_log(
    days: int = Query(7, ge=1, le=30),
    category: str | None = Query(None, description="Filter: trade, signal, sentiment, optimization, risk, error, system"),
    limit: int = Query(200, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
):
    """Unified AI activity timeline from multiple data sources."""
    cutoff = datetime.utcnow() - timedelta(days=days)

    # 1. Bot events (AI + system)
    ai_event_types = list(_AI_EVENT_MAP.keys())
    events_q = (
        select(BotEvent)
        .where(BotEvent.created_at >= cutoff, BotEvent.event_type.in_(ai_event_types))
        .order_by(desc(BotEvent.created_at))
        .limit(500)
    )
    events_result = await db.execute(events_q)
    bot_events = events_result.scalars().all()

    items: list[dict] = []
    for e in bot_events:
        cat = _AI_EVENT_MAP.get(e.event_type.value)
        if not cat:
            continue
        if category and cat != category:
            continue
        items.append({
            "id": f"evt-{e.id}",
            "timestamp": e.created_at.isoformat(),
            "category": cat,
            "type": e.event_type.value,
            "title": e.event_type.value.replace("_", " ").title(),
            "message": e.message,
            "source": "bot_engine",
        })

    # 2. Sentiment analyses (aggregated per analysis run — group by minute)
    if not category or category == "sentiment":
        sent_q = (
            select(NewsSentiment)
            .where(NewsSentiment.created_at >= cutoff)
            .order_by(desc(NewsSentiment.created_at))
            .limit(500)
        )
        sent_result = await db.execute(sent_q)
        sentiments = sent_result.scalars().all()

        # Group by minute to collapse multi-headline analyses
        grouped: dict[str, list] = {}
        for s in sentiments:
            key = s.created_at.strftime("%Y-%m-%d %H:%M")
            grouped.setdefault(key, []).append(s)

        for minute_key, group in grouped.items():
            # Use the dominant sentiment in this batch
            labels = [s.sentiment_label for s in group]
            dominant = max(set(labels), key=labels.count)
            avg_confidence = sum(s.confidence for s in group) / len(group)
            headlines = [s.headline for s in group[:3]]  # Show up to 3

            items.append({
                "id": f"sent-{group[0].id}",
                "timestamp": group[0].created_at.isoformat(),
                "category": "sentiment",
                "type": "SENTIMENT_ANALYSIS",
                "title": f"Sentiment: {dominant.upper()}",
                "message": f"{len(group)} headlines analyzed — {dominant} ({avg_confidence:.0%} confidence). {'; '.join(headlines)}",
                "source": "news_sentiment",
                "meta": {
                    "label": dominant,
                    "confidence": round(avg_confidence, 3),
                    "headline_count": len(group),
                },
            })

    # 3. Optimization runs
    if not category or category == "optimization":
        opt_q = (
            select(AIOptimizationLog)
            .where(AIOptimizationLog.created_at >= cutoff)
            .order_by(desc(AIOptimizationLog.created_at))
            .limit(50)
        )
        opt_result = await db.execute(opt_q)
        optimizations = opt_result.scalars().all()

        import json
        for o in optimizations:
            items.append({
                "id": f"opt-{o.id}",
                "timestamp": o.created_at.isoformat(),
                "category": "optimization",
                "type": "OPTIMIZATION_RUN",
                "title": f"Strategy Optimization {'(Applied)' if o.applied else '(Pending)'}",
                "message": o.rationale or "AI suggested parameter changes",
                "source": "optimizer",
                "meta": {
                    "confidence": o.confidence,
                    "applied": o.applied,
                    "suggested_params": json.loads(o.suggested_params) if o.suggested_params else {},
                },
            })

    # 4. Trades with AI sentiment data
    if not category or category == "trade":
        trade_q = (
            select(Trade)
            .where(Trade.created_at >= cutoff, Trade.ai_sentiment_label.isnot(None))
            .order_by(desc(Trade.created_at))
            .limit(100)
        )
        trade_result = await db.execute(trade_q)
        trades = trade_result.scalars().all()

        for t in trades:
            profit_str = f"${t.profit:.2f}" if t.profit is not None else "open"
            items.append({
                "id": f"trade-{t.id}",
                "timestamp": t.created_at.isoformat(),
                "category": "trade",
                "type": "AI_TRADE",
                "title": f"{t.order_type} {t.symbol}" if hasattr(t, "order_type") else f"Trade {t.symbol}",
                "message": f"AI sentiment: {t.ai_sentiment_label} ({t.ai_sentiment_score:.0%}) — P/L: {profit_str}",
                "source": "ai_trade",
                "meta": {
                    "symbol": t.symbol,
                    "sentiment_label": t.ai_sentiment_label,
                    "sentiment_score": t.ai_sentiment_score,
                    "profit": t.profit,
                },
            })

    # Sort all items by timestamp descending and limit
    items.sort(key=lambda x: x["timestamp"], reverse=True)
    items = items[:limit]

    # Summary stats
    categories = {}
    for item in items:
        cat = item["category"]
        categories[cat] = categories.get(cat, 0) + 1

    return {
        "items": items,
        "total": len(items),
        "period_days": days,
        "categories": categories,
    }


@router.get("/summary", dependencies=[Depends(require_auth)])
async def get_activity_summary(
    days: int = Query(7, ge=1, le=30),
    db: AsyncSession = Depends(get_db),
):
    """Quick summary counts for the activity dashboard header."""
    cutoff = datetime.utcnow() - timedelta(days=days)

    # Count queries in parallel-ish (SQLAlchemy async)
    events_count = await db.execute(
        select(func.count(BotEvent.id)).where(BotEvent.created_at >= cutoff)
    )
    sentiment_count = await db.execute(
        select(func.count(NewsSentiment.id)).where(NewsSentiment.created_at >= cutoff)
    )
    trade_count = await db.execute(
        select(func.count(Trade.id)).where(
            Trade.created_at >= cutoff,
            Trade.ai_sentiment_label.isnot(None),
        )
    )
    opt_count = await db.execute(
        select(func.count(AIOptimizationLog.id)).where(AIOptimizationLog.created_at >= cutoff)
    )

    return {
        "period_days": days,
        "total_events": events_count.scalar() or 0,
        "sentiment_analyses": sentiment_count.scalar() or 0,
        "ai_trades": trade_count.scalar() or 0,
        "optimization_runs": opt_count.scalar() or 0,
    }
