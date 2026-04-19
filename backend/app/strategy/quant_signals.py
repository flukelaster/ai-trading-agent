"""
Quantitative Alpha Signals — statistical signal generators.

Provides:
- Z-score mean reversion with half-life estimation
- Hurst exponent (trending vs mean-reverting classification)
- Rolling Sharpe ratio (strategy deterioration detection)
- Risk-adjusted momentum factor (cross-symbol ranking)
- Volatility breakout (normalized ATR breakout)
"""

from dataclasses import dataclass

import numpy as np


@dataclass
class QuantSignals:
    """Collection of quant signals for a single symbol."""

    z_score: float  # Current z-score (mean reversion signal)
    half_life: float  # Estimated mean-reversion half-life (bars)
    hurst: float  # Hurst exponent (>0.5 trending, <0.5 mean-reverting)
    rolling_sharpe: float  # Rolling Sharpe ratio (annualized)
    momentum_factor: float  # Risk-adjusted momentum
    vol_breakout: float  # Volatility breakout signal (-1, 0, or 1)
    regime_hint: str  # "trending" or "mean_reverting" based on Hurst

    def to_dict(self) -> dict:
        return {
            "z_score": float(round(self.z_score, 4)),
            "half_life": float(round(self.half_life, 2)),
            "hurst": float(round(self.hurst, 4)),
            "rolling_sharpe": float(round(self.rolling_sharpe, 4)),
            "momentum_factor": float(round(self.momentum_factor, 4)),
            "vol_breakout": self.vol_breakout,
            "regime_hint": self.regime_hint,
        }


def compute_z_score(prices: np.ndarray, window: int = 30) -> tuple[float, float]:
    """Compute rolling z-score and mean-reversion half-life.

    Half-life estimated via OLS: Δy = α + β·y_{t-1} + ε
    Half-life = -ln(2) / ln(1 + β)

    Returns:
        (z_score, half_life_bars)
    """
    if len(prices) < window + 5:
        return 0.0, float("inf")

    series = prices[-window:]
    mean = series.mean()
    std = series.std()

    z = (series[-1] - mean) / std if std > 0 else 0.0

    # Half-life via OLS on lagged levels
    y = np.diff(series)
    x = series[:-1]
    if len(x) < 5 or np.std(x) == 0:
        return z, float("inf")

    # Simple OLS: β = cov(x,y) / var(x)
    beta = np.cov(x, y)[0, 1] / np.var(x) if np.var(x) > 0 else 0

    if beta >= 0:
        # No mean reversion
        return z, float("inf")

    half_life = -np.log(2) / np.log(1 + beta)
    return z, max(half_life, 1.0)


