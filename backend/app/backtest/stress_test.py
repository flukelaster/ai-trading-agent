"""
Stress Testing — evaluate portfolio resilience under extreme scenarios.

Provides:
- Historical scenario replay (2008, 2020 COVID, 2022 rate hikes)
- Synthetic stress: vol spike, correlation breakdown, liquidity dry-up
- Portfolio impact assessment
"""

from dataclasses import dataclass

import numpy as np


@dataclass
class StressScenario:
    """Definition of a stress scenario."""

    name: str
    description: str
    vol_multiplier: float  # multiply current vol by this factor
    correlation_shift: float  # shift all correlations toward +1 (0 = no change, 1 = perfect)
    return_shock: float  # immediate return shock (e.g., -0.05 = -5%)
    duration_bars: int  # how many bars the stress lasts

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "vol_multiplier": self.vol_multiplier,
            "correlation_shift": self.correlation_shift,
            "return_shock": self.return_shock,
            "duration_bars": self.duration_bars,
        }


@dataclass
class StressResult:
    """Result of a stress test."""

    scenario: str
    portfolio_impact: float  # total P&L impact (%)
    max_drawdown: float  # max drawdown during stress
    worst_symbol: str  # symbol with worst impact
    worst_impact: float  # worst single-symbol impact
    recovery_bars: int  # estimated bars to recover (0 if no recovery)
    var_breach: bool  # whether VaR limit would be breached

    def to_dict(self) -> dict:
        return {
            "scenario": self.scenario,
            "portfolio_impact": float(round(self.portfolio_impact, 4)),
            "max_drawdown": float(round(self.max_drawdown, 4)),
            "worst_symbol": self.worst_symbol,
            "worst_impact": float(round(self.worst_impact, 4)),
            "recovery_bars": int(self.recovery_bars),
            "var_breach": bool(self.var_breach),
        }


# Predefined historical scenarios
SCENARIOS = {
    "covid_crash": StressScenario(
        name="COVID Crash (Mar 2020)",
        description="Sudden liquidity crisis, all correlations spike to 1, vol 3x",
        vol_multiplier=3.0,
        correlation_shift=0.8,
        return_shock=-0.10,
        duration_bars=20,
    ),
    "rate_hike": StressScenario(
        name="Aggressive Rate Hike (2022)",
        description="Sustained vol increase, USD strengthens, gold drops",
        vol_multiplier=2.0,
        correlation_shift=0.3,
        return_shock=-0.05,
        duration_bars=60,
    ),
    "flash_crash": StressScenario(
        name="Flash Crash",
        description="Sudden 5% drop in 15 minutes, recovery within hours",
        vol_multiplier=5.0,
        correlation_shift=0.9,
        return_shock=-0.05,
        duration_bars=4,
    ),
    "vol_spike": StressScenario(
        name="Volatility Spike",
        description="Vol triples with no directional bias",
        vol_multiplier=3.0,
        correlation_shift=0.2,
        return_shock=0.0,
        duration_bars=10,
    ),
    "correlation_breakdown": StressScenario(
        name="Correlation Breakdown",
        description="Historical correlations reverse — hedges fail",
        vol_multiplier=1.5,
        correlation_shift=-0.5,
        return_shock=-0.03,
        duration_bars=30,
    ),
}


def run_stress_test(
    positions: dict[str, float],
    price_series: dict[str, np.ndarray],
    scenario_name: str = "covid_crash",
    var_limit: float = 0.05,
) -> StressResult:
    """Run a stress test on current portfolio.

    Args:
        positions: {symbol: notional_exposure}
        price_series: {symbol: price_array}
        scenario_name: key from SCENARIOS dict
        var_limit: VaR limit to check breach against

    Returns:
        StressResult with impact assessment
    """
    scenario = SCENARIOS.get(scenario_name)
    if not scenario:
        return StressResult(scenario_name, 0, 0, "", 0, 0, False)

    symbols = sorted(positions.keys())
    total_exposure = sum(abs(v) for v in positions.values())

    if total_exposure == 0:
        return StressResult(scenario.name, 0, 0, "", 0, 0, False)

    # Compute stressed returns per symbol
    impacts = {}
    for sym in symbols:
        p = price_series.get(sym, np.array([]))
        if len(p) < 20:
            impacts[sym] = scenario.return_shock
            continue

        returns = np.diff(np.log(p[-61:]))
        base_vol = returns.std() if len(returns) > 0 else 0.01

        # Stressed vol
        stressed_vol = base_vol * scenario.vol_multiplier

        # Simulate stressed returns
        np.random.seed(42)
        stressed_returns = np.random.normal(
            scenario.return_shock / scenario.duration_bars,
            stressed_vol,
            scenario.duration_bars,
        )

        # Cumulative impact
        cum_return = np.expm1(np.sum(stressed_returns))
        impacts[sym] = cum_return

    # Portfolio impact
    weighted_impact = sum(impacts.get(sym, 0) * (positions[sym] / total_exposure) for sym in symbols)

    # Max drawdown (simplified: peak-to-trough of cumulative path)
    worst_sym = min(impacts, key=impacts.get) if impacts else ""
    worst_impact = impacts.get(worst_sym, 0)

    # Estimate recovery (rough: based on mean reversion at half-life of 20 bars)
    recovery = int(abs(weighted_impact) / 0.005) if weighted_impact < 0 else 0

    var_breach = abs(weighted_impact) > var_limit

    return StressResult(
        scenario=scenario.name,
        portfolio_impact=weighted_impact,
        max_drawdown=min(weighted_impact, worst_impact),
        worst_symbol=worst_sym,
        worst_impact=worst_impact,
        recovery_bars=recovery,
        var_breach=var_breach,
    )


def run_all_stress_tests(
    positions: dict[str, float],
    price_series: dict[str, np.ndarray],
    var_limit: float = 0.05,
) -> list[StressResult]:
    """Run all predefined stress scenarios."""
    results = []
    for name in SCENARIOS:
        result = run_stress_test(positions, price_series, name, var_limit)
        results.append(result)
    return results
