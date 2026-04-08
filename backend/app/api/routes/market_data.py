"""
Market data API routes — OHLCV candles for charting.
"""

from fastapi import APIRouter, Query

from app.api.routes.bot import get_bot

router = APIRouter(prefix="/api/market-data", tags=["market-data"])


@router.get("/ohlcv")
async def get_ohlcv(
    timeframe: str = Query("M15"),
    count: int = Query(200, le=5000),
):
    bot = get_bot()
    df = await bot.market_data.get_ohlcv(bot.symbol, timeframe, count)
    if df.empty:
        return {"candles": []}

    candles = []
    for ts, row in df.iterrows():
        candles.append({
            "time": int(ts.timestamp()),
            "open": round(row["open"], 2),
            "high": round(row["high"], 2),
            "low": round(row["low"], 2),
            "close": round(row["close"], 2),
        })
    return {"candles": candles}
