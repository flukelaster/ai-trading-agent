"""
Portfolio Optimizer — optimal capital allocation across symbols.

Supports:
- Mean-Variance Optimization (Markowitz)
- CVaR Optimization (robust to fat tails)
- Black-Litterman overlay (AI sentiment as views)
- Minimum variance and maximum Sharpe portfolios
"""

from dataclasses import dataclass

import numpy as np
from loguru import logger


@dataclass
class PortfolioAllocation:
    """Result of portfolio optimization."""

    weights: dict[str, float]  # optimal weight per symbol
    expected_return: float  # annualized expected return
    expected_vol: float  # annualized volatility
    sharpe_ratio: float  # expected Sharpe
    method: str  # "markowitz", "min_variance", "max_sharpe", "cvar", "risk_parity"
    rebalance_needed: bool = False  # True if current weights diverge > threshold

    def to_dict(self) -> dict:
        return {
            "weights": {k: round(v, 4) for k, v in self.weights.items()},
            "expected_return": float(round(self.expected_return, 4)),
            "expected_vol": float(round(self.expected_vol, 4)),
            "sharpe_ratio": float(round(self.sharpe_ratio, 4)),
            "method": self.method,
            "rebalance_needed": self.rebalance_needed,
        }


def _build_inputs(
    price_series: dict[str, np.ndarray],
    window: int = 60,
) -> tuple[list[str], np.ndarray, np.ndarray]:
    """Build expected returns and covariance matrix from price data."""
    symbols = sorted(price_series.keys())
    returns_list = []

    for sym in symbols:
        p = price_series[sym]
        if len(p) < window + 1:
            returns_list.append(np.zeros(window))
        else:
            r = np.diff(np.log(p[-(window + 1) :]))
            returns_list.append(r[:window])

    returns_matrix = np.array(returns_list)
    mu = returns_matrix.mean(axis=1) * 252  # annualize
    cov = np.cov(returns_matrix) * 252

    if cov.ndim == 0:
        cov = np.array([[float(cov)]])

    return symbols, mu, cov


def min_variance(
    price_series: dict[str, np.ndarray],
    window: int = 60,
    min_weight: float = 0.05,
    max_weight: float = 0.60,
) -> PortfolioAllocation:
    """Minimum variance portfolio (analytical solution with bounds)."""
    symbols, mu, cov = _build_inputs(price_series, window)
    n = len(symbols)

    if n == 0:
        return PortfolioAllocation({}, 0, 0, 0, "min_variance")

    try:
        # Analytical: w = (Σ^-1 · 1) / (1' · Σ^-1 · 1)
        cov_inv = np.linalg.inv(cov + np.eye(n) * 1e-8)
        ones = np.ones(n)
        raw_w = cov_inv @ ones
        w = raw_w / raw_w.sum()

        # Apply bounds
        w = np.clip(w, min_weight, max_weight)
        w /= w.sum()

    except np.linalg.LinAlgError:
        w = np.ones(n) / n

    port_return = w @ mu
    port_vol = np.sqrt(w @ cov @ w)
    sharpe = port_return / port_vol if port_vol > 0 else 0

    return PortfolioAllocation(
        weights={sym: w[i] for i, sym in enumerate(symbols)},
        expected_return=port_return,
        expected_vol=port_vol,
        sharpe_ratio=sharpe,
        method="min_variance",
    )


def max_sharpe(
    price_series: dict[str, np.ndarray],
    window: int = 60,
    risk_free: float = 0.0,
    min_weight: float = 0.05,
    max_weight: float = 0.60,
) -> PortfolioAllocation:
    """Maximum Sharpe ratio portfolio (tangency portfolio)."""
    symbols, mu, cov = _build_inputs(price_series, window)
    n = len(symbols)

    if n == 0:
        return PortfolioAllocation({}, 0, 0, 0, "max_sharpe")

    try:
        excess_mu = mu - risk_free
        cov_inv = np.linalg.inv(cov + np.eye(n) * 1e-8)
        raw_w = cov_inv @ excess_mu
        w = raw_w / raw_w.sum()

        w = np.clip(w, min_weight, max_weight)
        w /= w.sum()

    except np.linalg.LinAlgError:
        w = np.ones(n) / n

    port_return = w @ mu
    port_vol = np.sqrt(w @ cov @ w)
    sharpe = (port_return - risk_free) / port_vol if port_vol > 0 else 0

    return PortfolioAllocation(
        weights={sym: w[i] for i, sym in enumerate(symbols)},
        expected_return=port_return,
        expected_vol=port_vol,
        sharpe_ratio=sharpe,
        method="max_sharpe",
    )


