"""
Composite Overfitting Score — combines walk-forward, permutation test,
param stability, and monte carlo into a single 0-100% overfitting metric.
"""

from dataclasses import dataclass, field

import numpy as np
from loguru import logger

from app.backtest.monte_carlo import MonteCarloResult
from app.backtest.statistical_tests import PermutationTestResult
from app.backtest.walk_forward import WalkForwardResult

# ─── Default Weights ────────────────────────────────────────────────────────

DEFAULT_WEIGHTS = {
    "walk_forward": 0.40,
    "permutation": 0.25,
    "param_stability": 0.20,
    "monte_carlo": 0.15,
}

# ─── Grade Thresholds ───────────────────────────────────────────────────────

GRADE_HEALTHY = 30.0
GRADE_MODERATE = 60.0


@dataclass
class OverfittingScoreResult:
    overfitting_pct: float = 0.0
    grade: str = "healthy"
    components: dict = field(default_factory=dict)
    weights_used: dict = field(default_factory=dict)
    walk_forward: dict | None = None
    permutation: dict | None = None
    monte_carlo: dict | None = None
    partial: bool = False
    skipped_tests: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "overfitting_pct": round(self.overfitting_pct, 1),
            "grade": self.grade,
            "components": {k: round(v, 1) for k, v in self.components.items()},
            "weights_used": {k: round(v, 3) for k, v in self.weights_used.items()},
            "walk_forward": self.walk_forward,
            "permutation": self.permutation,
            "monte_carlo": self.monte_carlo,
            "partial": self.partial,
            "skipped_tests": self.skipped_tests,
        }


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def _classify_grade(pct: float) -> str:
    if pct < GRADE_HEALTHY:
        return "healthy"
    if pct < GRADE_MODERATE:
        return "moderate"
    return "overfit"


def _redistribute_weights(
    available: dict[str, float],
    base_weights: dict[str, float] | None = None,
) -> dict[str, float]:
    """Redistribute weights proportionally among available components."""
    weights = base_weights or DEFAULT_WEIGHTS
    total = sum(weights[k] for k in available)
    if total <= 0:
        return {k: 1.0 / len(available) for k in available}
    return {k: weights[k] / total for k in available}


