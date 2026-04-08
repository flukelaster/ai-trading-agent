from app.strategy.base import BaseStrategy
from app.strategy.breakout import BreakoutStrategy
from app.strategy.ema_crossover import EMACrossoverStrategy
from app.strategy.rsi_filter import RSIFilterStrategy

STRATEGIES: dict[str, type[BaseStrategy]] = {
    "ema_crossover": EMACrossoverStrategy,
    "rsi_filter": RSIFilterStrategy,
    "breakout": BreakoutStrategy,
}


def get_strategy(name: str, params: dict | None = None) -> BaseStrategy:
    cls = STRATEGIES.get(name)
    if cls is None:
        raise ValueError(f"Unknown strategy: {name}. Available: {list(STRATEGIES.keys())}")
    return cls(**(params or {}))