def risk_parity(
    price_series: dict[str, np.ndarray],
    window: int = 60,
) -> PortfolioAllocation:
    """True risk parity — equal risk contribution from each symbol.

    Uses inverse-volatility with correlation adjustment.
    """
    symbols, mu, cov = _build_inputs(price_series, window)
    n = len(symbols)

    if n == 0:
        return PortfolioAllocation({}, 0, 0, 0, "risk_parity")

    vols = np.sqrt(np.diag(cov))
    vols = np.maximum(vols, 1e-8)

    # Initial: inverse volatility
    w = 1.0 / vols
    w /= w.sum()

    # Iterative refinement (Newton-like) for equal risk contribution
    for _ in range(50):
        sigma_w = cov @ w
        risk_contrib = w * sigma_w
        total_risk = risk_contrib.sum()

        if total_risk <= 0:
            break

        target = total_risk / n
        adjustment = target / (risk_contrib + 1e-10)
        w = w * adjustment
        w /= w.sum()

    port_return = w @ mu
    port_vol = np.sqrt(w @ cov @ w)
    sharpe = port_return / port_vol if port_vol > 0 else 0

    return PortfolioAllocation(
        weights={sym: w[i] for i, sym in enumerate(symbols)},
        expected_return=port_return,
        expected_vol=port_vol,
        sharpe_ratio=sharpe,
        method="risk_parity",
    )


def cvar_optimization(
    price_series: dict[str, np.ndarray],
    window: int = 60,
    target_return: float | None = None,
    confidence: float = 0.95,
    min_weight: float = 0.05,
    max_weight: float = 0.60,
) -> PortfolioAllocation:
    """CVaR optimization — minimize Expected Shortfall.

    Uses historical simulation (not parametric).
    Falls back to min_variance if cvxpy unavailable.
    """
    symbols, mu, cov = _build_inputs(price_series, window)
    n = len(symbols)

    if n == 0:
        return PortfolioAllocation({}, 0, 0, 0, "cvar")

    # Build return scenarios
    returns_list = []
    for sym in symbols:
        p = price_series[sym]
        if len(p) < window + 1:
            returns_list.append(np.zeros(window))
        else:
            returns_list.append(np.diff(np.log(p[-(window + 1) :])))

    returns_matrix = np.array(returns_list)  # (n, T)

    try:
        import cvxpy as cp

        w = cp.Variable(n)
        alpha = 1 - confidence
        T = returns_matrix.shape[1]

        # Portfolio returns per scenario
        port_returns = returns_matrix.T @ w  # (T,)

        # CVaR formulation
        zeta = cp.Variable()
        losses = -port_returns
        cvar = zeta + (1.0 / (T * alpha)) * cp.sum(cp.pos(losses - zeta))

        constraints = [
            cp.sum(w) == 1,
            w >= min_weight,
            w <= max_weight,
        ]

        if target_return is not None:
            constraints.append(mu @ w >= target_return / 252)

        prob = cp.Problem(cp.Minimize(cvar), constraints)
        prob.solve(solver=cp.SCS, verbose=False)

        if prob.status == "optimal":
            w_opt = w.value
        else:
            logger.warning(f"CVaR optimization status: {prob.status}, falling back")
            return min_variance(price_series, window, min_weight, max_weight)

    except ImportError:
        logger.warning("cvxpy not available, falling back to min_variance")
        return min_variance(price_series, window, min_weight, max_weight)
    except Exception as e:
        logger.warning(f"CVaR optimization failed: {e}, falling back")
        return min_variance(price_series, window, min_weight, max_weight)

    port_return = w_opt @ mu
    port_vol = np.sqrt(w_opt @ cov @ w_opt)
    sharpe = port_return / port_vol if port_vol > 0 else 0

    return PortfolioAllocation(
        weights={sym: w_opt[i] for i, sym in enumerate(symbols)},
        expected_return=port_return,
        expected_vol=port_vol,
        sharpe_ratio=sharpe,
        method="cvar",
    )


