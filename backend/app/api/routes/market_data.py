"""
Market data API routes — OHLCV candles for charting (multi-symbol).
"""

from fastapi import APIRouter, Depends, Query

from app.api.routes.bot import _get_engine, get_manager
from app.auth import require_auth
from app.config import SYMBOL_PROFILES

router = APIRouter(
    prefix="/api/market-data",
    tags=["market-data"],
    dependencies=[Depends(require_auth)],
)


@router.get("/ohlcv")
async def get_ohlcv(
    symbol: str = Query("GOLD"),
    timeframe: str = Query("M15"),
    count: int = Query(200, le=5000),
):
    engine = _get_engine(symbol)
    # market_data.get_ohlcv internally resolves canonical → broker alias
    df = await engine.market_data.get_ohlcv(engine.symbol, timeframe, count)
    if df.empty:
        return {"candles": []}

    profile = SYMBOL_PROFILES.get(engine.symbol, {})
    decimals = profile.get("price_decimals", 2)

    candles = []
    for ts, row in df.iterrows():
        candles.append({
            "time": int(ts.timestamp()),
            "open": round(row["open"], decimals),
            "high": round(row["high"], decimals),
            "low": round(row["low"], decimals),
            "close": round(row["close"], decimals),
        })
    return {"candles": candles}


@router.get("/symbols")
async def get_symbols():
    """Return all configured symbols with their profiles."""
    mgr = get_manager()
    symbols = []
    for sym in mgr.get_symbols():
        profile = SYMBOL_PROFILES.get(sym, {})
        engine = mgr.get_engine(sym)
        symbols.append({
            "symbol": sym,
            "display_name": profile.get("display_name", sym),
            "timeframe": engine.timeframe if engine else profile.get("default_timeframe", "M15"),
            "state": engine.state.value if engine else "STOPPED",
            "price_decimals": profile.get("price_decimals", 2),
            "max_lot": profile.get("max_lot", 1.0),
            "default_lot": profile.get("default_lot", 0.1),
            "ml_tp_pips": profile.get("ml_tp_pips", 5.0),
            "ml_sl_pips": profile.get("ml_sl_pips", 5.0),
            "ml_forward_bars": profile.get("ml_forward_bars", 10),
            "ml_timeframe": profile.get("ml_timeframe", profile.get("default_timeframe", "M15")),
        })
    return {"symbols": symbols}
