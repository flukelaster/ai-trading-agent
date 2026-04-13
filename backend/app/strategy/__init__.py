from pathlib import Path

from app.strategy.base import BaseStrategy
from app.strategy.breakout import BreakoutStrategy
from app.strategy.dca import DCAStrategy
from app.strategy.ema_crossover import EMACrossoverStrategy
from app.strategy.grid import GridStrategy
from app.strategy.mean_reversion import MeanReversionStrategy
from app.strategy.momentum_rank import MomentumRankStrategy
from app.strategy.pair_spread import PairSpreadStrategy
from app.strategy.risk_parity import RiskParityStrategy
from app.strategy.rsi_filter import RSIFilterStrategy

STRATEGIES: dict[str, type[BaseStrategy]] = {
    "ema_crossover": EMACrossoverStrategy,
    "rsi_filter": RSIFilterStrategy,
    "breakout": BreakoutStrategy,
    "mean_reversion": MeanReversionStrategy,
    "dca": DCAStrategy,
    "grid": GridStrategy,
    "risk_parity": RiskParityStrategy,
    "momentum_rank": MomentumRankStrategy,
    "pair_spread": PairSpreadStrategy,
}

# Conditionally register ML strategy if model exists
try:
    from app.strategy.ml_strategy import MLStrategy
    STRATEGIES["ml_signal"] = MLStrategy
except ImportError:
    pass  # lightgbm not installed


def get_strategy(name: str, params: dict | None = None, symbol: str = "GOLD") -> BaseStrategy:
    # Handle ensemble strategy specially
    if name == "ensemble":
        return _build_ensemble(params, symbol)

    cls = STRATEGIES.get(name)
    if cls is None:
        raise ValueError(f"Unknown strategy: {name}. Available: {list(STRATEGIES.keys())}")
    kwargs = dict(params or {})
    # Pass symbol to strategies that need it (ML + quant cross-asset)
    if name in ("ml_signal", "risk_parity", "momentum_rank", "pair_spread"):
        kwargs.setdefault("symbol", symbol)
    return cls(**kwargs)


def _build_ensemble(params: dict | None, symbol: str) -> BaseStrategy:
    """Build an ensemble strategy from config string or params dict."""
    from app.config import settings
    from app.strategy.ensemble import EnsembleStrategy

    config_str = (params or {}).get("strategies") or settings.ensemble_strategies
    if not config_str:
        raise ValueError("Ensemble requires 'strategies' param, e.g. 'ema_crossover:0.3,breakout:0.7'")

    strategies = []
    for part in config_str.split(","):
        part = part.strip()
        if ":" in part:
            name, weight = part.rsplit(":", 1)
            weight = float(weight)
        else:
            name = part
            weight = 1.0
        sub = get_strategy(name.strip(), symbol=symbol)
        strategies.append((sub, weight))

    return EnsembleStrategy(strategies, symbol=symbol)
