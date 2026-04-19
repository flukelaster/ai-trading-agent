"""
GARCH Volatility Forecast — forward-looking volatility estimation.

Uses GARCH(1,1) model to forecast conditional volatility.
Falls back to EWMA if GARCH fitting fails (convergence issue).
"""

from dataclasses import dataclass

import numpy as np
from loguru import logger


@dataclass
class GARCHResult:
    """Result of GARCH volatility forecast."""

    current_vol: float  # current conditional volatility (annualized)
    forecast_1: float  # 1-step ahead forecast
    forecast_5: float  # 5-step ahead forecast
    long_run_vol: float  # unconditional (long-run) volatility
    method: str  # "garch" or "ewma" (fallback)
    omega: float = 0.0  # GARCH omega parameter
    alpha: float = 0.0  # GARCH alpha (news impact)
    beta: float = 0.0  # GARCH beta (persistence)

    def to_dict(self) -> dict:
        return {
            "current_vol": float(round(self.current_vol, 6)),
            "forecast_1": float(round(self.forecast_1, 6)),
            "forecast_5": float(round(self.forecast_5, 6)),
            "long_run_vol": float(round(self.long_run_vol, 6)),
            "method": self.method,
            "alpha": float(round(self.alpha, 4)),
            "beta": float(round(self.beta, 4)),
        }

    @property
    def persistence(self) -> float:
        """GARCH persistence (alpha + beta). Near 1.0 = highly persistent vol."""
        return self.alpha + self.beta


def _ewma_volatility(
    returns: np.ndarray,
    span: int = 30,
    horizon: int = 5,
) -> GARCHResult:
    """EWMA volatility as fallback when GARCH fails."""
    if len(returns) < 5:
        return GARCHResult(0, 0, 0, 0, "ewma")

    # Exponentially weighted variance
    weights = np.exp(-np.arange(len(returns))[::-1] / span)
    weights /= weights.sum()
    ewma_var = np.average(returns**2, weights=weights)
    ewma_vol = np.sqrt(ewma_var)

    ann = ewma_vol * np.sqrt(252)
    long_run = returns.std() * np.sqrt(252)

    return GARCHResult(
        current_vol=ann,
        forecast_1=ann,  # EWMA forecast is constant
        forecast_5=ann,
        long_run_vol=long_run,
        method="ewma",
    )


def fit_garch(
    prices: np.ndarray,
    window: int = 200,
    horizon: int = 5,
) -> GARCHResult:
    """Fit GARCH(1,1) and produce volatility forecasts.

    Args:
        prices: price series (newest last)
        window: lookback window for fitting
        horizon: forecast horizon (steps ahead)

    Returns:
        GARCHResult with current vol, forecasts, and model parameters.
    """
    # Compute returns
    p = prices[-window:]
    p = p[p > 0]
    if len(p) < 50:
        return _ewma_volatility(np.diff(np.log(p)) if len(p) > 1 else np.array([0]))

    returns = np.diff(np.log(p)) * 100  # scale to percentage for arch library

    try:
        from arch import arch_model

        model = arch_model(returns, vol="Garch", p=1, q=1, mean="Zero", rescale=False)
        result = model.fit(disp="off", show_warning=False)

        # Extract parameters
        omega = result.params.get("omega", 0)
        alpha = result.params.get("alpha[1]", 0)
        beta = result.params.get("beta[1]", 0)

        # Current conditional variance (last fitted value)
        cond_var = result.conditional_volatility.iloc[-1] ** 2

        # Multi-step forecast
        forecast = result.forecast(horizon=horizon)
        var_1 = forecast.variance.iloc[-1, 0]
        var_h = forecast.variance.iloc[-1, min(horizon - 1, forecast.variance.shape[1] - 1)]

        # Long-run (unconditional) variance
        persistence = alpha + beta
        if persistence < 1.0 and omega > 0:
            long_run_var = omega / (1 - persistence)
        else:
            long_run_var = returns.var()

        # Convert from percentage back to decimal, then annualize
        scale = np.sqrt(252) / 100

        return GARCHResult(
            current_vol=np.sqrt(cond_var) * scale,
            forecast_1=np.sqrt(var_1) * scale,
            forecast_5=np.sqrt(var_h) * scale,
            long_run_vol=np.sqrt(long_run_var) * scale,
            method="garch",
            omega=omega,
            alpha=alpha,
            beta=beta,
        )

    except Exception as e:
        logger.warning(f"GARCH fitting failed, using EWMA fallback: {e}")
        raw_returns = np.diff(np.log(prices[-window:])) if len(prices) > 1 else np.array([0])
        return _ewma_volatility(raw_returns[raw_returns != 0])