def compute_composite_score(
    wf_result: WalkForwardResult | None = None,
    perm_result: PermutationTestResult | None = None,
    mc_result: MonteCarloResult | None = None,
) -> OverfittingScoreResult:
    """Combine multiple overfitting metrics into a single 0-100% score.

    Args:
        wf_result: Walk-forward test result (provides overfitting_ratio + param_stability)
        perm_result: Permutation test result (provides p_value)
        mc_result: Monte Carlo result (provides probability_of_ruin)

    Returns:
        OverfittingScoreResult with composite percentage and breakdown.
    """
    components: dict[str, float] = {}
    summaries: dict[str, dict | None] = {
        "walk_forward": None,
        "permutation": None,
        "monte_carlo": None,
    }
    skipped: list[str] = []

    # ── Walk-Forward component ──────────────────────────────────────────
    if wf_result and wf_result.n_splits > 0 and wf_result.in_sample_avg_sharpe > 0:
        # overfitting_ratio = OOS Sharpe / IS Sharpe; 1.0 = perfect, 0.0 = total overfit
        wf_score = _clamp((1.0 - wf_result.overfitting_ratio) * 100)
        components["walk_forward"] = wf_score

        # Param stability (CV): 0 = stable, 1+ = unstable
        if wf_result.param_stability_score is not None:
            stab_score = _clamp(wf_result.param_stability_score * 100)
            components["param_stability"] = stab_score

        summaries["walk_forward"] = {
            "overfitting_ratio": round(wf_result.overfitting_ratio, 4),
            "likely_overfit": wf_result.likely_overfit,
            "is_sharpe": round(wf_result.in_sample_avg_sharpe, 4),
            "oos_sharpe": round(wf_result.aggregate_oos_sharpe, 4),
            "oos_sharpe_ci": (
                [round(wf_result.oos_sharpe_ci[0], 4), round(wf_result.oos_sharpe_ci[1], 4)]
                if wf_result.oos_sharpe_ci else None
            ),
            "param_stability_score": (
                round(wf_result.param_stability_score, 4)
                if wf_result.param_stability_score is not None else None
            ),
            "param_stability_detail": (
                {k: round(v, 4) for k, v in wf_result.param_stability_detail.items()}
                if wf_result.param_stability_detail else None
            ),
        }
    else:
        skipped.append("walk_forward")
        if not (wf_result and wf_result.param_stability_score is not None):
            skipped.append("param_stability")

    # ── Permutation component ───────────────────────────────────────────
    if perm_result and perm_result.n_permutations > 0:
        # High p-value → strategy does NOT beat random → overfit signal
        perm_score = _clamp(perm_result.p_value * 200)
        components["permutation"] = perm_score

        summaries["permutation"] = {
            "real_sharpe": round(perm_result.real_sharpe, 4),
            "p_value": round(perm_result.p_value, 4),
            "is_significant": perm_result.is_significant,
            "shuffled_mean": round(perm_result.shuffled_mean, 4),
        }
    else:
        skipped.append("permutation")

    # ── Monte Carlo component ───────────────────────────────────────────
    if mc_result and mc_result.n_simulations > 0:
        mc_score = _clamp(mc_result.probability_of_ruin * 200)
        components["monte_carlo"] = mc_score

        summaries["monte_carlo"] = {
            "probability_of_ruin": round(mc_result.probability_of_ruin, 4),
            "probability_of_profit": round(mc_result.probability_of_profit, 4),
            "p95_max_drawdown": round(mc_result.p95_max_drawdown, 4),
            "median_final_balance": round(mc_result.median_final_balance, 2),
        }
    else:
        skipped.append("monte_carlo")

    # ── Compute weighted composite ──────────────────────────────────────
    if not components:
        logger.warning("Overfitting score: no components available")
        return OverfittingScoreResult(
            overfitting_pct=0.0,
            grade="unknown",
            partial=True,
            skipped_tests=skipped,
        )

    weights = _redistribute_weights(components)
    composite = sum(components[k] * weights[k] for k in components)
    composite = _clamp(composite)

    logger.info(
        f"Overfitting score: {composite:.1f}% ({_classify_grade(composite)}) "
        f"components={list(components.keys())}"
    )

    return OverfittingScoreResult(
        overfitting_pct=composite,
        grade=_classify_grade(composite),
        components=components,
        weights_used=weights,
        walk_forward=summaries["walk_forward"],
        permutation=summaries["permutation"],
        monte_carlo=summaries["monte_carlo"],
        partial=len(skipped) > 0,
        skipped_tests=skipped,
    )


# ─── Auto param_grid generation ──────────────────────────────────────────────

# Param ranges per strategy — mirrors mcp_server/tools/strategy_gen.STRATEGY_PROFILES
# but avoids importing app.config (which triggers Settings validation in tests).
_PARAM_RANGES: dict[str, dict[str, tuple]] = {
    "ema_crossover": {"fast_period": (5, 50), "slow_period": (20, 200)},
    "rsi_filter": {"period": (7, 28), "overbought": (65, 85), "oversold": (15, 35)},
    "breakout": {"lookback": (10, 50)},
    "mean_reversion": {"bb_period": (10, 30), "bb_std": (1.5, 3.0), "min_bandwidth": (0.005, 0.03)},
    "ml_signal": {"confidence_threshold": (0.5, 0.9)},
    # ensemble, dca, grid, etc. have no tunable numeric params for grid search
}


def auto_param_grid(strategy_name: str, n_values: int = 5) -> dict[str, list] | None:
    """Generate a param_grid from known strategy param ranges.

    Returns None if the strategy has no param_ranges (e.g., ensemble).
    """
    ranges = _PARAM_RANGES.get(strategy_name)
    if not ranges:
        return None

    grid: dict[str, list] = {}
    for param, (lo, hi) in ranges.items():
        if isinstance(lo, int) and isinstance(hi, int):
            values = np.linspace(lo, hi, n_values)
            grid[param] = sorted(set(int(round(v)) for v in values))
        else:
            values = np.linspace(float(lo), float(hi), n_values)
            grid[param] = [round(float(v), 4) for v in values]

    return grid if grid else None
