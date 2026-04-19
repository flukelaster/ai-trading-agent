"""
Walk-Forward Optimization — train on past, validate on future, repeat.
Detects overfitting by comparing in-sample vs out-of-sample performance.
"""

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from loguru import logger

from app.backtest.engine import BacktestEngine
from app.backtest.optimizer import grid_search
from app.risk.manager import RiskManager
from app.strategy import get_strategy


@dataclass
class WalkForwardResult:
    n_splits: int
    windows: list[dict] = field(default_factory=list)
    aggregate_oos_sharpe: float = 0.0
    aggregate_oos_profit_factor: float = 0.0
    aggregate_oos_win_rate: float = 0.0
    aggregate_oos_total_trades: int = 0
    in_sample_avg_sharpe: float = 0.0
    overfitting_ratio: float = 0.0  # OOS sharpe / IS sharpe
    likely_overfit: bool = False
    best_params_stability: list[dict] = field(default_factory=list)
    oos_sharpe_ci: tuple[float, float] | None = None  # 95% bootstrap CI
    param_stability_score: float | None = None  # avg coefficient of variation (lower=better)
    param_stability_detail: dict = field(default_factory=dict)  # per-param CV

    def to_dict(self) -> dict:
        d = {
            "n_splits": self.n_splits,
            "windows": self.windows,
            "aggregate_oos_sharpe": round(self.aggregate_oos_sharpe, 4),
            "aggregate_oos_profit_factor": round(self.aggregate_oos_profit_factor, 4),
            "aggregate_oos_win_rate": round(self.aggregate_oos_win_rate, 4),
            "aggregate_oos_total_trades": self.aggregate_oos_total_trades,
            "in_sample_avg_sharpe": round(self.in_sample_avg_sharpe, 4),
            "overfitting_ratio": round(self.overfitting_ratio, 4),
            "likely_overfit": self.likely_overfit,
            "best_params_stability": self.best_params_stability,
        }
        if self.oos_sharpe_ci is not None:
            d["oos_sharpe_ci"] = [round(self.oos_sharpe_ci[0], 4), round(self.oos_sharpe_ci[1], 4)]
        if self.param_stability_score is not None:
            d["param_stability_score"] = round(self.param_stability_score, 4)
            d["param_stability_detail"] = {k: round(v, 4) for k, v in self.param_stability_detail.items()}
        return d


def bootstrap_ci(values: list[float], n_bootstrap: int = 1000, ci: float = 0.95) -> tuple[float, float]:
    """Compute bootstrap confidence interval for the mean of values."""
    arr = np.array(values)
    rng = np.random.default_rng(42)
    means = [rng.choice(arr, size=len(arr), replace=True).mean() for _ in range(n_bootstrap)]
    lower = np.percentile(means, (1 - ci) / 2 * 100)
    upper = np.percentile(means, (1 + ci) / 2 * 100)
    return float(lower), float(upper)


def compute_param_stability(params_list: list[dict]) -> tuple[float, dict[str, float]]:
    """Compute coefficient of variation per parameter across walk-forward windows.
    Returns (avg_cv, {param: cv}). Lower CV = more stable = less overfit."""
    if len(params_list) < 2:
        return 0.0, {}

    all_keys = set()
    for p in params_list:
        all_keys.update(p.keys())

    cvs = {}
    for key in all_keys:
        values = [p[key] for p in params_list if key in p and isinstance(p[key], int | float)]
        if len(values) < 2:
            continue
        arr = np.array(values, dtype=float)
        mean = arr.mean()
        if mean == 0:
            cvs[key] = 0.0
        else:
            cvs[key] = float(arr.std() / abs(mean))

    avg_cv = sum(cvs.values()) / len(cvs) if cvs else 0.0
    return avg_cv, cvs


