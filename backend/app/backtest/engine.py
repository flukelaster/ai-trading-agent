"""
Backtest Engine — bar-by-bar simulation of trading strategies.
"""

from bisect import bisect_right
from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd
from loguru import logger

from app.constants import DEFAULT_COMMISSION_PCT, DEFAULT_SLIPPAGE_PIPS
from app.risk.manager import RiskManager
from app.strategy.base import BaseStrategy


@dataclass
class BacktestResult:
    trades: list[dict] = field(default_factory=list)
    total_trades: int = 0
    win_rate: float = 0.0
    total_profit: float = 0.0
    total_gross_profit: float = 0.0
    max_drawdown: float = 0.0
    sharpe_ratio: float = 0.0
    profit_factor: float = 0.0
    equity_curve: list[float] = field(default_factory=list)
    ai_filtered_trades: int = 0

    def to_dict(self) -> dict:
        return {
            "total_trades": self.total_trades,
            "win_rate": round(self.win_rate, 4),
            "total_profit": round(self.total_profit, 2),
            "total_gross_profit": round(self.total_gross_profit, 2),
            "max_drawdown": round(self.max_drawdown, 4),
            "sharpe_ratio": round(self.sharpe_ratio, 4),
            "profit_factor": round(self.profit_factor, 4),
            "equity_curve": self.equity_curve,
            "ai_filtered_trades": self.ai_filtered_trades,
            "trades": self.trades[:100],
        }


