"""
Drift Detection — monitors feature and prediction distribution shifts.
Uses Population Stability Index (PSI) for feature drift.
"""

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

# PSI thresholds
PSI_LOW = 0.10  # no significant drift
PSI_MEDIUM = 0.25  # moderate drift — monitor
PSI_HIGH = 0.50  # severe drift — alert


@dataclass
class DriftReport:
    feature_drift: dict = field(default_factory=dict)  # feature_name → PSI
    prediction_drift: dict = field(default_factory=dict)  # label → {expected, actual, shift}
    drifted_features: list[str] = field(default_factory=list)  # features with PSI > threshold
    alert: bool = False
    summary: str = ""

    def to_dict(self) -> dict:
        return {
            "feature_drift": self.feature_drift,
            "prediction_drift": self.prediction_drift,
            "drifted_features": self.drifted_features,
            "alert": self.alert,
            "summary": self.summary,
        }


def compute_psi(expected: np.ndarray, actual: np.ndarray, bins: int = 10) -> float:
    """
    Compute Population Stability Index between two distributions.
    PSI < 0.10: no significant shift
    PSI 0.10-0.25: moderate shift
    PSI > 0.25: significant shift
    """
    if len(expected) < 10 or len(actual) < 10:
        return 0.0

    # Create bins from expected distribution
    breakpoints = np.percentile(expected, np.linspace(0, 100, bins + 1))
    breakpoints = np.unique(breakpoints)
    if len(breakpoints) < 3:
        return 0.0

    expected_counts = np.histogram(expected, bins=breakpoints)[0] + 1  # avoid zero
    actual_counts = np.histogram(actual, bins=breakpoints)[0] + 1

    expected_pct = expected_counts / expected_counts.sum()
    actual_pct = actual_counts / actual_counts.sum()

    psi = np.sum((actual_pct - expected_pct) * np.log(actual_pct / expected_pct))
    return float(psi)


def compute_feature_drift(
    live_features: pd.DataFrame,
    training_stats: dict,
) -> dict[str, float]:
    """
    Compare live feature distributions to training statistics using PSI.

    Args:
        live_features: Recent feature DataFrame (last N bars).
        training_stats: Dict with per-feature stats {feature_name: {mean, std, ...}}.

    Returns:
        Dict of feature_name → PSI value.
    """
    results = {}
    for col in live_features.columns:
        if col not in training_stats:
            continue

        stats = training_stats[col]
        train_mean = stats.get("mean", 0)
        train_std = stats.get("std", 1)

        if train_std <= 0:
            continue

        live_vals = live_features[col].dropna().values
        if len(live_vals) < 10:
            continue

        # Reconstruct approximate training distribution from stats
        train_approx = np.random.normal(train_mean, train_std, size=max(len(live_vals), 100))
        psi = compute_psi(train_approx, live_vals)
        results[col] = round(psi, 4)

    return results


def compute_prediction_drift(
    recent_predictions: list[int],
    training_label_dist: dict[str, float],
) -> dict:
    """
    Compare recent prediction distribution to training label distribution.

    Args:
        recent_predictions: List of recent signal predictions (-1, 0, 1).
        training_label_dist: Expected distribution, e.g. {"sell": 0.2, "hold": 0.6, "buy": 0.2}.
    """
    if not recent_predictions or not training_label_dist:
        return {}

    len(recent_predictions)
    preds = np.array(recent_predictions)

    actual_dist = {
        "sell": float(np.mean(preds == -1)),
        "hold": float(np.mean(preds == 0)),
        "buy": float(np.mean(preds == 1)),
    }

    result = {}
    for label in ["sell", "hold", "buy"]:
        expected = training_label_dist.get(label, 0.33)
        actual = actual_dist.get(label, 0)
        shift = actual - expected
        result[label] = {
            "expected": round(expected, 4),
            "actual": round(actual, 4),
            "shift": round(shift, 4),
        }

    return result


def check_drift(
    training_stats: dict | None,
    training_label_dist: dict | None,
    live_features: pd.DataFrame | None = None,
    recent_predictions: list[int] | None = None,
    psi_threshold: float = PSI_MEDIUM,
    min_drifted_features: int = 3,
) -> DriftReport:
    """
    Run full drift check and produce a report.
    Alert if >= min_drifted_features have PSI > psi_threshold.
    """
    report = DriftReport()

    if live_features is not None and training_stats:
        report.feature_drift = compute_feature_drift(live_features, training_stats)
        report.drifted_features = [f for f, psi in report.feature_drift.items() if psi > psi_threshold]

    if recent_predictions and training_label_dist:
        report.prediction_drift = compute_prediction_drift(recent_predictions, training_label_dist)

    n_drifted = len(report.drifted_features)
    report.alert = n_drifted >= min_drifted_features

    if report.alert:
        report.summary = (
            f"DRIFT ALERT: {n_drifted} features shifted (PSI > {psi_threshold}): {report.drifted_features[:5]}"
        )
    elif n_drifted > 0:
        report.summary = f"Minor drift: {n_drifted} features (below alert threshold of {min_drifted_features})"
    else:
        report.summary = "No significant drift detected"

    return report
