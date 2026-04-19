"""
Volatility Regime Detection — detects market regime and suggests parameter adjustments.
Uses ATR percentile + ADX to classify: trending_high_vol, trending_low_vol, ranging, normal.
"""

from dataclasses import dataclass, field

import numpy as np
from loguru import logger

from app.constants import ADX_RANGING_THRESHOLD, HIGH_VOL_THRESHOLD, LOW_VOL_THRESHOLD

REGIME_LABELS = ("trending_high_vol", "trending_low_vol", "ranging", "normal")


@dataclass
class RegimeResult:
    """Regime detection result with optional probability distribution.

    Backward-compatible: str(result) and comparisons work like a plain string.
    Phase 2 HMM will populate `probabilities`; until then they default to 1.0
    for the detected label and 0.0 for others.
    """

    label: str
    probabilities: dict[str, float] = field(default_factory=dict)

    def __post_init__(self):
        if not self.probabilities:
            self.probabilities = {r: (1.0 if r == self.label else 0.0) for r in REGIME_LABELS}

    # String compatibility — allows `regime == "ranging"` and dict key usage
    def __str__(self) -> str:
        return self.label

    def __eq__(self, other):
        if isinstance(other, str):
            return self.label == other
        if isinstance(other, RegimeResult):
            return self.label == other.label
        return NotImplemented

    def __hash__(self):
        return hash(self.label)


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


@dataclass
class MultiTFRegime:
    m15_regime: str
    h1_regime: str
    h4_regime: str
    composite: str  # dominant regime across timeframes
    suggested_style: str  # "scalp" | "intraday" | "swing"
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
    from app.strategy.indicators import adx as calc_adx
    from app.strategy.indicators import atr as calc_atr

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


# ─── HMM Regime Detection ────────────────────────────────────────────────


class HMMRegimeDetector:
    """Hidden Markov Model for regime detection.

    2-state model: state 0 = low volatility (ranging/trending_low),
                   state 1 = high volatility (trending_high).
    Trained on return volatility features.
    """

    def __init__(self, n_states: int = 2):
        self.n_states = n_states
        self.model = None
        self._fitted = False
        self._state_labels = {
            0: "ranging",  # low vol state
            1: "trending_high_vol",  # high vol state
        }

    def fit(self, prices: np.ndarray, min_samples: int = 100) -> bool:
        """Fit HMM on price series.

        Args:
            prices: price array (newest last)
            min_samples: minimum number of observations

        Returns:
            True if fitting succeeded
        """
        if len(prices) < min_samples:
            logger.debug(f"HMM: insufficient data ({len(prices)} < {min_samples})")
            return False

        try:
            from hmmlearn.hmm import GaussianHMM

            # Features: |return|, rolling_std(5)
            returns = np.diff(np.log(prices))
            abs_returns = np.abs(returns)

            # Rolling std
            window = 5
            rolling_std = np.array([returns[max(0, i - window) : i + 1].std() for i in range(len(returns))])

            features = np.column_stack([abs_returns, rolling_std])

            self.model = GaussianHMM(
                n_components=self.n_states,
                covariance_type="full",
                n_iter=100,
                random_state=42,
            )
            self.model.fit(features)
            self._fitted = True

            # Assign labels: state with higher mean volatility = trending_high_vol
            means = self.model.means_[:, 0]  # mean of |returns|
            if means[0] > means[1]:
                self._state_labels = {0: "trending_high_vol", 1: "ranging"}
            else:
                self._state_labels = {0: "ranging", 1: "trending_high_vol"}

            logger.info(f"HMM fitted: {self.n_states} states, labels={self._state_labels}")
            return True

        except Exception as e:
            logger.warning(f"HMM fitting failed: {e}")
            self._fitted = False
            return False

    def predict(self, prices: np.ndarray) -> RegimeResult:
        """Predict current regime with probabilities.

        Returns:
            RegimeResult with label and probability distribution
        """
        if not self._fitted or self.model is None:
            return RegimeResult("normal")

        try:
            returns = np.diff(np.log(prices))
            if len(returns) < 5:
                return RegimeResult("normal")

            abs_returns = np.abs(returns)
            window = 5
            rolling_std = np.array([returns[max(0, i - window) : i + 1].std() for i in range(len(returns))])
            features = np.column_stack([abs_returns, rolling_std])

            # Get state probabilities for last observation
            posteriors = self.model.predict_proba(features)
            last_probs = posteriors[-1]

            # Map to regime labels
            probabilities = {}
            for state_idx, prob in enumerate(last_probs):
                label = self._state_labels.get(state_idx, "normal")
                probabilities[label] = round(float(prob), 4)

            # Fill missing labels
            for label in REGIME_LABELS:
                if label not in probabilities:
                    probabilities[label] = 0.0

            # Dominant state
            dominant_state = int(np.argmax(last_probs))
            dominant_label = self._state_labels.get(dominant_state, "normal")

            return RegimeResult(label=dominant_label, probabilities=probabilities)

        except Exception as e:
            logger.warning(f"HMM prediction failed: {e}")
            return RegimeResult("normal")
