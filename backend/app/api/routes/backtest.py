"""
Backtest API routes.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_auth
from app.backtest.engine import BacktestEngine
from app.backtest.monte_carlo import monte_carlo_analysis
from app.backtest.optimizer import grid_search
from app.backtest.walk_forward import walk_forward_test
from app.db.models import NewsSentiment
from app.db.session import get_db
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


class _BacktestBase(BaseModel):
    """Shared fields for all backtest request models."""
    symbol: str = "GOLD"
    timeframe: str = "M15"
    initial_balance: float = Field(10000.0, ge=100.0)
    risk_per_trade: float = Field(0.01, ge=0.001, le=0.10)
    max_lot: float = Field(1.0, ge=0.01, le=100.0)
    source: str = "db"
    from_date: str | None = None
    to_date: str | None = None
    count: int = Field(5000, ge=100, le=50000)


class BacktestRequest(_BacktestBase):
    strategy: str = "ema_crossover"
    params: dict | None = None
    use_ai_filter: bool = False
    source: str = "mt5"


class OptimizeRequest(_BacktestBase):
    strategy: str = "ema_crossover"
    param_grid: dict[str, list]
    min_trades: int = Field(10, ge=1, le=1000)


async def _load_sentiment(db: AsyncSession, from_date: str | None, to_date: str | None) -> list[dict]:
    """Load historical sentiment records from DB for the backtest date range."""
    query = select(NewsSentiment).order_by(NewsSentiment.created_at)
    if from_date:
        query = query.where(NewsSentiment.created_at >= datetime.fromisoformat(from_date))
    if to_date:
        query = query.where(NewsSentiment.created_at <= datetime.fromisoformat(to_date))
    result = await db.execute(query)
    records = result.scalars().all()
    return [
        {
            "created_at": r.created_at,
            "sentiment_label": r.sentiment_label,
            "sentiment_score": r.sentiment_score,
            "confidence": r.confidence,
        }
        for r in records
    ]


@router.post("/run", dependencies=[Depends(require_auth)])
async def run_backtest(req: BacktestRequest, db: AsyncSession = Depends(get_db)):
    df = await _load_data(req.symbol, req.source, req.timeframe, req.count, req.from_date, req.to_date)
    if df.empty:
        return {"error": "No OHLCV data available"}

    strategy = get_strategy(req.strategy, req.params)
    risk_manager = RiskManager(
        max_risk_per_trade=req.risk_per_trade,
        max_lot=req.max_lot,
    )

    sentiment_data = None
    if req.use_ai_filter:
        sentiment_data = await _load_sentiment(db, req.from_date, req.to_date)

    import asyncio
    engine = BacktestEngine(strategy, risk_manager, req.initial_balance)
    result = await asyncio.to_thread(engine.run, df, use_ai_filter=req.use_ai_filter, sentiment_data=sentiment_data)

    resp = result.to_dict()
    if req.use_ai_filter:
        resp["sentiment_records_used"] = len(sentiment_data) if sentiment_data else 0
    return resp


@router.post("/optimize", dependencies=[Depends(require_auth)])
async def run_optimization(req: OptimizeRequest):
    df = await _load_data(req.symbol, req.source, req.timeframe, req.count, req.from_date, req.to_date)
    if df.empty:
        return {"error": "No OHLCV data available"}

    import asyncio
    result = await asyncio.to_thread(
        grid_search,
        strategy_name=req.strategy,
        df=df,
        param_grid=req.param_grid,
        initial_balance=req.initial_balance,
        risk_per_trade=req.risk_per_trade,
        max_lot=req.max_lot,
        min_trades=req.min_trades,
    )
    return result.to_dict()


class WalkForwardRequest(_BacktestBase):
    strategy: str = "ema_crossover"
    param_grid: dict[str, list]
    n_splits: int = Field(5, ge=2, le=20)
    train_pct: float = Field(0.7, ge=0.5, le=0.9)
    count: int = Field(5000, ge=500, le=50000)


class MonteCarloRequest(_BacktestBase):
    strategy: str = "ema_crossover"
    params: dict | None = None
    n_simulations: int = Field(1000, ge=100, le=10000)
    count: int = Field(5000, ge=500, le=50000)


class CompareRequest(_BacktestBase):
    strategies: list[dict]  # [{"name": "ema_crossover", "params": {...}}, ...]


@router.post("/walk-forward", dependencies=[Depends(require_auth)])
async def run_walk_forward(req: WalkForwardRequest):
    df = await _load_data(req.symbol, req.source, req.timeframe, req.count, req.from_date, req.to_date)
    if df.empty:
        return {"error": "No OHLCV data available"}

    import asyncio
    result = await asyncio.to_thread(
        walk_forward_test,
        strategy_name=req.strategy,
        df=df,
        param_grid=req.param_grid,
        n_splits=req.n_splits,
        train_pct=req.train_pct,
        initial_balance=req.initial_balance,
        risk_per_trade=req.risk_per_trade,
        max_lot=req.max_lot,
    )
    return result.to_dict()


@router.post("/monte-carlo", dependencies=[Depends(require_auth)])
async def run_monte_carlo(req: MonteCarloRequest):
    df = await _load_data(req.symbol, req.source, req.timeframe, req.count, req.from_date, req.to_date)
    if df.empty:
        return {"error": "No OHLCV data available"}

    import asyncio

    def _run_mc():
        strategy = get_strategy(req.strategy, req.params)
        risk_manager = RiskManager(max_risk_per_trade=req.risk_per_trade, max_lot=req.max_lot)
        engine = BacktestEngine(strategy, risk_manager, req.initial_balance)
        bt_result = engine.run(df)
        trades = bt_result.to_dict().get("trades", [])
        profits = [t["profit"] for t in trades if "profit" in t]
        if not profits:
            return None
        return monte_carlo_analysis(profits, req.n_simulations, req.initial_balance)

    mc_result = await asyncio.to_thread(_run_mc)
    if mc_result is None:
        return {"error": "No trades produced by backtest"}
    return mc_result.to_dict()


@router.post("/compare", dependencies=[Depends(require_auth)])
async def run_comparison(req: CompareRequest):
    df = await _load_data(req.symbol, req.source, req.timeframe, req.count, req.from_date, req.to_date)
    if df.empty:
        return {"error": "No OHLCV data available"}

    import asyncio

    def _run_compare():
        results = []
        for config in req.strategies:
            name = config.get("name", "ema_crossover")
            params = config.get("params")
            strategy = get_strategy(name, params)
            risk_manager = RiskManager(max_risk_per_trade=req.risk_per_trade, max_lot=req.max_lot)
            engine = BacktestEngine(strategy, risk_manager, req.initial_balance)
            bt_result = engine.run(df)
            result_dict = bt_result.to_dict()
            result_dict["strategy_name"] = name
            result_dict["strategy_params"] = params or {}
            results.append(result_dict)
        return results

    results = await asyncio.to_thread(_run_compare)
    return {"comparison": results}


async def _load_data(symbol: str, source: str, timeframe: str, count: int, from_date: str | None, to_date: str | None):
    """Load OHLCV data from MT5 (live) or DB (historical)."""
    from app.config import resolve_broker_symbol
    actual_symbol = resolve_broker_symbol(symbol)
    if source == "db":
        if _collector is None:
            raise HTTPException(status_code=503, detail="Data collector not initialized")
        return await _collector.load_from_db(actual_symbol, timeframe, from_date, to_date)
    else:
        if _market_data is None:
            raise HTTPException(status_code=503, detail="Market data service not available")
        return await _market_data.get_ohlcv(actual_symbol, timeframe, count)


# ─── Statistical Validation Endpoints ────────────────────────────────────────


from fastapi import Query


@router.get("/cointegration", dependencies=[Depends(require_auth)])
async def run_cointegration_test(
    symbol_a: str = Query("GOLD"),
    symbol_b: str = Query("USDJPY"),
    timeframe: str = Query("M15"),
    count: int = Query(2000, ge=100, le=10000),
    source: str = Query("mt5"),
):
    """Test if two symbols are cointegrated (pair spread validity)."""
    from app.backtest.statistical_tests import cointegration_test

    df_a = await _load_data(symbol_a, source, timeframe, count, None, None)
    df_b = await _load_data(symbol_b, source, timeframe, count, None, None)

    if df_a.empty or df_b.empty:
        return {"error": "Insufficient data for one or both symbols"}

    import asyncio
    result = await asyncio.to_thread(cointegration_test, df_a["close"], df_b["close"])
    return {**result.to_dict(), "symbol_a": symbol_a, "symbol_b": symbol_b}


class PermutationTestRequest(BaseModel):
    strategy: str = "ema_crossover"
    params: dict | None = None
    symbol: str = "GOLD"
    timeframe: str = "M15"
    source: str = "mt5"
    count: int = Field(5000, ge=200)
    from_date: str | None = None
    to_date: str | None = None
    initial_balance: float = 10000.0
    n_permutations: int = Field(500, ge=50, le=2000)
    include_costs: bool = True


@router.post("/permutation-test", dependencies=[Depends(require_auth)])
async def run_permutation_test_endpoint(req: PermutationTestRequest):
    """Test if strategy signals are significantly better than random."""
    import asyncio

    from app.backtest.statistical_tests import permutation_test

    df = await _load_data(req.symbol, req.source, req.timeframe, req.count, req.from_date, req.to_date)
    if df.empty:
        return {"error": "No OHLCV data available"}

    strategy = get_strategy(req.strategy, req.params, symbol=req.symbol)
    risk_manager = RiskManager()

    # Run in thread to avoid blocking event loop (CPU-heavy)
    result = await asyncio.to_thread(
        permutation_test,
        df, strategy, risk_manager,
        initial_balance=req.initial_balance,
        n_permutations=req.n_permutations,
        include_costs=req.include_costs,
    )
    return {**result.to_dict(), "symbol": req.symbol, "strategy": req.strategy}


# ─── Composite Overfitting Score ────────────────────────────────────────────


class OverfittingScoreRequest(BaseModel):
    strategy: str = "ema_crossover"
    params: dict | None = None
    symbol: str = "GOLD"
    timeframe: str = "M15"
    source: str = "db"
    count: int = Field(5000, ge=500, le=50000)
    from_date: str | None = None
    to_date: str | None = None
    initial_balance: float = Field(10000.0, ge=100.0)
    risk_per_trade: float = Field(0.01, ge=0.001, le=0.10)
    max_lot: float = Field(1.0, ge=0.01, le=100.0)
    n_permutations: int = Field(200, ge=50, le=1000)
    n_simulations: int = Field(500, ge=100, le=5000)
    n_splits: int = Field(5, ge=2, le=10)
    train_pct: float = Field(0.7, ge=0.5, le=0.9)


@router.post("/overfitting-score", dependencies=[Depends(require_auth)])
async def compute_overfitting_score_endpoint(req: OverfittingScoreRequest):
    """Compute composite overfitting score (0-100%) for a strategy.

    Runs walk-forward, permutation test, and monte carlo concurrently,
    then combines into a single overfitting percentage with grade.
    """
    import asyncio

    from app.backtest.overfitting import auto_param_grid, compute_composite_score

    df = await _load_data(req.symbol, req.source, req.timeframe, req.count, req.from_date, req.to_date)
    if df.empty:
        return {"error": "No OHLCV data available"}

    risk_manager = RiskManager(max_risk_per_trade=req.risk_per_trade, max_lot=req.max_lot)
    param_grid = auto_param_grid(req.strategy)

    # ── Define sub-tasks ────────────────────────────────────────────────

    async def _run_walk_forward():
        if param_grid is None:
            return None
        try:
            return await asyncio.to_thread(
                walk_forward_test,
                strategy_name=req.strategy,
                df=df,
                param_grid=param_grid,
                n_splits=req.n_splits,
                train_pct=req.train_pct,
                initial_balance=req.initial_balance,
                risk_per_trade=req.risk_per_trade,
                max_lot=req.max_lot,
            )
        except Exception as e:
            logger.error(f"Walk-forward failed: {e}")
            return None

    async def _run_permutation():
        try:
            from app.backtest.statistical_tests import permutation_test

            strategy = get_strategy(req.strategy, req.params, symbol=req.symbol)
            return await asyncio.to_thread(
                permutation_test,
                df, strategy, risk_manager,
                initial_balance=req.initial_balance,
                n_permutations=req.n_permutations,
            )
        except Exception as e:
            logger.error(f"Permutation test failed: {e}")
            return None

    async def _run_monte_carlo():
        try:
            strategy = get_strategy(req.strategy, req.params, symbol=req.symbol)
            engine = BacktestEngine(strategy, risk_manager, req.initial_balance)
            bt_result = await asyncio.to_thread(engine.run, df)
            trades = bt_result.to_dict().get("trades", [])
            profits = [t["profit"] for t in trades if "profit" in t]
            if len(profits) < 5:
                return None
            return await asyncio.to_thread(
                monte_carlo_analysis, profits, req.n_simulations, req.initial_balance
            )
        except Exception as e:
            logger.error(f"Monte Carlo failed: {e}")
            return None

    # ── Run concurrently ────────────────────────────────────────────────

    wf_result, perm_result, mc_result = await asyncio.gather(
        _run_walk_forward(),
        _run_permutation(),
        _run_monte_carlo(),
    )

    result = compute_composite_score(wf_result, perm_result, mc_result)
    return {
        **result.to_dict(),
        "strategy": req.strategy,
        "symbol": req.symbol,
    }
