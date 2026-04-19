"""
Monte Carlo Simulation — assess strategy robustness by randomizing trade sequences.
"""

from dataclasses import dataclass

import numpy as np
from loguru import logger


@dataclass
class MonteCarloResult:
    n_simulations: int
    initial_balance: float
    median_final_balance: float = 0.0
    mean_final_balance: float = 0.0
    p5_final_balance: float = 0.0
    p95_final_balance: float = 0.0
    median_max_drawdown: float = 0.0
    p95_max_drawdown: float = 0.0  # worst-case drawdown at 95th percentile
    probability_of_ruin: float = 0.0  # P(balance < 50% of initial)
    probability_of_profit: float = 0.0  # P(final > initial)

    def to_dict(self) -> dict:
        return {
            "n_simulations": self.n_simulations,
            "initial_balance": self.initial_balance,
            "median_final_balance": round(self.median_final_balance, 2),
            "mean_final_balance": round(self.mean_final_balance, 2),
            "p5_final_balance": round(self.p5_final_balance, 2),
            "p95_final_balance": round(self.p95_final_balance, 2),
            "median_max_drawdown": round(self.median_max_drawdown, 4),
            "p95_max_drawdown": round(self.p95_max_drawdown, 4),
            "probability_of_ruin": round(self.probability_of_ruin, 4),
            "probability_of_profit": round(self.probability_of_profit, 4),
        }


def monte_carlo_analysis(
    trade_profits: list[float],
    n_simulations: int = 1000,
    initial_balance: float = 10000.0,
    ruin_threshold: float = 0.5,
) -> MonteCarloResult:
    """
    Run Monte Carlo simulation by shuffling trade order.

    Args:
        trade_profits: List of P&L values from each trade.
        n_simulations: Number of random shuffles.
        initial_balance: Starting capital.
        ruin_threshold: Fraction of initial balance considered "ruin" (default 50%).
    """
    if not trade_profits or len(trade_profits) < 5:
        logger.warning(f"Monte Carlo: insufficient trades ({len(trade_profits)})")
        return MonteCarloResult(n_simulations=0, initial_balance=initial_balance)

    profits = np.array(trade_profits)
    n_trades = len(profits)

    final_balances = np.zeros(n_simulations)
    max_drawdowns = np.zeros(n_simulations)

    rng = np.random.default_rng(seed=42)

    for sim in range(n_simulations):
        shuffled = rng.permutation(profits)
        equity = np.empty(n_trades + 1)
        equity[0] = initial_balance
        for i, pnl in enumerate(shuffled):
            equity[i + 1] = equity[i] + pnl

        final_balances[sim] = equity[-1]

        # Max drawdown
        peak = np.maximum.accumulate(equity)
        drawdown = (peak - equity) / peak
        max_drawdowns[sim] = drawdown.max()

    ruin_level = initial_balance * ruin_threshold
    result = MonteCarloResult(
        n_simulations=n_simulations,
        initial_balance=initial_balance,
        median_final_balance=float(np.median(final_balances)),
        mean_final_balance=float(np.mean(final_balances)),
        p5_final_balance=float(np.percentile(final_balances, 5)),
        p95_final_balance=float(np.percentile(final_balances, 95)),
        median_max_drawdown=float(np.median(max_drawdowns)),
        p95_max_drawdown=float(np.percentile(max_drawdowns, 95)),
        probability_of_ruin=float(np.mean(final_balances < ruin_level)),
        probability_of_profit=float(np.mean(final_balances > initial_balance)),
    )
    return result
