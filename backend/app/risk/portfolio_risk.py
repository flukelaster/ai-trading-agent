"""
Portfolio-Level Risk — aggregate risk across multiple symbols.

Computes:
- Portfolio VaR (correlation-adjusted)
- Marginal VaR per position
- Component VaR (risk contribution per symbol)
"""

from dataclasses import dataclass

import numpy as np


@dataclass
class PortfolioRiskResult:
    """Portfolio-level risk metrics."""

    portfolio_var_95: float  # 95% portfolio VaR
    portfolio_var_99: float  # 99% portfolio VaR
    marginal_var: dict[str, float]  # per-symbol marginal VaR
    component_var: dict[str, float]  # per-symbol risk contribution (sums to portfolio VaR)
    diversification_ratio: float  # < 1.0 means diversification benefit
    max_position_by_var: dict[str, float]  # max lot based on marginal VaR limit

    def to_dict(self) -> dict:
        return {
            "portfolio_var_95": float(round(self.portfolio_var_95, 6)),
            "portfolio_var_99": float(round(self.portfolio_var_99, 6)),
            "marginal_var": {k: round(v, 6) for k, v in self.marginal_var.items()},
            "component_var": {k: round(v, 6) for k, v in self.component_var.items()},
            "diversification_ratio": float(round(self.diversification_ratio, 4)),
            "max_position_by_var": {k: round(v, 4) for k, v in self.max_position_by_var.items()},
        }


def compute_portfolio_risk(
    positions: dict[str, float],
    price_series: dict[str, np.ndarray],
    window: int = 60,
    max_portfolio_var: float = 0.03,
) -> PortfolioRiskResult:
    """Compute portfolio-level risk metrics.

    Args:
        positions: {symbol: notional_exposure} (e.g., {"GOLD": 5000, "BTCUSD": 2000})
        price_series: {symbol: np.array of prices}
        window: lookback for return calculation
        max_portfolio_var: max acceptable portfolio VaR (for position limits)

    Returns:
        PortfolioRiskResult with all risk metrics
    """
    symbols = sorted(positions.keys())
    n = len(symbols)

    if n == 0:
        return PortfolioRiskResult(0, 0, {}, {}, 1.0, {})

    # Build return matrix
    returns_matrix = []
    weights = []
    total_exposure = sum(abs(v) for v in positions.values())

    for sym in symbols:
        p = price_series.get(sym, np.array([]))
        if len(p) < window + 1:
            returns_matrix.append(np.zeros(window))
        else:
            r = np.diff(np.log(p[-(window + 1) :]))
            returns_matrix.append(r[:window])
        weights.append(positions[sym] / total_exposure if total_exposure > 0 else 0)

    returns_matrix = np.array(returns_matrix)  # (n_symbols, n_periods)
    weights = np.array(weights)

    if returns_matrix.shape[1] == 0:
        return PortfolioRiskResult(0, 0, {}, {}, 1.0, {})

    # Covariance matrix
    cov = np.cov(returns_matrix)
    if cov.ndim == 0:
        cov = np.array([[cov]])

    # Portfolio variance
    port_var = weights @ cov @ weights
    port_vol = np.sqrt(max(port_var, 0))

    # VaR (parametric)
    z_95, z_99 = 1.6449, 2.3263
    portfolio_var_95 = port_vol * z_95
    portfolio_var_99 = port_vol * z_99

    # Individual VaRs
    individual_vols = np.sqrt(np.diag(cov))
    individual_vars_95 = individual_vols * z_95

    # Diversification ratio = sum(individual VaRs) / portfolio VaR
    sum_individual = np.sum(np.abs(weights) * individual_vars_95)
    div_ratio = portfolio_var_95 / sum_individual if sum_individual > 0 else 1.0

    # Marginal VaR = d(portfolio_VaR) / d(weight_i) ≈ (cov @ w) / port_vol
    if port_vol > 0:
        marginal = (cov @ weights) / port_vol * z_95
    else:
        marginal = np.zeros(n)

    # Component VaR = weight_i * marginal_VaR_i (sums to portfolio VaR)
    component = weights * marginal

    # Max position based on VaR budget
    max_pos = {}
    for i, sym in enumerate(symbols):
        if marginal[i] > 0:
            max_pos[sym] = round(max_portfolio_var / marginal[i], 4)
        else:
            max_pos[sym] = 1.0

    return PortfolioRiskResult(
        portfolio_var_95=portfolio_var_95,
        portfolio_var_99=portfolio_var_99,
        marginal_var={sym: marginal[i] for i, sym in enumerate(symbols)},
        component_var={sym: component[i] for i, sym in enumerate(symbols)},
        diversification_ratio=div_ratio,
        max_position_by_var=max_pos,
    )
