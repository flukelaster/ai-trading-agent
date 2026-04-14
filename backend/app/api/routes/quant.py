"""
Quant API — endpoints for quantitative analytics.
"""

from fastapi import APIRouter, Depends
from loguru import logger

from app.auth import require_auth

router = APIRouter(prefix="/api/quant", tags=["quant"], dependencies=[Depends(require_auth)])


@router.get("/var")
async def get_var():
    """Get current VaR/CVaR per symbol + portfolio."""
    try:

        from app.api.routes.bot import get_manager
        from app.risk.var import compute_var

        manager = get_manager()
        results = {}

        for sym, engine in manager.engines.items():
            try:
                df = await engine.market_data.get_ohlcv(sym, engine.timeframe, 200)
                if df is not None and len(df) > 20:
                    prices = df["close"].values
                    var_result = compute_var(prices, method="historical", window=60)
                    results[sym] = var_result.to_dict()
                else:
                    logger.debug(f"VaR skipped [{sym}]: OHLCV empty or too short ({len(df) if df is not None else 'None'})")
            except Exception as e:
                logger.warning(f"VaR calculation failed for {sym}: {e}")

        return {"symbols": results}
    except Exception as e:
        return {"error": str(e), "symbols": {}}


@router.get("/regime")
async def get_regime():
    """Get HMM regime state + transition probabilities per symbol."""
    try:
        from app.api.routes.bot import get_manager

        manager = get_manager()
        results = {}

        for sym, engine in manager.engines.items():
            regime = getattr(engine, "_last_regime", "normal")
            mtf = getattr(engine, "_multi_tf_regime", None)
            results[sym] = {
                "current": str(regime),
                "multi_tf": mtf.to_dict() if mtf else None,
            }

        return {"symbols": results}
    except Exception as e:
        return {"error": str(e), "symbols": {}}


@router.get("/correlation")
async def get_correlation():
    """Get rolling correlation matrix."""
    try:

        from app.api.routes.bot import get_manager
        from app.risk.correlation import compute_rolling_correlation

        manager = get_manager()
        price_series = {}

        for sym, engine in manager.engines.items():
            try:
                df = await engine.market_data.get_ohlcv(sym, engine.timeframe, 100)
                if df is not None and len(df) > 30:
                    price_series[sym] = df["close"].values
            except Exception:
                pass

        if len(price_series) >= 2:
            matrix = compute_rolling_correlation(price_series, window=30)
            return matrix.to_dict()

        return {"matrix": {}, "window": 30, "last_update": ""}
    except Exception as e:
        return {"error": str(e), "matrix": {}}


@router.get("/volatility")
async def get_volatility():
    """Get GARCH volatility forecast vs realized per symbol."""
    try:
        import numpy as np

        from app.api.routes.bot import get_manager
        from app.risk.garch import fit_garch

        manager = get_manager()
        results = {}

        for sym, engine in manager.engines.items():
            try:
                df = await engine.market_data.get_ohlcv(sym, engine.timeframe, 200)
                if df is not None and len(df) > 50:
                    prices = df["close"].values
                    garch = fit_garch(prices, window=200)

                    # Realized vol for comparison
                    returns = np.diff(np.log(prices[-61:]))
                    realized = returns.std() * np.sqrt(252) if len(returns) > 5 else 0

                    results[sym] = {
                        **garch.to_dict(),
                        "realized_vol": round(realized, 6),
                    }
            except Exception as e:
                logger.warning(f"GARCH failed for {sym}: {e}")

        return {"symbols": results}
    except Exception as e:
        return {"error": str(e), "symbols": {}}


@router.get("/portfolio")
async def get_portfolio():
    """Get optimal portfolio weights and risk contribution."""
    try:

        from app.api.routes.bot import get_manager
        from app.risk.portfolio_optimizer import max_sharpe, risk_parity

        manager = get_manager()
        price_series = {}

        for sym, engine in manager.engines.items():
            try:
                df = await engine.market_data.get_ohlcv(sym, engine.timeframe, 100)
                if df is not None and len(df) > 30:
                    price_series[sym] = df["close"].values
            except Exception:
                pass

        if len(price_series) < 2:
            return {"error": "Need at least 2 symbols", "allocations": {}}

        sharpe_alloc = max_sharpe(price_series)
        parity_alloc = risk_parity(price_series)

        return {
            "max_sharpe": sharpe_alloc.to_dict(),
            "risk_parity": parity_alloc.to_dict(),
        }
    except Exception as e:
        return {"error": str(e), "allocations": {}}


@router.get("/signals")
async def get_signals():
    """Get quant signals (z-score, Hurst, rolling Sharpe) per symbol."""
    try:
        from app.api.routes.bot import get_manager
        from app.strategy.quant_signals import compute_all_signals

        manager = get_manager()
        results = {}

        for sym, engine in manager.engines.items():
            try:
                df = await engine.market_data.get_ohlcv(sym, engine.timeframe, 200)
                if df is not None and len(df) > 30:
                    prices = df["close"].values
                    signals = compute_all_signals(prices)
                    results[sym] = signals.to_dict()
            except Exception as e:
                logger.warning(f"Quant signals failed for {sym}: {e}")

        return {"symbols": results}
    except Exception as e:
        return {"error": str(e), "symbols": {}}


@router.post("/stress-test")
async def run_stress_test_endpoint(scenario: str = "covid_crash"):
    """Run stress test on current portfolio."""
    try:
        from app.api.routes.bot import get_manager
        from app.backtest.stress_test import run_all_stress_tests, run_stress_test

        manager = get_manager()
        price_series = {}
        positions = {}

        for sym, engine in manager.engines.items():
            try:
                df = await engine.market_data.get_ohlcv(sym, engine.timeframe, 200)
                if df is not None and len(df) > 20:
                    price_series[sym] = df["close"].values
                    # Approximate exposure from account
                    positions[sym] = 1000  # placeholder — use actual exposure
            except Exception:
                pass

        if scenario == "all":
            results = run_all_stress_tests(positions, price_series)
            return {"results": [r.to_dict() for r in results]}
        else:
            result = run_stress_test(positions, price_series, scenario)
            return result.to_dict()
    except Exception as e:
        return {"error": str(e)}
