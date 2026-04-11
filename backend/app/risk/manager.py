"""
Risk Manager — lot sizing, SL/TP calculation, trade permission checks.
"""

from dataclasses import dataclass
from loguru import logger


@dataclass
class SLTPResult:
    sl: float
    tp: float


class RiskManager:
    def __init__(
        self,
        max_risk_per_trade: float = 0.01,
        max_daily_loss: float = 0.03,
        max_concurrent_trades: int = 3,
        max_lot: float = 1.0,
        use_ai_filter: bool = True,
        ai_confidence_threshold: float = 0.7,
        pip_value: float = 1.0,
        price_decimals: int = 2,
        sl_atr_mult: float = 1.5,
        tp_atr_mult: float = 2.0,
    ):
        self.max_risk_per_trade = max_risk_per_trade
        self.max_daily_loss = max_daily_loss
        self.max_concurrent_trades = max_concurrent_trades
        self.max_lot = max_lot
        self.use_ai_filter = use_ai_filter
        self.ai_confidence_threshold = ai_confidence_threshold
        self.pip_value = pip_value
        self.price_decimals = price_decimals
        self.sl_atr_mult = sl_atr_mult
        self.tp_atr_mult = tp_atr_mult

    def calculate_lot_size(
        self, balance: float, sl_pips: float, pip_value: float | None = None,
        atr_pct: float | None = None, slippage_pips: float = 2.0, commission_pct: float = 0.002,
    ) -> float:
        if sl_pips <= 0:
            return 0.01
        pv = pip_value if pip_value is not None else self.pip_value

        # Account for slippage in effective SL distance
        effective_sl = sl_pips + slippage_pips

        # Risk budget minus estimated commission
        risk_budget = (balance * self.max_risk_per_trade) * (1 - commission_pct)
        lot = risk_budget / (effective_sl * pv * 100)

        # Volatility adjustment
        if atr_pct is not None:
            if atr_pct > 0.5:    # high volatility
                lot *= 0.7
            elif atr_pct < 0.2:  # low volatility
                lot *= 1.2

        lot = round(min(lot, self.max_lot), 2)
        return max(lot, 0.01)

    def calculate_kelly_size(
        self, balance: float, sl_pips: float,
        win_rate: float, avg_win: float, avg_loss: float,
        pip_value: float | None = None,
    ) -> float:
        """Kelly Criterion position sizing (fractional Kelly = 0.25x for safety)."""
        if avg_loss <= 0 or win_rate <= 0:
            return self.calculate_lot_size(balance, sl_pips, pip_value)

        # Kelly fraction: f* = (p * b - q) / b
        # where p=win_rate, q=1-p, b=avg_win/avg_loss
        b = avg_win / avg_loss
        q = 1 - win_rate
        kelly = (win_rate * b - q) / b

        # Fractional Kelly (25%) for safety
        kelly = max(kelly * 0.25, 0.005)  # min 0.5% risk
        kelly = min(kelly, self.max_risk_per_trade * 2)  # cap at 2x max risk

        pv = pip_value if pip_value is not None else self.pip_value
        if sl_pips <= 0:
            return 0.01
        lot = (balance * kelly) / (sl_pips * pv * 100)
        lot = round(min(lot, self.max_lot), 2)
        return max(lot, 0.01)

    def adjust_for_streak(self, base_lot: float, consecutive_losses: int, consecutive_wins: int) -> float:
        """Reduce lot after consecutive losses, restore after wins."""
        if consecutive_losses >= 3:
            return round(base_lot * 0.5, 2)  # halve after 3 losses
        elif consecutive_losses >= 2:
            return round(base_lot * 0.75, 2)  # 75% after 2 losses
        return max(base_lot, 0.01)

    def calculate_sl_tp(
        self, entry_price: float, signal: int, atr: float,
        sl_mult: float | None = None, tp_mult: float | None = None,
    ) -> SLTPResult:
        sl_m = sl_mult if sl_mult is not None else self.sl_atr_mult
        tp_m = tp_mult if tp_mult is not None else self.tp_atr_mult
        if signal == 1:  # BUY
            sl = entry_price - (atr * sl_m)
            tp = entry_price + (atr * tp_m)
        else:  # SELL
            sl = entry_price + (atr * sl_m)
            tp = entry_price - (atr * tp_m)
        return SLTPResult(
            sl=round(sl, self.price_decimals),
            tp=round(tp, self.price_decimals),
        )

    def can_open_trade(
        self,
        current_positions: int,
        daily_pnl: float,
        balance: float,
        signal: int = 0,
        ai_sentiment: dict | None = None,
        trade_patterns: dict | None = None,
    ) -> tuple[bool, str]:
        # Check max concurrent trades
        if current_positions >= self.max_concurrent_trades:
            return False, f"Max concurrent trades reached ({self.max_concurrent_trades})"

        # Check daily loss limit
        max_loss = balance * self.max_daily_loss
        if daily_pnl <= -max_loss:
            return False, f"Daily loss limit reached ({daily_pnl:.2f} <= -{max_loss:.2f})"

        # Adjust confidence threshold based on trade patterns
        effective_threshold = self.ai_confidence_threshold
        if trade_patterns:
            from datetime import datetime, timezone
            current_hour = datetime.now(timezone.utc).hour
            worst_hours = trade_patterns.get("worst_hours", [])
            if current_hour in worst_hours:
                effective_threshold = min(effective_threshold + 0.15, 0.95)

        # AI sentiment filter (optional)
        if self.use_ai_filter and ai_sentiment and signal != 0:
            confidence = ai_sentiment.get("confidence", 0)
            label = ai_sentiment.get("label", "neutral")

            if confidence >= effective_threshold:
                if signal == 1 and label == "bearish":
                    return False, f"AI sentiment bearish (confidence: {confidence:.0%}) — BUY signal filtered"
                if signal == -1 and label == "bullish":
                    return False, f"AI sentiment bullish (confidence: {confidence:.0%}) — SELL signal filtered"

        return True, "OK"
