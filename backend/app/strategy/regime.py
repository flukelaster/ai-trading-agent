"""
Volatility Regime Detection — detects market regime and suggests parameter adjustments.
Uses ATR percentile + ADX to classify: trending_high_vol, trending_low_vol, ranging, normal.
"""

from app.constants import ADX_RANGING_THRESHOLD, HIGH_VOL_THRESHOLD, LOW_VOL_THRESHOLD


def detect_regime(atr_pct: float, adx_value: float) -> str:
    """
    Detect current market regime.

    Args:
        atr_pct: ATR as percentage of price (e.g., 0.5 = 0.5%)
        adx_value: ADX(14) value (0-100)

    Returns:
        One of: "trending_high_vol", "trending_low_vol", "ranging", "normal"
    """
    is_trending = adx_value >= ADX_RANGING_THRESHOLD
    is_high_vol = atr_pct > HIGH_VOL_THRESHOLD
    is_low_vol = atr_pct < LOW_VOL_THRESHOLD

    if is_trending and is_high_vol:
        return "trending_high_vol"
    elif is_trending and is_low_vol:
        return "trending_low_vol"
    elif not is_trending:
        return "ranging"
    else:
        return "normal"


# Strategy parameter adjustments per regime
REGIME_ADJUSTMENTS = {
    "trending_high_vol": {
        # Wider SL, wider trail, breakout-friendly
        "sl_atr_mult_factor": 1.3,
        "tp_atr_mult_factor": 1.5,
        "description": "Strong trend + high volatility — wider stops, let profits run",
    },
    "trending_low_vol": {
        # Tighter entries, normal SL
        "sl_atr_mult_factor": 1.0,
        "tp_atr_mult_factor": 1.2,
        "description": "Trend + low volatility — standard stops, slightly wider TP",
    },
    "ranging": {
        # Mean-reversion friendly, tighter SL/TP
        "sl_atr_mult_factor": 0.8,
        "tp_atr_mult_factor": 0.8,
        "description": "Ranging market — tighter stops and targets",
    },
    "normal": {
        # No adjustment
        "sl_atr_mult_factor": 1.0,
        "tp_atr_mult_factor": 1.0,
        "description": "Normal conditions — use base parameters",
    },
}


def get_regime_adjustments(regime: str) -> dict:
    """Get SL/TP adjustment factors for the given regime."""
    return REGIME_ADJUSTMENTS.get(regime, REGIME_ADJUSTMENTS["normal"])


# ─── Multi-Timeframe Regime ────────────────────────────────────────────────

from collections import Counter
from dataclasses import dataclass


@dataclass
class MultiTFRegime:
    m15_regime: str
    h1_regime: str
    h4_regime: str
    composite: str          # dominant regime across timeframes
    suggested_style: str    # "scalp" | "intraday" | "swing"
    agreement_score: float  # 0.0-1.0 how aligned the TFs are

    def to_dict(self) -> dict:
        return {
            "m15": self.m15_regime,
            "h1": self.h1_regime,
            "h4": self.h4_regime,
            "composite": self.composite,
            "style": self.suggested_style,
            "agreement": self.agreement_score,
        }


# (composite_regime, high_agreement) → trading style
STYLE_MAP = {
    ("trending_high_vol", True): "swing",
    ("trending_high_vol", False): "intraday",
    ("trending_low_vol", True): "intraday",
    ("trending_low_vol", False): "scalp",
    ("ranging", True): "scalp",
    ("ranging", False): "scalp",
    ("normal", True): "intraday",
    ("normal", False): "scalp",
}


def _compute_composite(regimes: list[str]) -> tuple[str, float]:
    """Pick dominant regime via majority vote. Returns (regime, agreement_score)."""
    counts = Counter(regimes)
    dominant, top_count = counts.most_common(1)[0]
    agreement = top_count / len(regimes)
    return dominant, round(agreement, 2)


def _regime_from_df(df) -> str:
    """Detect regime from a single-timeframe OHLCV DataFrame."""
    if df is None or df.empty or len(df) < 16:
        return "normal"
    from app.strategy.indicators import atr as calc_atr, adx as calc_adx
    atr_val = calc_atr(df["high"], df["low"], df["close"]).iloc[-1]
    adx_result = calc_adx(df["high"], df["low"], df["close"])
    adx_val = adx_result["adx"].iloc[-1] if "adx" in adx_result else 20
    price = df["close"].iloc[-1]
    atr_pct = atr_val / price if price > 0 else 0
    return detect_regime(atr_pct, adx_val)


async def detect_multi_tf_regime(market_data, symbol: str) -> MultiTFRegime:
    """Fetch M15+H1+H4, detect regime on each, return composite."""
    import asyncio
    from app.constants import DEFAULT_OHLCV_BARS

    try:
        m15_df, h1_df, h4_df = await asyncio.gather(
            market_data.get_ohlcv(symbol, "M15", DEFAULT_OHLCV_BARS),
            market_data.get_ohlcv(symbol, "H1", 50),
            market_data.get_ohlcv(symbol, "H4", 50),
        )
    except Exception:
        return MultiTFRegime("normal", "normal", "normal", "normal", "intraday", 1.0)

    m15 = _regime_from_df(m15_df)
    h1 = _regime_from_df(h1_df)
    h4 = _regime_from_df(h4_df)

    composite, agreement = _compute_composite([m15, h1, h4])
    high_agreement = agreement >= 0.67
    style = STYLE_MAP.get((composite, high_agreement), "intraday")

    return MultiTFRegime(m15, h1, h4, composite, style, agreement)
