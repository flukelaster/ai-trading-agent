"""
Historical data collection API routes.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/data", tags=["data"])

_collector = None


def set_collector(collector):
    global _collector
    _collector = collector


def get_collector():
    if _collector is None:
        raise HTTPException(status_code=503, detail="Data collector not initialized")
    return _collector


class CollectRequest(BaseModel):
    symbol: str = "GOLD"
    timeframe: str = "M15"
    from_date: str  # ISO format: YYYY-MM-DD
    to_date: str


@router.post("/collect")
async def collect_data(req: CollectRequest):
    collector = get_collector()
    result = await collector.collect(req.symbol, req.timeframe, req.from_date, req.to_date)
    return result


@router.get("/status")
async def data_status(symbol: str | None = None):
    collector = get_collector()
    return await collector.get_data_status(symbol)
