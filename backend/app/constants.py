"""
Named constants extracted from across the codebase.
Centralizes magic numbers for readability, testability, and maintainability.
"""

# ─── MT5 / Order ───────────────────────────────────────────────────────────────

MT5_MAGIC_NUMBER = 234000

# ─── Engine ────────────────────────────────────────────────────────────────────

DEFAULT_OHLCV_BARS = 200
H1_BARS = 50
DEFAULT_ATR_FALLBACK = 10.0
WARMUP_SECONDS = 7200  # 2 hours — reduce lot during initial warmup
WARMUP_MIN_LOT_PCT = 0.25  # minimum 25% lot during warmup

# Multi-timeframe EMA trend thresholds
MTF_EMA_ABOVE = 1.0005  # price must be > EMA * this to confirm uptrend
MTF_EMA_BELOW = 0.9995  # price must be < EMA * this to confirm downtrend

# Paper trading
PAPER_TICKET_START = 900000
PAPER_INITIAL_BALANCE = 10000.0

# ─── Risk Management ──────────────────────────────────────────────────────────

MIN_LOT = 0.01

# Volatility-based lot adjustment thresholds
HIGH_VOL_THRESHOLD = 0.5
LOW_VOL_THRESHOLD = 0.2
HIGH_VOL_LOT_FACTOR = 0.7   # reduce lot in high volatility
LOW_VOL_LOT_FACTOR = 1.2    # increase lot in low volatility

# Slippage & commission defaults
DEFAULT_SLIPPAGE_PIPS = 2.0
DEFAULT_COMMISSION_PCT = 0.002

# Kelly Criterion
KELLY_FRACTION = 0.25   # fractional Kelly for safety
KELLY_MIN_RISK = 0.005  # minimum 0.5% risk
KELLY_MAX_RISK_MULT = 2  # cap at 2x max_risk_per_trade
MIN_KELLY_TRADES = 20   # minimum closed trades before using Kelly

# Minimum win rate to apply Kelly sizing
KELLY_MIN_WIN_RATE = 0.35

# Consecutive loss streak adjustments
STREAK_3_FACTOR = 0.5   # halve lot after 3 consecutive losses
STREAK_2_FACTOR = 0.75  # 75% lot after 2 consecutive losses

# AI confidence adjustments
AI_WORST_HOUR_THRESHOLD_BOOST = 0.15
AI_MAX_THRESHOLD = 0.95

# ─── Trailing Stop & Position Management ──────────────────────────────────────

BREAKEVEN_ATR_MULT = 0.5  # move to breakeven after profit > 0.5x ATR
DEFAULT_ATR_PCT_FALLBACK = 0.3  # fallback ATR% when not recorded at entry

# Default trailing stop settings
DEFAULT_TRAILING_START_ATR = 1.0  # activate trailing after profit > 1x ATR
DEFAULT_TRAILING_STEP_ATR = 0.5   # trail SL at 0.5x ATR behind price

# Adaptive trailing: volatility adjustments
HIGH_VOL_TRAIL_FACTOR = 1.3  # widen trail in high vol
LOW_VOL_TRAIL_FACTOR = 0.7   # tighten trail in low vol

# Profit-lock ratchet
PROFIT_LOCK_ATR_MULT = 2.0   # tighten trail after profit > 2x ATR
TIGHT_TRAIL_STEP_ATR = 0.3   # tighter step once profit-locked

# Scaling in/out
PARTIAL_TP_CLOSE_PCT = 0.5   # close this fraction at partial TP
SCALE_IN_ATR_MULT = 0.5      # add-on entry after price moves this * ATR
SCALE_IN_LOT_FACTOR = 0.5    # add-on lot = original * this
MAX_SCALE_IN_COUNT = 1        # max number of add-on entries per position

# ─── Multi-Timeframe ─────────────────────────────────────────────────────────

H4_BARS = 50
D1_BARS = 30
MTF_ADX_TRENDING_THRESHOLD = 20  # only apply MTF filter when ADX > this

# ─── Strategy Ensemble ────────────────────────────────────────────────────────

ENSEMBLE_BUY_THRESHOLD = 0.6    # weighted sum > this → BUY
ENSEMBLE_SELL_THRESHOLD = -0.6  # weighted sum < this → SELL

# ─── ML Strategy ──────────────────────────────────────────────────────────────

ADX_RANGING_THRESHOLD = 20
ATR_PERCENTILE_LOW = 0.4
RANGING_CONFIDENCE_FACTOR = 0.7

# Dynamic confidence threshold boosts
ML_HIGH_VOL_THRESHOLD_BOOST = 0.10
ML_LOW_VOL_THRESHOLD_BOOST = 0.15

# ─── Circuit Breaker ─────────────────────────────────────────────────────────

DEFAULT_PORTFOLIO_MAX_LOSS = 0.10  # 10% portfolio-level daily loss limit
MIN_TTL_SECONDS = 60  # minimum Redis TTL for daily PnL keys

# Kelly sizing: recent trades window
KELLY_RECENT_TRADES = 50
# Streak detection: recent trades to check
STREAK_RECENT_TRADES = 5

# ─── Regime-Aware Risk ──────────────────────────────────────────────────────

REGIME_LOT_MULTIPLIERS = {
    "trending_high_vol": 0.7,
    "trending_low_vol": 1.0,
    "ranging": 0.5,
    "normal": 1.0,
}

# ─── Event Filter ───────────────────────────────────────────────────────────

EVENT_LOT_FACTOR = 0.5       # halve lot size near high-impact events
EVENT_BLOCK_HOURS = 2        # hours before event to reduce exposure

# ─── Notifications ──────────────────────────────────────────────────────────

LOSING_STREAK_ALERT_THRESHOLD = 3  # consecutive losses before Telegram alert
PREDICTION_FEEDBACK_HOURS = 4      # match predictions within N hours of trade close

# ─── Absolute Drawdown ──────────────────────────────────────────────────────

DEFAULT_MAX_DRAWDOWN_FROM_PEAK = 0.15  # 15% drawdown from peak → halt all trading

# ─── Adaptive Confidence Policy ─────────────────────────────────────────────

CONFIDENCE_DRAWDOWN_5_BOOST = 0.05     # stricter when drawdown > 5%
CONFIDENCE_DRAWDOWN_10_BOOST = 0.10    # much stricter when drawdown > 10%
CONFIDENCE_RANGING_BOOST = 0.05        # stricter in ranging (false signals common)
CONFIDENCE_TRENDING_HV_DISCOUNT = 0.05 # looser in clear high-vol trend
CONFIDENCE_LOW_WINRATE_BOOST = 0.10    # stricter when recent win rate < 40%
CONFIDENCE_LOW_WINRATE_THRESHOLD = 0.40
CONFIDENCE_RECENT_TRADES_WINDOW = 20
