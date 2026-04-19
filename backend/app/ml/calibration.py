"""
ML Probability Calibration — ensure predicted confidence matches actual win rate.

Provides:
- Platt scaling (logistic regression on predicted probabilities)
- Isotonic regression calibration
- Reliability diagram data (for frontend visualization)
- Brier score tracking
"""

from dataclasses import dataclass

import numpy as np
from loguru import logger


@dataclass
class CalibrationResult:
    """Result of calibration analysis."""

    brier_score: float  # 0 = perfect, 1 = worst
    brier_score_calibrated: float  # after calibration
    reliability_bins: list[dict]  # [{predicted, actual, count}] for diagram
    calibration_method: str  # "platt" or "isotonic"
    improvement_pct: float  # % improvement from calibration

    def to_dict(self) -> dict:
        return {
            "brier_score": round(self.brier_score, 4),
            "brier_score_calibrated": round(self.brier_score_calibrated, 4),
            "reliability_bins": self.reliability_bins,
            "calibration_method": self.calibration_method,
            "improvement_pct": round(self.improvement_pct, 2),
        }


def brier_score(predicted: np.ndarray, actual: np.ndarray) -> float:
    """Compute Brier score: mean squared error of probability predictions."""
    if len(predicted) == 0:
        return 1.0
    return float(np.mean((predicted - actual) ** 2))


def reliability_diagram(
    predicted: np.ndarray,
    actual: np.ndarray,
    n_bins: int = 10,
) -> list[dict]:
    """Compute reliability diagram data.

    Returns:
        List of {predicted_mean, actual_mean, count} per bin
    """
    bins = np.linspace(0, 1, n_bins + 1)
    result = []

    for i in range(n_bins):
        mask = (predicted >= bins[i]) & (predicted < bins[i + 1])
        if mask.sum() > 0:
            result.append(
                {
                    "predicted": round(float(predicted[mask].mean()), 3),
                    "actual": round(float(actual[mask].mean()), 3),
                    "count": int(mask.sum()),
                }
            )

    return result


def platt_scaling(
    predicted: np.ndarray,
    actual: np.ndarray,
) -> tuple[callable, float]:
    """Platt scaling — fit logistic regression on predicted probs.

    Returns:
        (calibration_function, calibrated_brier_score)
    """
    if len(predicted) < 10:
        return lambda x: x, brier_score(predicted, actual)

    try:
        from sklearn.linear_model import LogisticRegression

        # Reshape for sklearn
        X = predicted.reshape(-1, 1)
        y = actual.astype(int)

        lr = LogisticRegression(C=1.0, solver="lbfgs")
        lr.fit(X, y)

        def calibrate(probs):
            return lr.predict_proba(np.asarray(probs).reshape(-1, 1))[:, 1]

        calibrated = calibrate(predicted)
        cal_brier = brier_score(calibrated, actual)

        return calibrate, cal_brier

    except Exception as e:
        logger.warning(f"Platt scaling failed: {e}")
        return lambda x: x, brier_score(predicted, actual)


def isotonic_calibration(
    predicted: np.ndarray,
    actual: np.ndarray,
) -> tuple[callable, float]:
    """Isotonic regression calibration — non-parametric.

    Returns:
        (calibration_function, calibrated_brier_score)
    """
    if len(predicted) < 10:
        return lambda x: x, brier_score(predicted, actual)

    try:
        from sklearn.isotonic import IsotonicRegression

        ir = IsotonicRegression(out_of_bounds="clip")
        ir.fit(predicted, actual)

        def calibrate(probs):
            return ir.predict(np.asarray(probs))

        calibrated = calibrate(predicted)
        cal_brier = brier_score(calibrated, actual)

        return calibrate, cal_brier

    except Exception as e:
        logger.warning(f"Isotonic calibration failed: {e}")
        return lambda x: x, brier_score(predicted, actual)


def analyze_calibration(
    predicted_probs: np.ndarray,
    actual_outcomes: np.ndarray,
    method: str = "platt",
    n_bins: int = 10,
) -> CalibrationResult:
    """Full calibration analysis.

    Args:
        predicted_probs: model confidence scores (0-1)
        actual_outcomes: binary outcomes (0 = loss, 1 = win)
        method: "platt" or "isotonic"
        n_bins: number of bins for reliability diagram
    """
    predicted = np.asarray(predicted_probs, dtype=float)
    actual = np.asarray(actual_outcomes, dtype=float)

    original_brier = brier_score(predicted, actual)

    if method == "isotonic":
        calibrate_fn, cal_brier = isotonic_calibration(predicted, actual)
    else:
        calibrate_fn, cal_brier = platt_scaling(predicted, actual)

    improvement = ((original_brier - cal_brier) / original_brier * 100) if original_brier > 0 else 0

    # Reliability diagram (on original predictions)
    diagram = reliability_diagram(predicted, actual, n_bins)

    return CalibrationResult(
        brier_score=original_brier,
        brier_score_calibrated=cal_brier,
        reliability_bins=diagram,
        calibration_method=method,
        improvement_pct=improvement,
    )