def black_litterman(
    price_series: dict[str, np.ndarray],
    views: dict[str, float],
    view_confidence: dict[str, float] | None = None,
    window: int = 60,
    risk_aversion: float = 2.5,
    tau: float = 0.05,
) -> PortfolioAllocation:
    """Black-Litterman model — combine market equilibrium with AI sentiment views.

    Args:
        price_series: {symbol: prices}
        views: {symbol: expected_excess_return} from AI sentiment
               e.g., {"GOLD": 0.02, "BTCUSD": -0.01} means AI thinks GOLD will return +2%
        view_confidence: {symbol: confidence 0-1} — lower = less certain view
        risk_aversion: market risk aversion parameter (delta)
        tau: scaling factor for prior uncertainty
    """
    symbols, mu_market, cov = _build_inputs(price_series, window)
    n = len(symbols)

    if n == 0 or not views:
        return max_sharpe(price_series, window)

    # Market equilibrium returns: pi = delta * Sigma * w_market
    w_market = np.ones(n) / n  # assume equal-weight market portfolio
    pi = risk_aversion * cov @ w_market

    # Build view matrices
    view_symbols = [s for s in symbols if s in views]
    k = len(view_symbols)

    if k == 0:
        return max_sharpe(price_series, window)

    P = np.zeros((k, n))
    q = np.zeros(k)

    for i, sym in enumerate(view_symbols):
        j = symbols.index(sym)
        P[i, j] = 1.0
        q[i] = views[sym]

    # View uncertainty: Omega = diag(confidence-adjusted)
    omega_diag = []
    for sym in view_symbols:
        conf = (view_confidence or {}).get(sym, 0.5)
        # Higher confidence → lower uncertainty
        omega_diag.append(tau * (1 - conf + 0.1))

    Omega = np.diag(omega_diag)

    # Black-Litterman posterior
    tau_cov = tau * cov
    try:
        inv_tau_cov = np.linalg.inv(tau_cov + np.eye(n) * 1e-8)
        inv_omega = np.linalg.inv(Omega + np.eye(k) * 1e-8)

        post_cov = np.linalg.inv(inv_tau_cov + P.T @ inv_omega @ P)
        post_mu = post_cov @ (inv_tau_cov @ pi + P.T @ inv_omega @ q)

        # Optimal weights
        w = np.linalg.inv(risk_aversion * cov + np.eye(n) * 1e-8) @ post_mu
        w = np.clip(w, 0.05, 0.60)
        w /= w.sum()

    except np.linalg.LinAlgError:
        logger.warning("Black-Litterman matrix inversion failed, falling back")
        return max_sharpe(price_series, window)

    port_return = w @ mu_market
    port_vol = np.sqrt(w @ cov @ w)
    sharpe = port_return / port_vol if port_vol > 0 else 0

    return PortfolioAllocation(
        weights={sym: w[i] for i, sym in enumerate(symbols)},
        expected_return=port_return,
        expected_vol=port_vol,
        sharpe_ratio=sharpe,
        method="black_litterman",
    )


def check_rebalance(
    current_weights: dict[str, float],
    optimal_weights: dict[str, float],
    threshold: float = 0.05,
) -> bool:
    """Check if rebalancing is needed (any weight drifted > threshold)."""
    for sym, opt_w in optimal_weights.items():
        cur_w = current_weights.get(sym, 0.0)
        if abs(cur_w - opt_w) > threshold:
            return True
    return False