def walk_forward_test(
    strategy_name: str,
    df: pd.DataFrame,
    param_grid: dict[str, list],
    n_splits: int = 5,
    train_pct: float = 0.7,
    initial_balance: float = 10000.0,
    risk_per_trade: float = 0.01,
    max_lot: float = 1.0,
    min_trades: int = 5,
    anchored: bool = True,
) -> WalkForwardResult:
    """
    Walk-forward optimization with expanding (anchored) or sliding windows.

    Args:
        anchored: If True, training always starts from bar 0 (expanding window).
                  If False, sliding window of fixed size.
    """
    total_bars = len(df)
    if total_bars < 200:
        logger.warning(f"Walk-forward: insufficient data ({total_bars} bars)")
        return WalkForwardResult(n_splits=0)

    result = WalkForwardResult(n_splits=n_splits)
    split_size = total_bars // n_splits

    oos_sharpes = []
    is_sharpes = []
    oos_total_trades = 0
    oos_total_profit = 0.0
    oos_total_wins = 0

    for i in range(n_splits):
        # Define train/test boundaries
        if anchored:
            train_start = 0
        else:
            train_start = i * split_size
        split_end = (i + 1) * split_size if i < n_splits - 1 else total_bars
        train_end = train_start + int((split_end - train_start) * train_pct)
        test_start = train_end
        test_end = split_end

        if test_end - test_start < 50:
            continue  # skip tiny test windows

        train_df = df.iloc[train_start:train_end]
        test_df = df.iloc[test_start:test_end]

        # Optimize on training data
        opt_result = grid_search(
            strategy_name=strategy_name,
            df=train_df,
            param_grid=param_grid,
            initial_balance=initial_balance,
            risk_per_trade=risk_per_trade,
            max_lot=max_lot,
            min_trades=min_trades,
        )

        if not opt_result.results:
            continue

        best = opt_result.results[0]
        best_params = best["params"]
        is_sharpe = best.get("sharpe_ratio", 0)
        is_sharpes.append(is_sharpe)

        # Validate on test data with best params
        strategy = get_strategy(strategy_name, best_params)
        risk_manager = RiskManager(max_risk_per_trade=risk_per_trade, max_lot=max_lot)
        engine = BacktestEngine(strategy, risk_manager, initial_balance)
        oos_result = engine.run(test_df)

        oos_dict = oos_result.to_dict()
        oos_sharpe = oos_dict.get("sharpe_ratio", 0)
        oos_sharpes.append(oos_sharpe)
        oos_total_trades += oos_dict.get("total_trades", 0)
        oos_total_profit += oos_dict.get("total_profit", 0)
        oos_total_wins += int(oos_dict.get("win_rate", 0) * oos_dict.get("total_trades", 0))

        window = {
            "split": i + 1,
            "train_bars": train_end - train_start,
            "test_bars": test_end - test_start,
            "best_params": best_params,
            "in_sample_sharpe": round(is_sharpe, 4),
            "oos_sharpe": round(oos_sharpe, 4),
            "oos_win_rate": round(oos_dict.get("win_rate", 0), 4),
            "oos_profit_factor": round(oos_dict.get("profit_factor", 0), 4),
            "oos_total_trades": oos_dict.get("total_trades", 0),
            "oos_total_profit": round(oos_dict.get("total_profit", 0), 2),
        }
        result.windows.append(window)
        result.best_params_stability.append(best_params)

    # Aggregate metrics
    if oos_sharpes:
        result.aggregate_oos_sharpe = sum(oos_sharpes) / len(oos_sharpes)
        result.aggregate_oos_total_trades = oos_total_trades
        result.aggregate_oos_win_rate = oos_total_wins / oos_total_trades if oos_total_trades > 0 else 0
    if is_sharpes:
        result.in_sample_avg_sharpe = sum(is_sharpes) / len(is_sharpes)
        if result.in_sample_avg_sharpe > 0:
            result.overfitting_ratio = result.aggregate_oos_sharpe / result.in_sample_avg_sharpe
        result.likely_overfit = result.overfitting_ratio < 0.5 and result.in_sample_avg_sharpe > 0

    # Bootstrap 95% CI on OOS Sharpe
    if len(oos_sharpes) >= 3:
        result.oos_sharpe_ci = bootstrap_ci(oos_sharpes)

    # Parameter stability score
    if len(result.best_params_stability) >= 2:
        result.param_stability_score, result.param_stability_detail = compute_param_stability(
            result.best_params_stability
        )

    return result
