"""
MCP tools for adaptive strategy selection and template-based strategy generation.

Two capabilities:
1. **Adaptive selection**: Choose best strategy for current market regime
2. **Template generation**: Create new strategy configurations from a parameter template

Does NOT generate arbitrary Python code — uses a safe template system with
predefined indicator combinations and validated parameter ranges.
"""

import json
from typing import Any

# ─── Known Strategies & Their Regime Suitability ─────────────────────────────

STRATEGY_PROFILES: dict[str, dict[str, Any]] = {
    "ema_crossover": {
        "description": "EMA crossover with fast/slow period",
        "best_regime": ["trending"],
        "params": {"fast_period": 20, "slow_period": 50},
        "param_ranges": {"fast_period": (5, 50), "slow_period": (20, 200)},
    },
    "rsi_filter": {
        "description": "RSI overbought/oversold with threshold",
        "best_regime": ["ranging"],
        "params": {"period": 14, "overbought": 70, "oversold": 30},
        "param_ranges": {"period": (7, 28), "overbought": (65, 85), "oversold": (15, 35)},
    },
    "breakout": {
        "description": "Price breakout above/below N-period high/low",
        "best_regime": ["trending", "volatile"],
        "params": {"lookback": 20, "volume_filter": True},
        "param_ranges": {"lookback": (10, 50)},
    },
    "mean_reversion": {
        "description": "Bollinger Band mean reversion with RSI confirmation",
        "best_regime": ["ranging"],
        "params": {"bb_period": 20, "bb_std": 2.0, "min_bandwidth": 0.01},
        "param_ranges": {"bb_period": (10, 30), "bb_std": (1.5, 3.0), "min_bandwidth": (0.005, 0.03)},
    },
    "ml_signal": {
        "description": "LightGBM ML model prediction",
        "best_regime": ["trending", "ranging", "volatile"],
        "params": {"confidence_threshold": 0.6},
        "param_ranges": {"confidence_threshold": (0.5, 0.9)},
    },
    "ensemble": {
        "description": "Weighted vote from multiple strategies",
        "best_regime": ["transitional"],
        "params": {"composition": "ema_crossover:0.3,breakout:0.3,mean_reversion:0.2,rsi_filter:0.2"},
    },
}


def get_strategy_profiles() -> dict:
    """Get all available strategy profiles with their regime suitability.

    Returns:
        Dict with strategy profiles including descriptions, best regimes, and parameters.
    """
    return {
        "strategies": STRATEGY_PROFILES,
        "total": len(STRATEGY_PROFILES),
    }


def recommend_strategy(regime: str, symbol: str) -> dict:
    """Recommend the best strategy for the current market regime.

    Args:
        regime: Market regime (trending, ranging, volatile, transitional)
        symbol: Trading symbol (for symbol-specific adjustments)

    Returns:
        Dict with recommended strategy name, params, and alternatives.
    """
    best_match: list[dict] = []
    alternatives: list[dict] = []

    for name, profile in STRATEGY_PROFILES.items():
        if regime in profile.get("best_regime", []):
            best_match.append(
                {
                    "name": name,
                    "description": profile["description"],
                    "params": profile["params"],
                }
            )
        else:
            alternatives.append(
                {
                    "name": name,
                    "description": profile["description"],
                }
            )

    primary = best_match[0] if best_match else {"name": "ensemble", "params": STRATEGY_PROFILES["ensemble"]["params"]}

    return {
        "regime": regime,
        "symbol": symbol,
        "recommended": primary,
        "alternatives": best_match[1:] if len(best_match) > 1 else [],
        "other_strategies": alternatives,
    }


def generate_strategy_config(
    base_strategy: str,
    param_overrides: dict | None = None,
    name: str | None = None,
) -> dict:
    """Generate a strategy configuration from a template with custom parameters.

    Uses predefined strategy templates with validated parameter ranges.
    Does NOT generate arbitrary code — uses safe parameter injection.

    Args:
        base_strategy: Base strategy name to customize (e.g., "ema_crossover")
        param_overrides: Dict of parameter overrides (validated against ranges)
        name: Optional custom name for the generated config

    Returns:
        Dict with strategy config ready to use with BotEngine.update_strategy().
    """
    if base_strategy not in STRATEGY_PROFILES:
        return {"error": f"Unknown strategy: {base_strategy}. Available: {list(STRATEGY_PROFILES.keys())}"}

    profile = STRATEGY_PROFILES[base_strategy]
    params = dict(profile["params"])
    validation_errors: list[str] = []

    # Apply overrides with validation
    if param_overrides:
        ranges = profile.get("param_ranges", {})
        for key, value in param_overrides.items():
            if key not in params:
                validation_errors.append(f"Unknown parameter '{key}' for {base_strategy}")
                continue
            if key in ranges:
                min_val, max_val = ranges[key]
                if isinstance(value, int | float) and not (min_val <= value <= max_val):
                    validation_errors.append(f"'{key}' = {value} out of range [{min_val}, {max_val}]")
                    continue
            params[key] = value

    if validation_errors:
        return {"error": "Validation failed", "errors": validation_errors}

    config_name = name or f"{base_strategy}_custom"

    return {
        "name": config_name,
        "base_strategy": base_strategy,
        "params": params,
        "description": f"Custom {profile['description']}",
        "usage": f"Apply via: update_strategy('{base_strategy}', {json.dumps(params)})",
    }


def generate_ensemble_config(
    weights: dict[str, float],
    name: str = "custom_ensemble",
) -> dict:
    """Generate a custom ensemble strategy with specified weights.

    Args:
        weights: Dict of strategy_name -> weight (must sum to ~1.0)
            e.g. {"ema_crossover": 0.4, "breakout": 0.3, "mean_reversion": 0.3}
        name: Name for the ensemble config

    Returns:
        Dict with ensemble config ready for use.
    """
    # Validate strategy names
    unknown = [s for s in weights if s not in STRATEGY_PROFILES or s == "ensemble"]
    if unknown:
        return {"error": f"Unknown strategies: {unknown}"}

    # Validate weights
    total = sum(weights.values())
    if not (0.95 <= total <= 1.05):
        return {"error": f"Weights must sum to ~1.0, got {total:.2f}"}

    for w in weights.values():
        if w < 0 or w > 1:
            return {"error": "Each weight must be between 0 and 1"}

    composition = ",".join(f"{name}:{w}" for name, w in weights.items())

    return {
        "name": name,
        "base_strategy": "ensemble",
        "params": {"composition": composition},
        "weights": weights,
        "usage": f"Apply via: update_strategy('ensemble', {{'composition': '{composition}'}})",
    }
