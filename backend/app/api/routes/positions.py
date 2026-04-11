"""
Positions API routes (multi-symbol).
"""

import asyncio

from fastapi import APIRouter, Query

from app.api.routes.bot import _get_engine, get_manager

router = APIRouter(prefix="/api/positions", tags=["positions"])


@router.get("")
async def get_positions(symbol: str | None = Query(None)):
    mgr = get_manager()
    if symbol:
        engine = _get_engine(symbol)
        positions = await engine.executor.get_open_positions(symbol)
        return {"positions": positions}

    # All symbols
    all_positions = []
    tasks = []
    for sym, engine in mgr.engines.items():
        tasks.append(engine.executor.get_open_positions(sym))
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for result in results:
        if isinstance(result, list):
            all_positions.extend(result)
    return {"positions": all_positions}


@router.delete("/{ticket}")
async def close_position(ticket: int):
    mgr = get_manager()
    # Use first engine's executor (they share the same connector)
    first_engine = next(iter(mgr.engines.values()))
    result = await first_engine.executor.close_position(ticket)
    return result