class BacktestEngine:
    def __init__(
        self,
        strategy: BaseStrategy,
        risk_manager: RiskManager,
        initial_balance: float = 10000.0,
        include_costs: bool = False,
        spread_pips: float = DEFAULT_SLIPPAGE_PIPS,
        commission_pct: float = DEFAULT_COMMISSION_PCT,
    ):
        self.strategy = strategy
        self.risk_manager = risk_manager
        self.initial_balance = initial_balance
        self.include_costs = include_costs
        self.spread_pips = spread_pips
        self.commission_pct = commission_pct

    def run(
        self,
        df: pd.DataFrame,
        use_ai_filter: bool = False,
        sentiment_data: list[dict] | None = None,
        signals_override: pd.Series | None = None,
    ) -> BacktestResult:
        if len(df) < self.strategy.min_bars_required:
            logger.warning(f"Not enough bars: {len(df)} < {self.strategy.min_bars_required}")
            return BacktestResult()

        # Calculate signals on full dataset
        df = self.strategy.calculate(df)

        # Override signals (used by permutation test)
        if signals_override is not None:
            df["signal"] = signals_override.values

        # Pre-sort sentiment data for binary search lookup
        sorted_sentiments: list[dict] = []
        sentiment_times: list[datetime] = []
        if use_ai_filter and sentiment_data:
            sorted_sentiments = sorted(sentiment_data, key=lambda s: s["created_at"])
            sentiment_times = [s["created_at"] for s in sorted_sentiments]
            logger.info(f"Loaded {len(sorted_sentiments)} historical sentiment records for backtest")

        balance = self.initial_balance
        equity_curve = [balance]
        trades = []
        open_trade = None
        ai_filtered = 0

        for i in range(self.strategy.min_bars_required, len(df)):
            row = df.iloc[i]
            prev_row = df.iloc[i - 1]

            # Check if open trade SL/TP hit
            if open_trade:
                hit = self._check_sl_tp(open_trade, row)
                if hit:
                    profit = hit["profit"]
                    balance += profit
                    open_trade["close_price"] = hit["close_price"]
                    open_trade["close_time"] = str(row.name)
                    open_trade["profit"] = profit
                    trades.append(open_trade)
                    open_trade = None

            # Check for new signal (only if no open trade)
            signal = int(prev_row.get("signal", 0))
            if signal != 0 and open_trade is None:
                # AI sentiment filter using historical data
                if use_ai_filter and sorted_sentiments:
                    candle_time = pd.Timestamp(row.name).to_pydatetime().replace(tzinfo=None)
                    sentiment = self._lookup_sentiment(candle_time, sorted_sentiments, sentiment_times)
                    if sentiment:
                        confidence = sentiment["confidence"]
                        label = sentiment["sentiment_label"]
                        if confidence >= self.risk_manager.ai_confidence_threshold:
                            if signal == 1 and label == "bearish":
                                ai_filtered += 1
                                continue
                            if signal == -1 and label == "bullish":
                                ai_filtered += 1
                                continue

                atr = prev_row.get("atr", 10.0)
                if pd.isna(atr) or atr <= 0:
                    continue

                entry_price = row["open"]
                # Apply spread cost: BUY at ask (higher), SELL at bid (lower)
                if self.include_costs:
                    half_spread = self.spread_pips * 0.5
                    if signal == 1:
                        entry_price += half_spread
                    else:
                        entry_price -= half_spread
                sl_tp = self.risk_manager.calculate_sl_tp(entry_price, signal, atr)
                sl_pips = abs(entry_price - sl_tp.sl)
                lot = self.risk_manager.calculate_lot_size(balance, sl_pips)

                open_trade = {
                    "type": "BUY" if signal == 1 else "SELL",
                    "entry_price": entry_price,
                    "sl": sl_tp.sl,
                    "tp": sl_tp.tp,
                    "lot": lot,
                    "open_time": str(row.name),
                }

            equity_curve.append(balance + (self._unrealized_pnl(open_trade, row) if open_trade else 0))

        # Close any remaining open trade at last bar's close
        if open_trade:
            last = df.iloc[-1]
            profit = self._calc_profit(open_trade, last["close"])
            balance += profit
            open_trade["close_price"] = last["close"]
            open_trade["close_time"] = str(last.name)
            open_trade["profit"] = profit
            trades.append(open_trade)
            equity_curve[-1] = balance

        return self._build_result(trades, equity_curve, ai_filtered)

    @staticmethod
    def _lookup_sentiment(
        candle_time: datetime,
        sorted_sentiments: list[dict],
        sentiment_times: list[datetime],
    ) -> dict | None:
        """Find the most recent sentiment record before candle_time (binary search)."""
        idx = bisect_right(sentiment_times, candle_time) - 1
        if idx < 0:
            return None
        return sorted_sentiments[idx]

    def _check_sl_tp(self, trade: dict, row) -> dict | None:
        if trade["type"] == "BUY":
            if row["low"] <= trade["sl"]:
                return {"close_price": trade["sl"], "profit": self._calc_profit(trade, trade["sl"])}
            if row["high"] >= trade["tp"]:
                return {"close_price": trade["tp"], "profit": self._calc_profit(trade, trade["tp"])}
        else:  # SELL
            if row["high"] >= trade["sl"]:
                return {"close_price": trade["sl"], "profit": self._calc_profit(trade, trade["sl"])}
            if row["low"] <= trade["tp"]:
                return {"close_price": trade["tp"], "profit": self._calc_profit(trade, trade["tp"])}
        return None

    def _calc_profit(self, trade: dict, close_price: float) -> float:
        if trade["type"] == "BUY":
            pips = close_price - trade["entry_price"]
        else:
            pips = trade["entry_price"] - close_price
        gross = pips * trade["lot"] * 100
        if self.include_costs:
            commission = abs(close_price * trade["lot"] * 100) * self.commission_pct
            return round(gross - commission, 2)
        return round(gross, 2)

    def _unrealized_pnl(self, trade: dict, row) -> float:
        return self._calc_profit(trade, row["close"])

    def _build_result(self, trades: list, equity_curve: list, ai_filtered: int) -> BacktestResult:
        if not trades:
            return BacktestResult(equity_curve=equity_curve, ai_filtered_trades=ai_filtered)

        wins = [t for t in trades if t["profit"] > 0]
        losses = [t for t in trades if t["profit"] <= 0]
        total_profit = sum(t["profit"] for t in trades)
        gross_profit = sum(t["profit"] for t in wins) if wins else 0
        gross_loss = abs(sum(t["profit"] for t in losses)) if losses else 0

        # Max drawdown
        peak = equity_curve[0]
        max_dd = 0
        for val in equity_curve:
            peak = max(peak, val)
            dd = (peak - val) / peak if peak > 0 else 0
            max_dd = max(max_dd, dd)

        # Sharpe ratio (simplified)
        returns = []
        for i in range(1, len(equity_curve)):
            r = (equity_curve[i] - equity_curve[i - 1]) / equity_curve[i - 1] if equity_curve[i - 1] > 0 else 0
            returns.append(r)
        if returns:
            import statistics

            mean_r = statistics.mean(returns)
            std_r = statistics.stdev(returns) if len(returns) > 1 else 1
            sharpe = (mean_r / std_r * (252**0.5)) if std_r > 0 else 0
        else:
            sharpe = 0

        return BacktestResult(
            trades=trades,
            total_trades=len(trades),
            win_rate=len(wins) / len(trades) if trades else 0,
            total_profit=total_profit,
            total_gross_profit=gross_profit,
            max_drawdown=max_dd,
            sharpe_ratio=sharpe,
            profit_factor=gross_profit / gross_loss if gross_loss > 0 else float("inf"),
            equity_curve=equity_curve,
            ai_filtered_trades=ai_filtered,
        )
