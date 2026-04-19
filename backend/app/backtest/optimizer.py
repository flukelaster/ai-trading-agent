"""
Parameter Optimizer — grid search over strategy parameters using BacktestEngine.
"""

import itertools
from dataclasses import dataclass, field

import pandas as pd
from loguru import logger

from app.backtest.engine import BacktestEngine, BacktestResult
from app.risk.manager import RiskManager
from app.strategy import get_strategy

MAX_COMBINATIONS = 500


@dataclass
class OptimizationResult:
    best_params: dict = field(default_factory=dict)
    best_score: float = 0.0
    best_metrics: dict = field(default_factory=dict)
    all_results: list[dict] = field(default_factory=list)
    total_combinations: int = 0
    tested_combinations: int = 0

    def to_dict(self) -> dict:
        return {
            "best_params": self.best_params,
            "best_score": round(self.best_score, 4),
            "best_metrics": self.best_metrics,
            "total_combinations": self.total_combinations,
            "tested_combinations": self.tested_combinations,
            "top_10": self.all_results[:10],
        }


def generate_combinations(param_grid: dict[str, list]) -> list[dict]:
    """Generate cartesian product of parameter grid."""
    keys = list(param_grid.keys())
    values = list(param_grid.values())
    return [dict(zip(keys, combo, strict=False)) for combo in itertools.product(*values)]


def score_result(result: BacktestResult, min_trades: int = 10) -> float:
    """Composite score: sharpe × profit_factor, with minimum trade filter."""
    if result.total_trades < min_trades:
        return -999.0
    if result.profit_factor <= 0:
        return -999.0
    pf = min(result.profit_factor, 10.0)  # Cap to avoid inf
    return result.sharpe_ratio * pf * result.win_rate


def grid_search(
    strategy_name: str,
    df: pd.DataFrame,
    param_grid: dict[str, list],
    initial_balance: float = 10000.0,
    risk_per_trade: float = 0.01,
    max_lot: float = 1.0,
    min_trades: int = 10,
) -> OptimizationResult:
    """Run backtest for each parameter combination and return ranked results."""
    combinations = generate_combinations(param_grid)
    total = len(combinations)

    if total > MAX_COMBINATIONS:
        logger.warning(f"Grid search: {total} combos exceeds max {MAX_COMBINATIONS}, truncating")
        combinations = combinations[:MAX_COMBINATIONS]

    risk_manager = RiskManager(max_risk_per_trade=risk_per_trade, max_lot=max_lot)
    results = []

    for i, params in enumerate(combinations):
        try:
            strategy = get_strategy(strategy_name, params)
            engine = BacktestEngine(strategy, risk_manager, initial_balance)
            bt_result = engine.run(df)

            s = score_result(bt_result, min_trades)
            results.append(
                {
                    "params": params,
                    "score": round(s, 4),
                    "total_trades": bt_result.total_trades,
                    "win_rate": round(bt_result.win_rate, 4),
                    "total_profit": round(bt_result.total_profit, 2),
                    "max_drawdown": round(bt_result.max_drawdown, 4),
                    "sharpe_ratio": round(bt_result.sharpe_ratio, 4),
                    "profit_factor": round(min(bt_result.profit_factor, 99.0), 4),
                }
            )
        except Exception as e:
            logger.warning(f"Grid search combo {i + 1}/{len(combinations)} failed: {e}")
            continue

    results.sort(key=lambda x: x["score"], reverse=True)

    best = results[0] if results else {}
    return OptimizationResult(
        best_params=best.get("params", {}),
        best_score=best.get("score", 0.0),
        best_metrics={k: v for k, v in best.items() if k != "params"} if best else {},
        all_results=results,
        total_combinations=total,
        tested_combinations=len(results),
    )
