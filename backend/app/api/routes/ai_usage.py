"""
AI usage monitoring API — token consumption and equivalent USD cost.
"""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_auth
from app.db.models import AIUsageLog
from app.db.session import get_db

router = APIRouter(
    prefix="/api/ai-usage",
    tags=["ai-usage"],
    dependencies=[Depends(require_auth)],
)


def _effective_cost(sdk: float | None, calc: float | None) -> float:
    if sdk is not None:
        return sdk
    if calc is not None:
        return calc
    return 0.0


@router.get("/summary")
async def get_summary(
    days: int = Query(7, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
):
    cutoff = datetime.utcnow() - timedelta(days=days)
    result = await db.execute(select(AIUsageLog).where(AIUsageLog.timestamp >= cutoff))
    rows = result.scalars().all()

    total_calls = len(rows)
    input_tokens = sum(r.input_tokens for r in rows)
    output_tokens = sum(r.output_tokens for r in rows)
    cache_read = sum(r.cache_read_tokens for r in rows)
    cache_write = sum(r.cache_write_tokens for r in rows)
    total_cost = sum(_effective_cost(r.cost_usd_sdk, r.cost_usd_calc) for r in rows)
    success_count = sum(1 for r in rows if r.success)

    models: dict[str, dict] = {}
    for r in rows:
        m = models.setdefault(r.model, {"calls": 0, "tokens": 0, "cost_usd": 0.0})
        m["calls"] += 1
        m["tokens"] += r.input_tokens + r.output_tokens + r.cache_read_tokens + r.cache_write_tokens
        m["cost_usd"] += _effective_cost(r.cost_usd_sdk, r.cost_usd_calc)

    agents: dict[str, dict] = {}
    for r in rows:
        a = agents.setdefault(r.agent_id, {"calls": 0, "tokens": 0, "cost_usd": 0.0})
        a["calls"] += 1
        a["tokens"] += r.input_tokens + r.output_tokens + r.cache_read_tokens + r.cache_write_tokens
        a["cost_usd"] += _effective_cost(r.cost_usd_sdk, r.cost_usd_calc)

    return {
        "total_calls": total_calls,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_read": cache_read,
        "cache_write": cache_write,
        "total_tokens": input_tokens + output_tokens + cache_read + cache_write,
        "total_cost_usd": round(total_cost, 4),
        "avg_cost_per_call": round(total_cost / total_calls, 4) if total_calls else 0,
        "success_rate": round(success_count / total_calls, 4) if total_calls else 0,
        "models": {k: {**v, "cost_usd": round(v["cost_usd"], 4)} for k, v in models.items()},
        "agents": {k: {**v, "cost_usd": round(v["cost_usd"], 4)} for k, v in agents.items()},
        "period_days": days,
    }


@router.get("/timeseries")
async def get_timeseries(
    days: int = Query(7, ge=1, le=365),
    granularity: str = Query("day", pattern="^(day|hour)$"),
    db: AsyncSession = Depends(get_db),
):
    cutoff = datetime.utcnow() - timedelta(days=days)
    result = await db.execute(select(AIUsageLog).where(AIUsageLog.timestamp >= cutoff).order_by(AIUsageLog.timestamp))
    rows = result.scalars().all()

    fmt = "%Y-%m-%d" if granularity == "day" else "%Y-%m-%d %H:00"
    buckets: dict[str, dict] = {}
    for r in rows:
        key = r.timestamp.strftime(fmt)
        b = buckets.setdefault(
            key,
            {
                "date": key,
                "input_tokens": 0,
                "output_tokens": 0,
                "cache_read": 0,
                "cache_write": 0,
                "cost_usd": 0.0,
                "calls": 0,
            },
        )
        b["input_tokens"] += r.input_tokens
        b["output_tokens"] += r.output_tokens
        b["cache_read"] += r.cache_read_tokens
        b["cache_write"] += r.cache_write_tokens
        b["cost_usd"] += _effective_cost(r.cost_usd_sdk, r.cost_usd_calc)
        b["calls"] += 1

    series = sorted(buckets.values(), key=lambda b: b["date"])
    for b in series:
        b["cost_usd"] = round(b["cost_usd"], 4)
    return {"granularity": granularity, "period_days": days, "series": series}


@router.get("/breakdown")
async def get_breakdown(
    days: int = Query(7, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
):
    cutoff = datetime.utcnow() - timedelta(days=days)
    result = await db.execute(select(AIUsageLog).where(AIUsageLog.timestamp >= cutoff))
    rows = result.scalars().all()

    groups: dict[tuple[str, str], dict] = {}
    for r in rows:
        key = (r.agent_id, r.model)
        g = groups.setdefault(
            key,
            {
                "agent_id": r.agent_id,
                "model": r.model,
                "calls": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "cache_read": 0,
                "cache_write": 0,
                "cost_usd": 0.0,
                "total_duration_ms": 0,
                "tool_calls": 0,
                "success_count": 0,
            },
        )
        g["calls"] += 1
        g["input_tokens"] += r.input_tokens
        g["output_tokens"] += r.output_tokens
        g["cache_read"] += r.cache_read_tokens
        g["cache_write"] += r.cache_write_tokens
        g["cost_usd"] += _effective_cost(r.cost_usd_sdk, r.cost_usd_calc)
        g["total_duration_ms"] += r.duration_ms
        g["tool_calls"] += r.tool_calls_count
        if r.success:
            g["success_count"] += 1

    items = []
    for g in groups.values():
        calls = g["calls"]
        items.append(
            {
                **g,
                "avg_duration_ms": round(g["total_duration_ms"] / calls) if calls else 0,
                "cost_usd": round(g["cost_usd"], 4),
                "success_rate": round(g["success_count"] / calls, 4) if calls else 0,
            }
        )
    items.sort(key=lambda x: x["cost_usd"], reverse=True)
    return {"items": items, "period_days": days}


@router.get("/recent")
async def get_recent(
    limit: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(AIUsageLog).order_by(desc(AIUsageLog.timestamp)).limit(limit))
    rows = result.scalars().all()
    return {
        "items": [
            {
                "id": r.id,
                "timestamp": r.timestamp.isoformat(),
                "agent_id": r.agent_id,
                "model": r.model,
                "input_tokens": r.input_tokens,
                "output_tokens": r.output_tokens,
                "cache_read": r.cache_read_tokens,
                "cache_write": r.cache_write_tokens,
                "total_tokens": r.input_tokens + r.output_tokens + r.cache_read_tokens + r.cache_write_tokens,
                "cost_usd": round(_effective_cost(r.cost_usd_sdk, r.cost_usd_calc), 4),
                "duration_ms": r.duration_ms,
                "turns": r.turns,
                "tool_calls_count": r.tool_calls_count,
                "success": r.success,
            }
            for r in rows
        ]
    }
