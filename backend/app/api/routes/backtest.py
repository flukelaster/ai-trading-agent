"""
Backtest API routes.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.backtest.engine import BacktestEngine
from app.backtest.optimizer import grid_search
from app.config import Settings
from app.risk.manager import RiskManager
from app.strategy import get_strategy

router = APIRouter(prefix="/api/backtest", tags=["backtest"])

# Will use bot's market data service
_market_data = None
_collector = None


def set_market_data(md):
    global _market_data
    _market_data = md


def set_collector(collector):
    global _collector
    _collector = collector


class BacktestRequest(BaseModel):
    strategy: str = "ema_crossover"
    params: dict | None = None
    symbol: str = "GOLD"
    timeframe: str = "M15"
    count: int = 5000
    use_ai_filter: bool = False
    initial_balance: float = 10000.0
    risk_per_trade: float = 0.01
    max_lot: float = 1.0
    source: str = "mt5"  # "mt5" for live data, "db" for historical
    from_date: str | None = None
    to_date: str | None = None


class OptimizeRequest(BaseModel):
    strategy: str = "ema_crossover"
    param_grid: dict[str, list]  # e.g. {"fast_period": [10,20,30], "slow_period": [40,50,60]}
    symbol: str = "GOLD"
    timeframe: str = "M15"
    initial_balance: float = 10000.0
    risk_per_trade: float = 0.01
    max_lot: float = 1.0
    min_trades: int = 10
    source: str = "db"
    from_date: str | None = None
    to_date: str | None = None
    count: int = 5000


@router.post("/run")
async def run_backtest(req: BacktestRequest):
    df = await _load_data(req.symbol, req.source, req.timeframe, req.count, req.from_date, req.to_date)
    if df.empty:
        return {"error": "No OHLCV data available"}

    strategy = get_strategy(req.strategy, req.params)
    risk_manager = RiskManager(
        max_risk_per_trade=req.risk_per_trade,
        max_lot=req.max_lot,
    )

    engine = BacktestEngine(strategy, risk_manager, req.initial_balance)
    result = engine.run(df, use_ai_filter=req.use_ai_filter)

    return result.to_dict()


@router.post("/optimize")
async def run_optimization(req: OptimizeRequest):
    df = await _load_data(req.symbol, req.source, req.timeframe, req.count, req.from_date, req.to_date)
    if df.empty:
        return {"error": "No OHLCV data available"}

    result = grid_search(
        strategy_name=req.strategy,
        df=df,
        param_grid=req.param_grid,
        initial_balance=req.initial_balance,
        risk_per_trade=req.risk_per_trade,
        max_lot=req.max_lot,
        min_trades=req.min_trades,
    )
    return result.to_dict()


async def _load_data(symbol: str, source: str, timeframe: str, count: int, from_date: str | None, to_date: str | None):
    """Load OHLCV data from MT5 (live) or DB (historical)."""
    if source == "db":
        if _collector is None:
            raise HTTPException(status_code=503, detail="Data collector not initialized")
        return await _collector.load_from_db(symbol, timeframe, from_date, to_date)
    else:
        if _market_data is None:
            raise HTTPException(status_code=503, detail="Market data service not available")
        return await _market_data.get_ohlcv(symbol, timeframe, count)
