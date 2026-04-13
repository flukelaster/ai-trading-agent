"""
Statistical Tests — validate trading edges with math, not intuition.

- Cointegration (ADF): prove pair spread relationship is real
- Permutation Test: prove strategy beats random
"""

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from loguru import logger


# ─── Cointegration Test ──────────────────────────────────────────────────────


@dataclass
class CointegrationResult:
    test_statistic: float
    p_value: float
    is_cointegrated: bool
    critical_values: dict[str, float]
    hedge_ratio: float
    n_observations: int
    significance: float

    def to_dict(self) -> dict:
        return {
            "test_statistic": round(self.test_statistic, 4),
            "p_value": round(self.p_value, 4),
            "is_cointegrated": self.is_cointegrated,
            "critical_values": {k: round(v, 4) for k, v in self.critical_values.items()},
            "hedge_ratio": round(self.hedge_ratio, 4),
            "n_observations": self.n_observations,
            "significance": self.significance,
            "verdict": "Cointegrated — pair spread is valid" if self.is_cointegrated
                       else "NOT cointegrated — pair spread may not work",
        }


def cointegration_test(
    series_a: pd.Series,
    series_b: pd.Series,
    significance: float = 0.05,
) -> CointegrationResult:
    """
    Run Augmented Dickey-Fuller test on OLS residuals of two price series.
    If p_value < significance → the pair is cointegrated (spread is mean-reverting).
    """
    from statsmodels.tsa.stattools import adfuller

    # Align lengths
    n = min(len(series_a), len(series_b))
    a = series_a.values[-n:].astype(float)
    b = series_b.values[-n:].astype(float)

    # OLS hedge ratio: a = beta * b + residual
    X = np.column_stack([b, np.ones(len(b))])
    coeffs = np.linalg.lstsq(X, a, rcond=None)[0]
    beta = coeffs[0]

    # Spread = residuals
    spread = a - beta * b

    # ADF test on spread
    result = adfuller(spread, autolag="AIC")

    return CointegrationResult(
        test_statistic=float(result[0]),
        p_value=float(result[1]),
        is_cointegrated=result[1] < significance,
        critical_values={k: float(v) for k, v in result[4].items()},
        hedge_ratio=float(beta),
        n_observations=int(result[3]),
        significance=significance,
    )


# ─── Permutation Test ────────────────────────────────────────────────────────


@dataclass
class PermutationTestResult:
    real_sharpe: float
    shuffled_mean: float
    shuffled_std: float
    p_value: float
    is_significant: bool
    n_permutations: int
    significance: float

    def to_dict(self) -> dict:
        return {
            "real_sharpe": round(self.real_sharpe, 4),
            "shuffled_mean": round(self.shuffled_mean, 4),
            "shuffled_std": round(self.shuffled_std, 4),
            "p_value": round(self.p_value, 4),
            "is_significant": self.is_significant,
            "n_permutations": self.n_permutations,
            "significance": self.significance,
            "verdict": "Significant — strategy has edge over random" if self.is_significant
                       else "NOT significant — strategy may not beat random",
        }


def permutation_test(
    df: pd.DataFrame,
    strategy,
    risk_manager,
    initial_balance: float = 10000.0,
    n_permutations: int = 500,
    significance: float = 0.05,
    include_costs: bool = True,
    seed: int = 42,
) -> PermutationTestResult:
    """
    Shuffle signals N times, re-run backtest each time.
    p_value = fraction of shuffled runs with Sharpe >= real Sharpe.
    If p < 0.05 → strategy is significantly better than random.
    """
    from app.backtest.engine import BacktestEngine

    # Run real backtest
    engine = BacktestEngine(strategy, risk_manager, initial_balance, include_costs=include_costs)
    real_result = engine.run(df)
    real_sharpe = real_result.sharpe_ratio

    # Get signal column from calculated df
    calc_df = strategy.calculate(df.copy())
    original_signals = calc_df["signal"].values.copy()

    rng = np.random.default_rng(seed)
    beat_count = 0
    shuffled_sharpes = []

    for _ in range(n_permutations):
        shuffled = rng.permutation(original_signals)
        shuffled_series = pd.Series(shuffled, index=calc_df.index)

        engine_perm = BacktestEngine(strategy, risk_manager, initial_balance, include_costs=include_costs)
        perm_result = engine_perm.run(df, signals_override=shuffled_series)

        s = perm_result.sharpe_ratio
        shuffled_sharpes.append(s)
        if s >= real_sharpe:
            beat_count += 1

    p_value = beat_count / n_permutations
    arr = np.array(shuffled_sharpes)

    return PermutationTestResult(
        real_sharpe=real_sharpe,
        shuffled_mean=float(arr.mean()),
        shuffled_std=float(arr.std()),
        p_value=p_value,
        is_significant=p_value < significance,
        n_permutations=n_permutations,
        significance=significance,
    )
