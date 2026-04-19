"""
AI Context Builder — enriches AI prompts with historical patterns, price action, and trade history.
"""

from datetime import UTC, datetime, timedelta


def _naive(dt: datetime) -> datetime:
    """Strip timezone for DB columns stored as TIMESTAMP WITHOUT TIME ZONE."""
    return dt.replace(tzinfo=None) if dt.tzinfo is not None else dt


import pandas as pd
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import OHLCVData, Trade
from app.strategy.indicators import atr, ema, rsi


class AIContextBuilder:
    def __init__(self, db_session: AsyncSession):
        self.db = db_session
        self._macro_service = None
        self._event_calendar = None

    def set_macro_service(self, macro_service):
        self._macro_service = macro_service

    def set_event_calendar(self, calendar):
        self._event_calendar = calendar

    async def build_full_context(self, symbol: str, timeframe: str) -> dict:
        """Build all context sections. Returns dict of context strings."""
        context = {}
        try:
            context["price_action"] = await self.build_price_action_stats(symbol, timeframe)
        except Exception as e:
            logger.warning(f"Price action context failed: {e}")

        try:
            context["trade_patterns"] = await self.build_trade_history_patterns()
        except Exception as e:
            logger.warning(f"Trade pattern context failed: {e}")

        try:
            context["historical_patterns"] = await self.build_historical_patterns(symbol, timeframe)
        except Exception as e:
            logger.warning(f"Historical pattern context failed: {e}")

        try:
            macro = await self.build_macro_context(symbol, timeframe)
            if macro:
                context["macro_context"] = macro
        except Exception as e:
            logger.warning(f"Macro context failed: {e}")

        return context

    async def build_price_action_stats(self, symbol: str, timeframe: str) -> str:
        """30-day price action summary: trend, ATR percentile, range."""
        cutoff = _naive(datetime.now(UTC)) - timedelta(days=30)
        result = await self.db.execute(
            select(OHLCVData)
            .where(OHLCVData.symbol == symbol, OHLCVData.timeframe == timeframe, OHLCVData.time >= cutoff)
            .order_by(OHLCVData.time)
        )
        rows = result.scalars().all()
        if len(rows) < 50:
            return "Insufficient price data for analysis."

        df = pd.DataFrame(
            [
                {
                    "open": r.open,
                    "high": r.high,
                    "low": r.low,
                    "close": r.close,
                    "volume": r.volume,
                }
                for r in rows
            ]
        )

        current_price = df["close"].iloc[-1]
        high_30d = df["high"].max()
        low_30d = df["low"].min()

        # Trend via EMA
        ema_50 = ema(df["close"], 50)
        ema_20 = ema(df["close"], 20)
        trend = "bullish" if current_price > ema_50.iloc[-1] else "bearish"
        ema_20_val = ema_20.iloc[-1] if not pd.isna(ema_20.iloc[-1]) else current_price

        # ATR
        atr_vals = atr(df["high"], df["low"], df["close"], 14)
        current_atr = atr_vals.iloc[-1] if not pd.isna(atr_vals.iloc[-1]) else 0
        atr_90_pct = atr_vals.quantile(0.9) if len(atr_vals.dropna()) > 10 else current_atr

        # RSI
        rsi_vals = rsi(df["close"], 14)
        current_rsi = rsi_vals.iloc[-1] if not pd.isna(rsi_vals.iloc[-1]) else 50

        # Daily average range
        df["range"] = df["high"] - df["low"]
        avg_range = df["range"].mean()

        volatility = "high" if current_atr >= atr_90_pct else "normal"

        return (
            f"Price Action (30d): {symbol} @ {current_price:.2f}\n"
            f"Trend: {trend} (price {'above' if trend == 'bullish' else 'below'} EMA50={ema_50.iloc[-1]:.2f})\n"
            f"EMA20: {ema_20_val:.2f}, RSI(14): {current_rsi:.1f}\n"
            f"30d Range: {low_30d:.2f} - {high_30d:.2f}\n"
            f"ATR(14): {current_atr:.2f} ({volatility} volatility)\n"
            f"Avg bar range: {avg_range:.2f}"
        )

    async def build_trade_history_patterns(self, days: int = 30) -> str:
        """Win rate by hour/day from Trade table."""
        cutoff = _naive(datetime.now(UTC)) - timedelta(days=days)
        result = await self.db.execute(
            select(Trade).where(Trade.open_time >= cutoff, Trade.profit.isnot(None), Trade.is_archived.is_(False))
        )
        trades = result.scalars().all()

        if len(trades) < 10:
            return "Insufficient trade history for pattern analysis."

        wins = [t for t in trades if t.profit > 0]
        total_wr = len(wins) / len(trades) * 100

        # By hour
        hour_stats = {}
        for t in trades:
            h = t.open_time.hour
            if h not in hour_stats:
                hour_stats[h] = {"wins": 0, "total": 0}
            hour_stats[h]["total"] += 1
            if t.profit > 0:
                hour_stats[h]["wins"] += 1

        best_hours = []
        worst_hours = []
        for h, s in sorted(hour_stats.items()):
            if s["total"] >= 3:
                wr = s["wins"] / s["total"] * 100
                if wr >= 60:
                    best_hours.append(f"{h:02d}:00 ({wr:.0f}% in {s['total']} trades)")
                elif wr <= 30:
                    worst_hours.append(f"{h:02d}:00 ({wr:.0f}% in {s['total']} trades)")

        # By day of week
        dow_stats = {}
        dow_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        for t in trades:
            d = t.open_time.weekday()
            if d not in dow_stats:
                dow_stats[d] = {"wins": 0, "total": 0}
            dow_stats[d]["total"] += 1
            if t.profit > 0:
                dow_stats[d]["wins"] += 1

        dow_summary = []
        for d, s in sorted(dow_stats.items()):
            if s["total"] >= 2:
                wr = s["wins"] / s["total"] * 100
                dow_summary.append(f"{dow_names[d]}: {wr:.0f}% ({s['total']} trades)")

        # AI filter performance
        ai_agreed = [
            t
            for t in trades
            if t.ai_sentiment_label
            and (
                (t.type == "BUY" and t.ai_sentiment_label == "bullish")
                or (t.type == "SELL" and t.ai_sentiment_label == "bearish")
            )
        ]
        ai_disagreed = [
            t
            for t in trades
            if t.ai_sentiment_label
            and (
                (t.type == "BUY" and t.ai_sentiment_label == "bearish")
                or (t.type == "SELL" and t.ai_sentiment_label == "bullish")
            )
        ]

        lines = [
            f"Trade Patterns ({days}d): {len(trades)} trades, {total_wr:.0f}% win rate",
        ]
        if best_hours:
            lines.append(f"Best hours: {', '.join(best_hours)}")
        if worst_hours:
            lines.append(f"Worst hours: {', '.join(worst_hours)}")
        if dow_summary:
            lines.append(f"By day: {', '.join(dow_summary)}")
        if ai_agreed:
            wr = sum(1 for t in ai_agreed if t.profit > 0) / len(ai_agreed) * 100
            lines.append(f"AI-aligned trades: {wr:.0f}% win ({len(ai_agreed)} trades)")
        if ai_disagreed:
            wr = sum(1 for t in ai_disagreed if t.profit > 0) / len(ai_disagreed) * 100
            lines.append(f"AI-opposing trades: {wr:.0f}% win ({len(ai_disagreed)} trades)")

        return "\n".join(lines)

    async def build_historical_patterns(self, symbol: str, timeframe: str) -> str:
        """Patterns around known recurring events (NFP, session times)."""
        # Get 90 days of data
        cutoff = _naive(datetime.now(UTC)) - timedelta(days=90)
        result = await self.db.execute(
            select(OHLCVData)
            .where(OHLCVData.symbol == symbol, OHLCVData.timeframe == timeframe, OHLCVData.time >= cutoff)
            .order_by(OHLCVData.time)
        )
        rows = result.scalars().all()
        if len(rows) < 100:
            return "Insufficient data for historical pattern analysis."

        df = pd.DataFrame(
            [
                {
                    "time": r.time,
                    "close": r.close,
                    "high": r.high,
                    "low": r.low,
                }
                for r in rows
            ]
        )
        df["time"] = pd.to_datetime(df["time"])

        # Session analysis
        df["hour"] = df["time"].dt.hour
        london = df[(df["hour"] >= 8) & (df["hour"] < 16)]
        ny = df[(df["hour"] >= 13) & (df["hour"] < 21)]
        overlap = df[(df["hour"] >= 13) & (df["hour"] < 16)]

        # Average move by session
        def session_move(sdf):
            if len(sdf) < 10:
                return 0
            return sdf["close"].pct_change().mean() * 100

        # First Friday patterns (NFP proxy)
        df["day"] = df["time"].dt.day
        df["weekday"] = df["time"].dt.weekday
        nfp_bars = df[(df["weekday"] == 4) & (df["day"] <= 7)]  # First Friday
        nfp_up = 0
        nfp_total = 0
        if len(nfp_bars) > 0:
            for _, group in nfp_bars.groupby(df["time"].dt.date):
                if len(group) >= 2:
                    nfp_total += 1
                    if group["close"].iloc[-1] > group["close"].iloc[0]:
                        nfp_up += 1

        lines = [f"Historical Patterns (90d, {symbol}):"]

        if nfp_total >= 2:
            lines.append(f"NFP Fridays: gold rose {nfp_up}/{nfp_total} times")

        lines.append(f"London session (08-16 UTC): avg move {session_move(london):.4f}%")
        lines.append(f"NY session (13-21 UTC): avg move {session_move(ny):.4f}%")
        lines.append(f"Overlap (13-16 UTC): avg move {session_move(overlap):.4f}%")

        # Recent momentum
        if len(df) >= 20:
            last_20_change = (df["close"].iloc[-1] / df["close"].iloc[-20] - 1) * 100
            lines.append(f"20-bar momentum: {last_20_change:+.2f}%")

        return "\n".join(lines)

    async def build_macro_context(self, symbol: str, timeframe: str) -> str | None:
        """Build macro economic context from FRED data and event calendar."""
        if not self._macro_service:
            return None

        lines = []

        # Latest macro snapshot
        snapshot = await self._macro_service.get_latest_snapshot()
        if snapshot:
            lines.append("Macro Data (latest):")
            for _series_id, info in snapshot.items():
                lines.append(f"  {info['name']}: {info['value']} ({info['date']})")

        # Correlations
        try:
            correlations = await self._macro_service.compute_correlations(symbol, timeframe, days=90)
            if correlations and "error" not in correlations:
                lines.append("Gold correlations (90d):")
                for _series_id, info in correlations.items():
                    if info["correlation"] is not None:
                        lines.append(f"  {info['name']}: {info['correlation']:+.3f} ({info['data_points']} pts)")
        except Exception as e:
            logger.warning(f"Correlation computation failed: {e}")

        # Upcoming events
        if self._event_calendar:
            events = self._event_calendar.get_upcoming_events(days_ahead=7)
            if events:
                lines.append("Upcoming events (7d):")
                for e in events:
                    lines.append(f"  {e['date']}: {e['name']} ({e['impact']} impact) — {e['note']}")

            near_event = self._event_calendar.is_near_event(hours_before=4)
            if near_event:
                lines.append(f"WARNING: {near_event['name']} within 4 hours — expect high volatility")

        return "\n".join(lines) if lines else None

    def get_trade_patterns_for_risk(self, context: dict) -> dict | None:
        """Extract trade patterns dict for RiskManager from context."""
        patterns_str = context.get("trade_patterns", "")
        if "Insufficient" in patterns_str:
            return None

        # Parse worst hours from context
        worst_hours = []
        for line in patterns_str.split("\n"):
            if line.startswith("Worst hours:"):
                import re

                hours = re.findall(r"(\d{2}):00", line)
                worst_hours = [int(h) for h in hours]

        if not worst_hours:
            return None

        return {"worst_hours": worst_hours}
