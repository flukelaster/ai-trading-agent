"""
Kalman Filter — adaptive signal processing for trading.

Provides:
- Dynamic hedge ratio estimation (replaces static OLS in pair spread)
- Adaptive moving average (Kalman-smoothed price)
- Kalman residual z-score for mean reversion signals
"""

from dataclasses import dataclass

import numpy as np


@dataclass
class KalmanState:
    """State of the Kalman filter."""

    value: float  # filtered value (e.g., hedge ratio or smoothed price)
    variance: float  # estimation uncertainty
    residual: float  # innovation (prediction error)
    residual_z: float  # z-score of residual
    gain: float  # Kalman gain (0-1, higher = more responsive)

    def to_dict(self) -> dict:
        return {
            "value": round(self.value, 6),
            "variance": round(self.variance, 8),
            "residual": round(self.residual, 6),
            "residual_z": round(self.residual_z, 4),
            "gain": round(self.gain, 4),
        }


class KalmanFilter1D:
    """1-dimensional Kalman filter for scalar state estimation.

    Use cases:
    - Smoothed price (adaptive moving average)
    - Dynamic hedge ratio tracking
    """

    def __init__(
        self,
        initial_value: float = 0.0,
        process_noise: float = 1e-5,
        measurement_noise: float = 1e-3,
    ):
        """
        Args:
            initial_value: starting state estimate
            process_noise: Q — how much the true state changes per step (small = smooth)
            measurement_noise: R — observation noise (large = more smoothing)
        """
        self.x = initial_value  # state estimate
        self.P = 1.0  # estimation error covariance
        self.Q = process_noise  # process noise
        self.R = measurement_noise  # measurement noise
        self._residuals: list[float] = []
        self._max_residuals = 100

    def update(self, measurement: float) -> KalmanState:
        """Process one new measurement and return updated state."""
        # Predict
        x_pred = self.x
        P_pred = self.P + self.Q

        # Innovation
        residual = measurement - x_pred
        S = P_pred + self.R  # innovation covariance

        # Kalman gain
        K = P_pred / S if S > 0 else 0.5

        # Update
        self.x = x_pred + K * residual
        self.P = (1 - K) * P_pred

        # Track residuals for z-score
        self._residuals.append(residual)
        if len(self._residuals) > self._max_residuals:
            self._residuals.pop(0)

        # Z-score of residual
        if len(self._residuals) >= 5:
            r_arr = np.array(self._residuals)
            r_std = r_arr.std()
            r_z = residual / r_std if r_std > 0 else 0.0
        else:
            r_z = 0.0

        return KalmanState(
            value=self.x,
            variance=self.P,
            residual=residual,
            residual_z=r_z,
            gain=K,
        )

    def smooth_series(self, prices: np.ndarray) -> tuple[np.ndarray, list[KalmanState]]:
        """Run filter over entire price series.

        Returns:
            (smoothed_prices, list_of_states)
        """
        smoothed = np.zeros(len(prices))
        states = []

        for i, p in enumerate(prices):
            state = self.update(p)
            smoothed[i] = state.value
            states.append(state)

        return smoothed, states


class KalmanHedgeRatio:
    """2-state Kalman filter for dynamic hedge ratio estimation.

    Models: y_t = beta_t * x_t + alpha_t + epsilon_t
    where beta (hedge ratio) and alpha (intercept) evolve over time.
    """

    def __init__(
        self,
        process_noise: float = 1e-4,
        measurement_noise: float = 1.0,
    ):
        # State: [intercept, slope/hedge_ratio]
        self.beta = np.array([0.0, 1.0])  # [alpha, beta]
        self.P = np.eye(2) * 1.0  # state covariance
        self.Q = np.eye(2) * process_noise
        self.R = measurement_noise
        self._spread_residuals: list[float] = []
        self._max_residuals = 100

    def update(self, y: float, x: float) -> dict:
        """Update hedge ratio with new price pair.

        Args:
            y: dependent price (e.g., GOLD)
            x: independent price (e.g., USDJPY)

        Returns:
            dict with hedge_ratio, intercept, spread, spread_z
        """
        # Observation vector
        H = np.array([1.0, x])

        # Predict
        beta_pred = self.beta
        P_pred = self.P + self.Q

        # Innovation
        y_pred = H @ beta_pred
        residual = y - y_pred
        S = H @ P_pred @ H.T + self.R

        # Kalman gain
        K = (P_pred @ H.T) / S if S > 0 else P_pred @ H.T * 0.5

        # Update
        self.beta = beta_pred + K * residual
        self.P = P_pred - np.outer(K, H) @ P_pred

        # Spread = actual_y - predicted_y using current hedge ratio
        spread = y - (self.beta[0] + self.beta[1] * x)

        # Track spread for z-score
        self._spread_residuals.append(spread)
        if len(self._spread_residuals) > self._max_residuals:
            self._spread_residuals.pop(0)

        spread_z = 0.0
        if len(self._spread_residuals) >= 10:
            s_arr = np.array(self._spread_residuals)
            s_std = s_arr.std()
            spread_z = spread / s_std if s_std > 0 else 0.0

        return {
            "hedge_ratio": self.beta[1],
            "intercept": self.beta[0],
            "spread": spread,
            "spread_z": spread_z,
        }

    def process_series(self, y_prices: np.ndarray, x_prices: np.ndarray) -> list[dict]:
        """Run filter over price pair series."""
        n = min(len(y_prices), len(x_prices))
        results = []
        for i in range(n):
            results.append(self.update(y_prices[i], x_prices[i]))
        return results