def compute_hurst(prices: np.ndarray, max_lag: int = 20) -> float:
    """Compute Hurst exponent via rescaled range (R/S) method.

    H > 0.5: trending (persistent)
    H = 0.5: random walk
    H < 0.5: mean-reverting (anti-persistent)
    """
    if len(prices) < max_lag * 2:
        return 0.5

    lags = range(2, min(max_lag + 1, len(prices) // 2))
    tau = []
    rs_values = []

    for lag in lags:
        # Split series into chunks of size lag
        returns = np.diff(np.log(prices))
        n_chunks = len(returns) // lag
        if n_chunks < 1:
            continue

        rs_list = []
        for i in range(n_chunks):
            chunk = returns[i * lag : (i + 1) * lag]
            mean = chunk.mean()
            deviations = np.cumsum(chunk - mean)
            r = deviations.max() - deviations.min()
            s = chunk.std()
            if s > 0:
                rs_list.append(r / s)

        if rs_list:
            tau.append(lag)
            rs_values.append(np.mean(rs_list))

    if len(tau) < 3:
        return 0.5

    # Hurst = slope of log(R/S) vs log(lag)
    log_tau = np.log(tau)
    log_rs = np.log(rs_values)

    # OLS slope
    n = len(log_tau)
    hurst = (n * np.sum(log_tau * log_rs) - np.sum(log_tau) * np.sum(log_rs)) / (
        n * np.sum(log_tau**2) - np.sum(log_tau) ** 2
    )

    return np.clip(hurst, 0.0, 1.0)


def compute_rolling_sharpe(
    prices: np.ndarray,
    window: int = 60,
    annualization: float = 252,
) -> float:
    """Compute rolling Sharpe ratio (annualized, zero risk-free rate)."""
    if len(prices) < window + 1:
        return 0.0

    returns = np.diff(np.log(prices[-window - 1 :]))
    if len(returns) < 5:
        return 0.0

    mean_r = returns.mean()
    std_r = returns.std()

    if std_r == 0:
        return 0.0

    return (mean_r / std_r) * np.sqrt(annualization)


def compute_momentum_factor(
    prices: np.ndarray,
    lookback: int = 20,
) -> float:
    """Risk-adjusted momentum = return / volatility over lookback period."""
    if len(prices) < lookback + 1:
        return 0.0

    returns = np.diff(np.log(prices[-lookback - 1 :]))
    total_return = returns.sum()
    vol = returns.std()

    if vol == 0:
        return 0.0

    return total_return / vol


def compute_vol_breakout(
    prices: np.ndarray,
    atr_window: int = 14,
    lookback: int = 60,
    threshold: float = 1.5,
) -> float:
    """Volatility breakout signal.

    Fires when current ATR > threshold * median(ATR over lookback).
    Direction determined by recent price movement.

    Returns:
        1.0 (bullish breakout), -1.0 (bearish breakout), or 0.0 (no breakout)
    """
    if len(prices) < lookback + atr_window:
        return 0.0

    # Simple ATR approximation (true range needs high/low, use price range instead)
    returns = np.abs(np.diff(prices))

    # Current ATR
    current_atr = returns[-atr_window:].mean()

    # Historical median ATR
    historical_atrs = []
    for i in range(atr_window, min(lookback, len(returns))):
        historical_atrs.append(returns[i - atr_window : i].mean())

    if not historical_atrs:
        return 0.0

    median_atr = np.median(historical_atrs)

    if median_atr == 0:
        return 0.0

    # Check breakout
    if current_atr / median_atr >= threshold:
        # Direction: based on recent returns
        recent_return = prices[-1] / prices[-atr_window] - 1
        return 1.0 if recent_return > 0 else -1.0

    return 0.0


def compute_all_signals(
    prices: np.ndarray,
    z_window: int = 30,
    sharpe_window: int = 60,
    momentum_lookback: int = 20,
) -> QuantSignals:
    """Compute all quant signals for a single symbol."""
    z_score, half_life = compute_z_score(prices, z_window)
    hurst = compute_hurst(prices)
    rolling_sharpe = compute_rolling_sharpe(prices, sharpe_window)
    momentum = compute_momentum_factor(prices, momentum_lookback)
    vol_breakout = compute_vol_breakout(prices)

    regime_hint = "mean_reverting" if hurst < 0.45 else "trending" if hurst > 0.55 else "neutral"

    return QuantSignals(
        z_score=z_score,
        half_life=half_life,
        hurst=hurst,
        rolling_sharpe=rolling_sharpe,
        momentum_factor=momentum,
        vol_breakout=vol_breakout,
        regime_hint=regime_hint,
    )


def rank_momentum(
    price_series: dict[str, np.ndarray],
    lookback: int = 20,
) -> dict[str, int]:
    """Rank symbols by risk-adjusted momentum.

    Returns:
        {symbol: rank} where 1 = strongest momentum
    """
    factors = {}
    for sym, prices in price_series.items():
        factors[sym] = compute_momentum_factor(prices, lookback)

    ranked = sorted(factors.items(), key=lambda x: x[1], reverse=True)
    return {sym: rank + 1 for rank, (sym, _) in enumerate(ranked)}
