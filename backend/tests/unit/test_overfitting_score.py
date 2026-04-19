"""
Unit tests for composite overfitting score — backend/app/backtest/overfitting.py.
"""

import pytest

from app.backtest.monte_carlo import MonteCarloResult
from app.backtest.overfitting import (
    _clamp,
    _classify_grade,
    _redistribute_weights,
    auto_param_grid,
    compute_composite_score,
)
from app.backtest.statistical_tests import PermutationTestResult
from app.backtest.walk_forward import WalkForwardResult

# ─── Helper builders ────────────────────────────────────────────────────────


def _make_wf(
    overfitting_ratio: float = 0.8,
    is_sharpe: float = 1.5,
    oos_sharpe: float = 1.2,
    param_stability_score: float | None = 0.3,
    n_splits: int = 5,
) -> WalkForwardResult:
    return WalkForwardResult(
        n_splits=n_splits,
        in_sample_avg_sharpe=is_sharpe,
        aggregate_oos_sharpe=oos_sharpe,
        overfitting_ratio=overfitting_ratio,
        likely_overfit=overfitting_ratio < 0.5,
        param_stability_score=param_stability_score,
        param_stability_detail={"fast_period": 0.2, "slow_period": 0.4} if param_stability_score else {},
        oos_sharpe_ci=(0.8, 1.6) if n_splits >= 3 else None,
    )


def _make_perm(
    p_value: float = 0.02,
    real_sharpe: float = 1.2,
    is_significant: bool = True,
) -> PermutationTestResult:
    return PermutationTestResult(
        real_sharpe=real_sharpe,
        shuffled_mean=0.1,
        shuffled_std=0.3,
        p_value=p_value,
        is_significant=is_significant,
        n_permutations=200,
        significance=0.05,
    )


def _make_mc(
    ruin_prob: float = 0.05,
    profit_prob: float = 0.85,
) -> MonteCarloResult:
    return MonteCarloResult(
        n_simulations=500,
        initial_balance=10000.0,
        median_final_balance=11500.0,
        mean_final_balance=11800.0,
        p5_final_balance=8000.0,
        p95_final_balance=15000.0,
        median_max_drawdown=0.08,
        p95_max_drawdown=0.15,
        probability_of_ruin=ruin_prob,
        probability_of_profit=profit_prob,
    )


# ─── _clamp ─────────────────────────────────────────────────────────────────


class TestClamp:
    def test_within_range(self):
        assert _clamp(50.0) == 50.0

    def test_below_min(self):
        assert _clamp(-10.0) == 0.0

    def test_above_max(self):
        assert _clamp(150.0) == 100.0

    def test_at_boundaries(self):
        assert _clamp(0.0) == 0.0
        assert _clamp(100.0) == 100.0


# ─── _classify_grade ────────────────────────────────────────────────────────


class TestClassifyGrade:
    def test_healthy(self):
        assert _classify_grade(0.0) == "healthy"
        assert _classify_grade(29.9) == "healthy"

    def test_moderate(self):
        assert _classify_grade(30.0) == "moderate"
        assert _classify_grade(59.9) == "moderate"

    def test_overfit(self):
        assert _classify_grade(60.0) == "overfit"
        assert _classify_grade(100.0) == "overfit"


# ─── _redistribute_weights ──────────────────────────────────────────────────


class TestRedistributeWeights:
    def test_all_components(self):
        available = {"walk_forward": 10, "permutation": 5, "param_stability": 3, "monte_carlo": 2}
        weights = _redistribute_weights(available)
        assert abs(sum(weights.values()) - 1.0) < 1e-9

    def test_two_components(self):
        available = {"permutation": 5, "monte_carlo": 2}
        weights = _redistribute_weights(available)
        assert abs(sum(weights.values()) - 1.0) < 1e-9
        # permutation weight should be > monte_carlo weight
        assert weights["permutation"] > weights["monte_carlo"]

    def test_single_component(self):
        available = {"permutation": 5}
        weights = _redistribute_weights(available)
        assert weights["permutation"] == pytest.approx(1.0)


# ─── compute_composite_score ────────────────────────────────────────────────


