"""
Backtest API routes.
"""

from fastapi import APIRouter
from pydantic import BaseModel

from app.backtest.engine import BacktestEngine
from app.config import Settings
from app.risk.manager import RiskManager
from app.strategy import get_strategy

router = APIRouter(prefix="/api/backtest", tags=["backtest"])

# Will use bot's market data service
_market_data = None


def set_market_data(md):
    global _market_data
    _market_data = md


class BacktestRequest(BaseModel):
    strategy: str = "ema_crossover"
    params: dict | None = None
    timeframe: str = "M15"
    count: int = 5000
    use_ai_filter: bool = False
    initial_balance: float = 10000.0
    risk_per_trade: float = 0.01
    max_lot: float = 1.0


@router.post("/run")
async def run_backtest(req: BacktestRequest):
    if not _market_data:
        return {"error": "Market data service not available"}

    strategy = get_strategy(req.strategy, req.params)
    risk_manager = RiskManager(
        max_risk_per_trade=req.risk_per_trade,
        max_lot=req.max_lot,
    )

    symbol = Settings().symbol
    df = await _market_data.get_ohlcv(symbol, req.timeframe, req.count)
    if df.empty:
        return {"error": "No OHLCV data available"}

    engine = BacktestEngine(strategy, risk_manager, req.initial_balance)
    result = engine.run(df, use_ai_filter=req.use_ai_filter)

    return result.to_dict()
