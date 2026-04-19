"""
VaR / CVaR Calculator — Value at Risk and Conditional Value at Risk.

Supports:
- Historical VaR (percentile-based)
- Parametric VaR (normal assumption)
- Cornish-Fisher VaR (skewness + kurtosis adjusted)
- CVaR / Expected Shortfall (average loss beyond VaR)
"""

from dataclasses import dataclass

import numpy as np


@dataclass
class VaRResult:
    """Result of a VaR/CVaR calculation."""

    var_95: float  # 95% VaR (positive = loss)
    var_99: float  # 99% VaR
    cvar_95: float  # 95% CVaR (Expected Shortfall)
    cvar_99: float  # 99% CVaR
    method: str  # "historical", "parametric", "cornish_fisher"
    window: int  # number of observations used
    annualized_vol: float  # annualized volatility estimate

    def to_dict(self) -> dict:
        return {
            "var_95": float(round(self.var_95, 6)),
            "var_99": float(round(self.var_99, 6)),
            "cvar_95": float(round(self.cvar_95, 6)),
            "cvar_99": float(round(self.cvar_99, 6)),
            "method": self.method,
            "window": self.window,
            "annualized_vol": float(round(self.annualized_vol, 6)),
        }


def _returns_from_prices(prices: np.ndarray) -> np.ndarray:
    """Compute log returns from a price series."""
    prices = prices[prices > 0]  # filter zeros
    if len(prices) < 2:
        return np.array([])
    return np.diff(np.log(prices))


def historical_var(
    prices: np.ndarray,
    window: int = 60,
) -> VaRResult:
    """Historical (non-parametric) VaR — uses actual return distribution."""
    returns = _returns_from_prices(prices[-window:])
    if len(returns) < 10:
        return VaRResult(0, 0, 0, 0, "historical", 0, 0)

    var_95 = -np.percentile(returns, 5)
    var_99 = -np.percentile(returns, 1)

    # CVaR = average of losses beyond VaR
    tail_95 = returns[returns <= -var_95]
    tail_99 = returns[returns <= -var_99]
    cvar_95 = -tail_95.mean() if len(tail_95) > 0 else var_95
    cvar_99 = -tail_99.mean() if len(tail_99) > 0 else var_99

    ann_vol = returns.std() * np.sqrt(252)

    return VaRResult(
        var_95=var_95,
        var_99=var_99,
        cvar_95=cvar_95,
        cvar_99=cvar_99,
        method="historical",
        window=len(returns),
        annualized_vol=ann_vol,
    )


def parametric_var(
    prices: np.ndarray,
    window: int = 60,
) -> VaRResult:
    """Parametric (Gaussian) VaR — assumes normal return distribution."""
    returns = _returns_from_prices(prices[-window:])
    if len(returns) < 10:
        return VaRResult(0, 0, 0, 0, "parametric", 0, 0)

    mu = returns.mean()
    sigma = returns.std()

    # z-scores for 95% and 99%
    z_95, z_99 = 1.6449, 2.3263

    var_95 = -(mu - z_95 * sigma)
    var_99 = -(mu - z_99 * sigma)

    # CVaR for normal distribution: E[X | X < -VaR]
    # CVaR = mu + sigma * phi(z) / (1 - alpha)  where phi = normal pdf
    from scipy.stats import norm

    cvar_95 = -(mu - sigma * norm.pdf(z_95) / 0.05)
    cvar_99 = -(mu - sigma * norm.pdf(z_99) / 0.01)

    ann_vol = sigma * np.sqrt(252)

    return VaRResult(
        var_95=var_95,
        var_99=var_99,
        cvar_95=cvar_95,
        cvar_99=cvar_99,
        method="parametric",
        window=len(returns),
        annualized_vol=ann_vol,
    )


def cornish_fisher_var(
    prices: np.ndarray,
    window: int = 60,
) -> VaRResult:
    """Cornish-Fisher VaR — adjusts for skewness and kurtosis."""
    returns = _returns_from_prices(prices[-window:])
    if len(returns) < 20:
        return VaRResult(0, 0, 0, 0, "cornish_fisher", 0, 0)

    mu = returns.mean()
    sigma = returns.std()
    from scipy.stats import kurtosis, skew

    s = skew(returns)
    k = kurtosis(returns)  # excess kurtosis

    def _cf_quantile(z: float) -> float:
        """Cornish-Fisher expansion of quantile."""
        return z + (z**2 - 1) * s / 6 + (z**3 - 3 * z) * k / 24 - (2 * z**3 - 5 * z) * s**2 / 36

    z_95 = _cf_quantile(-1.6449)
    z_99 = _cf_quantile(-2.3263)

    var_95 = -(mu + z_95 * sigma)
    var_99 = -(mu + z_99 * sigma)

    # Approximate CVaR using historical tail beyond CF-VaR
    tail_95 = returns[returns <= (mu + z_95 * sigma)]
    tail_99 = returns[returns <= (mu + z_99 * sigma)]
    cvar_95 = -tail_95.mean() if len(tail_95) > 0 else var_95
    cvar_99 = -tail_99.mean() if len(tail_99) > 0 else var_99

    ann_vol = sigma * np.sqrt(252)

    return VaRResult(
        var_95=var_95,
        var_99=var_99,
        cvar_95=cvar_95,
        cvar_99=cvar_99,
        method="cornish_fisher",
        window=len(returns),
        annualized_vol=ann_vol,
    )


def compute_var(
    prices: np.ndarray,
    method: str = "historical",
    window: int = 60,
) -> VaRResult:
    """Compute VaR/CVaR using the specified method.

    Args:
        prices: array of price observations (newest last)
        method: "historical", "parametric", or "cornish_fisher"
        window: lookback window (number of bars)
    """
    if method == "parametric":
        return parametric_var(prices, window)
    if method == "cornish_fisher":
        return cornish_fisher_var(prices, window)
    return historical_var(prices, window)