class TestCompositeScore:
    def test_all_components_healthy(self):
        """Good WF ratio + significant perm + low ruin = healthy."""
        result = compute_composite_score(
            wf_result=_make_wf(overfitting_ratio=0.9, param_stability_score=0.1),
            perm_result=_make_perm(p_value=0.01),
            mc_result=_make_mc(ruin_prob=0.02),
        )
        assert result.grade == "healthy"
        assert result.overfitting_pct < 30.0
        assert not result.partial
        assert len(result.skipped_tests) == 0
        assert "walk_forward" in result.components
        assert "permutation" in result.components
        assert "param_stability" in result.components
        assert "monte_carlo" in result.components

    def test_all_components_overfit(self):
        """Bad WF ratio + not significant + high ruin = overfit."""
        result = compute_composite_score(
            wf_result=_make_wf(overfitting_ratio=0.1, param_stability_score=0.9),
            perm_result=_make_perm(p_value=0.6, is_significant=False),
            mc_result=_make_mc(ruin_prob=0.6),
        )
        assert result.grade == "overfit"
        assert result.overfitting_pct >= 60.0

    def test_moderate_score(self):
        """Mixed signals → moderate."""
        result = compute_composite_score(
            wf_result=_make_wf(overfitting_ratio=0.5, param_stability_score=0.4),
            perm_result=_make_perm(p_value=0.04),
            mc_result=_make_mc(ruin_prob=0.3),
        )
        assert result.grade == "moderate"
        assert 30.0 <= result.overfitting_pct < 60.0

    def test_missing_wf_result(self):
        """Without WF, weights redistribute to remaining components."""
        result = compute_composite_score(
            wf_result=None,
            perm_result=_make_perm(p_value=0.01),
            mc_result=_make_mc(ruin_prob=0.02),
        )
        assert result.partial
        assert "walk_forward" in result.skipped_tests
        assert "param_stability" in result.skipped_tests
        assert "walk_forward" not in result.components
        # Should still produce a score
        assert result.overfitting_pct >= 0.0

    def test_missing_perm_result(self):
        result = compute_composite_score(
            wf_result=_make_wf(),
            perm_result=None,
            mc_result=_make_mc(),
        )
        assert result.partial
        assert "permutation" in result.skipped_tests
        assert "permutation" not in result.components

    def test_missing_mc_result(self):
        result = compute_composite_score(
            wf_result=_make_wf(),
            perm_result=_make_perm(),
            mc_result=None,
        )
        assert result.partial
        assert "monte_carlo" in result.skipped_tests

    def test_all_missing(self):
        result = compute_composite_score(None, None, None)
        assert result.grade == "unknown"
        assert result.partial
        assert result.overfitting_pct == 0.0

    def test_wf_zero_is_sharpe_skipped(self):
        """WF with zero IS Sharpe should be skipped."""
        result = compute_composite_score(
            wf_result=_make_wf(is_sharpe=0.0, overfitting_ratio=0.0),
            perm_result=_make_perm(),
            mc_result=_make_mc(),
        )
        assert "walk_forward" in result.skipped_tests

    def test_wf_no_param_stability(self):
        """WF present but no param_stability_score → param_stability skipped."""
        result = compute_composite_score(
            wf_result=_make_wf(param_stability_score=None),
            perm_result=_make_perm(),
            mc_result=_make_mc(),
        )
        assert "walk_forward" in result.components
        assert "param_stability" not in result.components

    def test_to_dict(self):
        result = compute_composite_score(
            wf_result=_make_wf(),
            perm_result=_make_perm(),
            mc_result=_make_mc(),
        )
        d = result.to_dict()
        assert "overfitting_pct" in d
        assert "grade" in d
        assert "components" in d
        assert "weights_used" in d
        assert isinstance(d["components"], dict)

    def test_score_clamped_0_to_100(self):
        """Even with extreme inputs, score stays in 0-100."""
        result = compute_composite_score(
            wf_result=_make_wf(overfitting_ratio=-1.0, param_stability_score=5.0),
            perm_result=_make_perm(p_value=1.0),
            mc_result=_make_mc(ruin_prob=1.0),
        )
        assert 0.0 <= result.overfitting_pct <= 100.0


# ─── auto_param_grid ────────────────────────────────────────────────────────


class TestAutoParamGrid:
    def test_ema_crossover(self):
        grid = auto_param_grid("ema_crossover")
        assert grid is not None
        assert "fast_period" in grid
        assert "slow_period" in grid
        assert len(grid["fast_period"]) >= 3
        # Values should be integers for int ranges
        assert all(isinstance(v, int) for v in grid["fast_period"])

    def test_mean_reversion_float_params(self):
        grid = auto_param_grid("mean_reversion")
        assert grid is not None
        assert "bb_std" in grid
        # bb_std range is (1.5, 3.0) — should be floats
        assert all(isinstance(v, float) for v in grid["bb_std"])

    def test_unknown_strategy_returns_none(self):
        grid = auto_param_grid("nonexistent_strategy")
        assert grid is None

    def test_ensemble_returns_none(self):
        """Ensemble has no param_ranges, should return None."""
        grid = auto_param_grid("ensemble")
        assert grid is None

    def test_breakout(self):
        grid = auto_param_grid("breakout")
        assert grid is not None
        assert "lookback" in grid
