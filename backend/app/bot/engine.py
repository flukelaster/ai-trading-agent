"""
Bot Engine — main trading loop integrating strategy, risk, AI sentiment, and orders.
"""

import enum
import json
import random
from datetime import datetime, timezone


def _naive_utc() -> datetime:
    """Return current UTC time without timezone info (for DB columns without tz)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _get_h1_trend(df) -> int:
    """
    Determine H1 trend direction using EMA(21) slope.
    Returns +1 (uptrend), -1 (downtrend), or 0 (neutral/insufficient data).
    """
    if df is None or df.empty or len(df) < 22:
        return 0
    try:
        from app.strategy.indicators import ema as _ema
        closes = df["close"]
        ema21 = _ema(closes, 21)
        current_price = closes.iloc[-1]
        ema_val = ema21.iloc[-1]
        if current_price > ema_val * 1.0005:   # price clearly above EMA
            return 1
        elif current_price < ema_val * 0.9995:  # price clearly below EMA
            return -1
        return 0
    except Exception:
        return 0

import redis.asyncio as redis
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.context_builder import AIContextBuilder
from app.ai.news_sentiment import NewsSentimentAnalyzer
from app.config import settings
from app.db.models import BotEvent, BotEventType, Trade
from app.mt5.connector import MT5BridgeConnector
from app.mt5.market_data import MarketDataService
from app.mt5.order_executor import OrderExecutor
from app.news.fetcher import NewsFetcher
from app.risk.circuit_breaker import CircuitBreaker
from app.risk.manager import RiskManager
from app.strategy import get_strategy
from app.strategy.base import BaseStrategy


class BotState(str, enum.Enum):
    STOPPED = "STOPPED"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    ERROR = "ERROR"


class BotEngine:
    def __init__(
        self,
        connector: MT5BridgeConnector,
        db_session: AsyncSession,
        redis_client: redis.Redis,
        symbol: str | None = None,
        symbol_profile: dict | None = None,
    ):
        self.connector = connector
        self.market_data = MarketDataService(connector)
        self.executor = OrderExecutor(connector)
        self.db = db_session
        self.redis = redis_client

        # Symbol profile (per-symbol config)
        profile = symbol_profile or {}
        self.symbol = symbol or settings.symbol
        self.timeframe = profile.get("default_timeframe", settings.timeframe)
        self.contract_size = profile.get("contract_size", 100)

        self.circuit_breaker = CircuitBreaker(redis_client, self.symbol)

        # Initialize with defaults — can be updated via API
        self.strategy: BaseStrategy = get_strategy("ema_crossover")
        self.risk_manager = RiskManager(
            max_risk_per_trade=settings.max_risk_per_trade,
            max_daily_loss=settings.max_daily_loss,
            max_concurrent_trades=settings.max_concurrent_trades,
            max_lot=profile.get("max_lot", settings.max_lot),
            use_ai_filter=settings.use_ai_filter,
            ai_confidence_threshold=settings.ai_confidence_threshold,
            pip_value=profile.get("pip_value", 1.0),
            price_decimals=profile.get("price_decimals", 2),
            sl_atr_mult=profile.get("sl_atr_mult", 1.5),
            tp_atr_mult=profile.get("tp_atr_mult", 2.0),
        )
        self.sentiment_analyzer: NewsSentimentAnalyzer | None = None
        self.context_builder = AIContextBuilder(db_session)
        self._ai_context: dict | None = None  # Cached context, refreshed with sentiment
        self._optimizer = None
        self.notifier = None  # TelegramNotifier (optional)
        self._scheduler = None  # BotScheduler ref (set in main.py)
        self.news_fetcher = NewsFetcher()

        self.state = BotState.STOPPED
        self._manager = None  # BotManager ref (set in manager.py)
        self._known_tickets: set[int] = set()  # Track open tickets for close detection

        # Paper trade mode
        self.paper_trade = settings.paper_trade
        self._paper_positions: list[dict] = []
        self._paper_ticket_counter = 900000
        self._paper_balance = 10000.0  # Virtual balance

        # Trailing stop config
        self.trailing_stop_enabled = True
        self.trailing_start_atr = 1.0   # Activate trailing after profit > start_atr * ATR
        self.trailing_step_atr = 0.5    # Trail SL at step_atr * ATR behind price
        self._position_atr: dict[int, float] = {}  # ticket → ATR at entry time
        self.started_at: datetime | None = None
        self.last_signal_time: datetime | None = None

    def set_sentiment_analyzer(self, analyzer: NewsSentimentAnalyzer):
        self.sentiment_analyzer = analyzer

    def set_notifier(self, notifier):
        self.notifier = notifier

    async def _notify(self, coro):
        """Fire-and-forget notification — never crash the bot."""
        if not self.notifier:
            return
        try:
            await coro
        except Exception as e:
            logger.error(f"Notification failed: {e}")

    async def start(self):
        if self.state == BotState.RUNNING:
            return
        self.state = BotState.RUNNING
        self.started_at = datetime.now(timezone.utc)

        # Seed known tickets from current MT5 positions
        try:
            positions = await self.executor.get_open_positions(self.symbol)
            self._known_tickets = {p["ticket"] for p in positions}
            if self._known_tickets:
                logger.info(f"Tracking {len(self._known_tickets)} existing positions")
        except Exception as e:
            logger.warning(f"Could not seed known tickets: {e}")

        await self._log_event(BotEventType.STARTED, "Bot started")
        logger.info(f"Bot started: strategy={self.strategy.name}, symbol={self.symbol}")
        if self.notifier:
            await self._notify(self.notifier._send(
                f"▶️ <b>Bot Started</b>\nStrategy: {self.strategy.name}\nSymbol: {self.symbol}\nTimeframe: {self.timeframe}"
            ))

    async def stop(self):
        self.state = BotState.STOPPED
        await self._log_event(BotEventType.STOPPED, "Bot stopped")
        logger.info("Bot stopped")
        if self.notifier:
            await self._notify(self.notifier._send("⏹ <b>Bot Stopped</b>"))

    async def emergency_stop(self):
        self.state = BotState.STOPPED
        result = await self.executor.close_all_positions(self.symbol)
        await self._log_event(BotEventType.STOPPED, f"Emergency stop: {result}")
        logger.warning(f"EMERGENCY STOP executed: {result}")
        return result

    def get_status(self) -> dict:
        return {
            "state": self.state.value,
            "strategy": self.strategy.name,
            "strategy_params": self.strategy.get_params(),
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "use_ai_filter": self.risk_manager.use_ai_filter,
            "paper_trade": self.paper_trade,
            "max_risk_per_trade": self.risk_manager.max_risk_per_trade,
            "max_daily_loss": self.risk_manager.max_daily_loss,
            "max_concurrent_trades": self.risk_manager.max_concurrent_trades,
            "max_lot": self.risk_manager.max_lot,
        }

    async def process_candle(self):
        """Main trading logic — called every candle close."""
        if self.state != BotState.RUNNING:
            return

        try:
            # 1. Check circuit breaker
            account = await self.connector.get_account()
            if not account.get("success"):
                logger.error("Cannot get account info")
                return

            balance = account["data"]["balance"]
            if await self.circuit_breaker.is_triggered(balance):
                self.state = BotState.PAUSED
                await self._log_event(BotEventType.CIRCUIT_BREAKER, "Circuit breaker triggered")
                if self.notifier:
                    await self._notify(self.notifier.send_error_alert("⚡ Circuit breaker triggered — bot paused"))
                return

            # Check global portfolio daily loss (across all symbols)
            from app.risk.circuit_breaker import CircuitBreaker
            from app.config import settings
            all_symbols = settings.symbol_list
            if await CircuitBreaker.is_global_triggered(self.redis, all_symbols, balance, settings.max_daily_loss * 1.5):
                self.state = BotState.PAUSED
                await self._log_event(BotEventType.CIRCUIT_BREAKER, "Portfolio circuit breaker triggered (global daily loss)")
                if self.notifier:
                    await self._notify(self.notifier.send_error_alert("⚡ Portfolio circuit breaker — ALL symbols paused"))
                return

            # 2. Fetch OHLCV and calculate signal
            df = await self.market_data.get_ohlcv(self.symbol, self.timeframe, 200)
            if df.empty:
                return

            # Lazy-load ML model from DB if strategy supports it
            if hasattr(self.strategy, "_ensure_model"):
                await self.strategy._ensure_model()

            df = self.strategy.calculate(df)
            if len(df) < 2:
                return

            signal = int(df.iloc[-2]["signal"])  # Previous bar's signal (confirmed candle)
            if signal == 0:
                return

            # Phase G: Multi-timeframe H1 trend confirmation
            from app.config import settings as _settings
            if _settings.use_mtf_filter:
                h1_df = await self.market_data.get_ohlcv(self.symbol, "H1", 50)
                h1_trend = _get_h1_trend(h1_df)
                if h1_trend != 0 and h1_trend != signal:
                    h1_label = "uptrend" if h1_trend == 1 else "downtrend"
                    signal_label_tmp = "BUY" if signal == 1 else "SELL"
                    logger.info(f"MTF filter blocked: M15={signal_label_tmp}, H1={h1_label}")
                    await self._log_event(
                        BotEventType.TRADE_BLOCKED,
                        f"{signal_label_tmp} blocked: H1 {h1_label} disagrees"
                    )
                    return

            self.last_signal_time = datetime.now(timezone.utc)
            signal_label = "BUY" if signal == 1 else "SELL"
            logger.info(f"Signal detected: {signal_label}")
            await self._log_event(BotEventType.SIGNAL_DETECTED, f"{signal_label} signal on {self.symbol}")
            await self._push_event("bot_event", {"type": "signal_detected", "signal": signal_label, "symbol": self.symbol})
            await self._notify(self.notifier._send(f"📊 <b>Signal: {signal_label}</b> on {self.symbol}"))

            # 3. Get AI sentiment (optional)
            ai_sentiment = None
            if self.sentiment_analyzer and self.risk_manager.use_ai_filter:
                sentiment = await self.sentiment_analyzer.get_latest_sentiment(self.symbol)
                if sentiment.confidence > 0:
                    ai_sentiment = {"label": sentiment.label, "confidence": sentiment.confidence}

            # 4. Check risk
            positions = await self.executor.get_open_positions(self.symbol)
            daily_pnl = await self.circuit_breaker.get_daily_pnl()

            # Get trade patterns from cached context for risk adjustment
            trade_patterns = None
            if self._ai_context:
                trade_patterns = self.context_builder.get_trade_patterns_for_risk(self._ai_context)

            can_trade, reason = self.risk_manager.can_open_trade(
                current_positions=len(positions),
                daily_pnl=daily_pnl,
                balance=balance,
                signal=signal,
                ai_sentiment=ai_sentiment,
                trade_patterns=trade_patterns,
            )
            if not can_trade:
                logger.info(f"Trade blocked: {reason}")
                await self._log_event(BotEventType.TRADE_BLOCKED, f"{signal_label} blocked: {reason}")
                await self._push_event("bot_event", {"type": "trade_blocked", "signal": signal_label, "reason": reason})
                if self.notifier:
                    await self._notify(self.notifier._send(f"🚫 <b>{signal_label} Blocked</b>\n{reason}"))
                return

            # Check symbol correlation conflicts
            if self._manager:
                from app.risk.correlation import check_correlation_conflict
                active_positions = await self._manager.get_active_positions()
                has_conflict, conflict_reason = check_correlation_conflict(self.symbol, signal, active_positions)
                if has_conflict:
                    logger.info(f"Correlation conflict: {conflict_reason}")
                    await self._log_event(BotEventType.TRADE_BLOCKED, conflict_reason)
                    await self._push_event("bot_event", {"type": "trade_blocked", "signal": signal_label, "reason": conflict_reason})
                    return

            # 5. Calculate lot size and SL/TP
            atr = df.iloc[-2].get("atr", 10.0)
            tick = await self.market_data.get_current_tick(self.symbol)
            if not tick:
                return

            entry_price = tick["ask"] if signal == 1 else tick["bid"]
            sl_tp = self.risk_manager.calculate_sl_tp(entry_price, signal, atr)
            sl_pips = abs(entry_price - sl_tp.sl)
            lot = self.risk_manager.calculate_lot_size(balance, sl_pips)

            # 6. Place order (real or paper)
            order_type = "BUY" if signal == 1 else "SELL"
            comment = f"{self.strategy.name}"
            tag = "📝 PAPER" if self.paper_trade else ""

            if self.paper_trade:
                # Paper trade: simulate order fill
                self._paper_ticket_counter += 1
                ticket = self._paper_ticket_counter
                result = {"success": True, "data": {
                    "ticket": ticket, "price": entry_price,
                    "lot": lot, "type": order_type,
                }}
                self._paper_positions.append({
                    "ticket": ticket, "symbol": self.symbol,
                    "type": order_type, "lot": lot,
                    "open_price": entry_price, "current_price": entry_price,
                    "sl": sl_tp.sl, "tp": sl_tp.tp,
                    "profit": 0.0, "open_time": datetime.now(timezone.utc).isoformat(),
                    "comment": comment, "magic": 234000,
                })
                logger.info(f"PAPER trade: {order_type} {lot} {self.symbol} @ {entry_price}")
            else:
                result = await self.executor.place_order(
                    self.symbol, order_type, lot, sl_tp.sl, sl_tp.tp, comment
                )

            if not result.get("success"):
                error_msg = result.get("error", "Unknown error")
                logger.error(f"Order failed: {order_type} {lot} {self.symbol} — {error_msg}")
                await self._log_event(BotEventType.ORDER_FAILED, f"{order_type} {lot} {self.symbol}: {error_msg}")
                await self._push_event("bot_event", {"type": "order_failed", "order": order_type, "symbol": self.symbol, "lot": lot, "error": error_msg})
                if self.notifier:
                    await self._notify(self.notifier._send(f"❌ <b>Order Failed</b>\n{order_type} {lot} {self.symbol}\n{error_msg}"))
                return

            if result.get("success"):
                # 7. Save trade to DB
                sentiment_data = ai_sentiment or {}
                trade = Trade(
                    ticket=result["data"]["ticket"],
                    symbol=self.symbol,
                    type=order_type,
                    lot=lot,
                    open_price=entry_price,
                    sl=sl_tp.sl,
                    tp=sl_tp.tp,
                    open_time=_naive_utc(),
                    strategy_name=self.strategy.name,
                    ai_sentiment_score=sentiment_data.get("confidence"),
                    ai_sentiment_label=sentiment_data.get("label"),
                )
                self.db.add(trade)
                await self.db.commit()

                await self._log_event(
                    BotEventType.TRADE_OPENED,
                    f"{tag}{order_type} {lot} {self.symbol} @ {entry_price} SL={sl_tp.sl} TP={sl_tp.tp}",
                )

                # Push event via Redis
                await self._push_event("bot_event", {
                    "type": "trade_opened",
                    "data": result["data"],
                    "sentiment": sentiment_data,
                })

                # Store ATR for trailing stop
                self._position_atr[result["data"]["ticket"]] = atr

                # Telegram: trade opened
                if self.notifier:
                    paper_label = " [PAPER]" if self.paper_trade else ""
                    await self._notify(self.notifier.send_trade_alert(
                        f"{order_type}{paper_label}", self.symbol, entry_price, sl_tp.sl, sl_tp.tp, lot,
                        sentiment_data.get("label", ""),
                    ))

        except Exception as e:
            logger.error(f"Bot engine error: {e}")
            self.state = BotState.ERROR
            await self._log_event(BotEventType.ERROR, str(e))
            if self.notifier:
                await self._notify(self.notifier.send_error_alert(f"Bot engine error: {e}"))

    async def fetch_and_analyze_sentiment(self):
        """Fetch news and run sentiment analysis with enriched context."""
        if not self.sentiment_analyzer:
            return
        try:
            # Build AI context (historical patterns, price action, trade history)
            try:
                self._ai_context = await self.context_builder.build_full_context(
                    self.symbol, self.timeframe
                )
            except Exception as e:
                logger.warning(f"Context building failed, using basic sentiment: {e}")
                self._ai_context = None

            news = await self.news_fetcher.fetch_for_symbol(self.symbol)
            if news:
                result = await self.sentiment_analyzer.analyze(news, context=self._ai_context, symbol=self.symbol)
                logger.info(f"Sentiment: {result.label} (score={result.score}, confidence={result.confidence})")
                await self._push_event("sentiment_update", result.to_dict())
                if self.notifier:
                    await self._notify(self.notifier.send_sentiment_alert(
                        result.label, result.score, result.key_factors, symbol=self.symbol,
                    ))
        except Exception as e:
            logger.error(f"Sentiment analysis error: {e}")

    async def sync_positions(self):
        """Sync open positions and update closed trades."""
        if self.state != BotState.RUNNING:
            return
        try:
            if self.paper_trade:
                positions = await self._sync_paper_positions()
            else:
                positions = await self.executor.get_open_positions(self.symbol)

            current_tickets = {p["ticket"] for p in positions}

            # Always track ALL open positions (including manually opened ones)
            self._known_tickets = self._known_tickets | current_tickets

            # Detect closed positions
            closed = self._known_tickets - current_tickets
            if closed and not self.paper_trade:
                await self._handle_closed_trades(closed)
            elif closed:
                for ticket in closed:
                    logger.info(f"Paper position closed: ticket={ticket}")
                    self._position_atr.pop(ticket, None)

            self._known_tickets = current_tickets

            # Apply trailing stops (real mode only — paper handles SL/TP internally)
            if self.trailing_stop_enabled and positions and not self.paper_trade:
                await self._apply_trailing_stops(positions)

            await self._push_event("position_update", {"positions": positions})
        except Exception as e:
            logger.error(f"Position sync error: {e}")

    async def _handle_closed_trades(self, closed_tickets: set[int]):
        """Fetch close details from MT5 history and update DB."""
        history_result = await self.connector.get_history(days=1)
        history_deals = history_result.get("data", []) if history_result.get("success") else []
        history_map = {d["ticket"]: d for d in history_deals}

        for ticket in closed_tickets:
            self._position_atr.pop(ticket, None)
            deal = history_map.get(ticket)

            close_price = deal["price"] if deal else 0
            profit = deal["profit"] if deal else 0
            close_time = datetime.fromisoformat(deal["time"]).replace(tzinfo=None) if deal and deal.get("time") else datetime.now(timezone.utc).replace(tzinfo=None)

            profit_str = f"+${profit:.2f}" if profit >= 0 else f"-${abs(profit):.2f}"
            logger.info(f"Position closed: ticket={ticket} price={close_price} profit={profit_str}")

            # Update trade in DB
            from sqlalchemy import select
            stmt = select(Trade).where(Trade.ticket == ticket)
            result = await self.db.execute(stmt)
            trade = result.scalar_one_or_none()
            if trade:
                trade.close_price = close_price
                trade.close_time = close_time
                trade.profit = profit
                await self.db.commit()

            # Log event
            await self._log_event(
                BotEventType.TRADE_CLOSED,
                f"#{ticket} closed @ {close_price} — {profit_str}",
            )

            # Push to frontend
            await self._push_event("bot_event", {
                "type": "trade_closed",
                "ticket": ticket,
                "close_price": close_price,
                "profit": profit,
            })

            # Telegram notification
            if self.notifier:
                await self._notify(self.notifier.send_trade_alert(
                    "CLOSE", self.symbol, close_price, 0, 0, deal.get("lot", 0) if deal else 0,
                    extra=profit_str,
                ))

    async def _sync_paper_positions(self) -> list[dict]:
        """Update paper positions with current prices, close if SL/TP hit."""
        tick = await self.market_data.get_current_tick(self.symbol)
        if not tick:
            return self._paper_positions

        still_open = []
        for pos in self._paper_positions:
            price = tick["bid"] if pos["type"] == "BUY" else tick["ask"]
            pos["current_price"] = price

            # Calculate profit: price diff * lot * contract_size
            if pos["type"] == "BUY":
                pos["profit"] = round((price - pos["open_price"]) * pos["lot"] * self.contract_size, 2)
            else:
                pos["profit"] = round((pos["open_price"] - price) * pos["lot"] * self.contract_size, 2)

            # Check SL/TP hit
            hit = False
            if pos["type"] == "BUY":
                if pos["sl"] > 0 and price <= pos["sl"]:
                    hit = True
                elif pos["tp"] > 0 and price >= pos["tp"]:
                    hit = True
            else:
                if pos["sl"] > 0 and price >= pos["sl"]:
                    hit = True
                elif pos["tp"] > 0 and price <= pos["tp"]:
                    hit = True

            if hit:
                self._paper_balance += pos["profit"]
                logger.info(f"PAPER position {pos['ticket']} closed: profit={pos['profit']}")
                await self._push_event("bot_event", {"type": "trade_closed", "ticket": pos["ticket"]})
                if self.notifier:
                    tag = " [PAPER]" if self.paper_trade else ""
                    await self._notify(self.notifier.send_trade_alert(
                        f"CLOSE{tag}", self.symbol, price, 0, 0, pos["lot"],
                    ))
            else:
                still_open.append(pos)

        self._paper_positions = still_open
        return still_open

    async def _apply_trailing_stops(self, positions: list[dict]):
        """Move SL in profit direction when position is profitable enough."""
        for pos in positions:
            ticket = pos["ticket"]
            pos_atr = self._position_atr.get(ticket)
            if not pos_atr or pos_atr <= 0:
                continue

            current_price = pos.get("current_price", 0)
            open_price = pos.get("open_price", 0)
            current_sl = pos.get("sl", 0)
            pos_type = pos.get("type", "")

            if pos_type == "BUY":
                profit_distance = current_price - open_price
                if profit_distance < pos_atr * self.trailing_start_atr:
                    continue
                new_sl = current_price - pos_atr * self.trailing_step_atr
                if new_sl > current_sl:
                    logger.info(f"Trailing stop BUY {ticket}: SL {current_sl:.2f} → {new_sl:.2f}")
                    await self.executor.modify_position(ticket, sl=round(new_sl, 2))

            elif pos_type == "SELL":
                profit_distance = open_price - current_price
                if profit_distance < pos_atr * self.trailing_start_atr:
                    continue
                new_sl = current_price + pos_atr * self.trailing_step_atr
                if current_sl == 0 or new_sl < current_sl:
                    logger.info(f"Trailing stop SELL {ticket}: SL {current_sl:.2f} → {new_sl:.2f}")
                    await self.executor.modify_position(ticket, sl=round(new_sl, 2))

    async def update_strategy(self, name: str, params: dict | None = None):
        self.strategy = get_strategy(name, params)
        logger.info(f"Strategy updated: {name} params={params}")

    async def update_settings(self, use_ai_filter: bool | None = None, ai_confidence_threshold: float | None = None, paper_trade: bool | None = None, timeframe: str | None = None, max_risk_per_trade: float | None = None, max_daily_loss: float | None = None, max_concurrent_trades: int | None = None, max_lot: float | None = None):
        if use_ai_filter is not None:
            self.risk_manager.use_ai_filter = use_ai_filter
        if ai_confidence_threshold is not None:
            self.risk_manager.ai_confidence_threshold = ai_confidence_threshold
        if paper_trade is not None:
            self.paper_trade = paper_trade
            logger.info(f"Paper trade mode: {'ON' if paper_trade else 'OFF'}")
        if timeframe is not None:
            valid = ["M1", "M5", "M15", "M30", "H1", "H4", "D1"]
            if timeframe in valid:
                self.timeframe = timeframe
                logger.info(f"Timeframe changed to: {timeframe}")
                if self._scheduler:
                    self._scheduler.reschedule_candle(self.symbol, timeframe)
        if max_risk_per_trade is not None:
            self.risk_manager.max_risk_per_trade = max_risk_per_trade
            logger.info(f"Max risk per trade: {max_risk_per_trade:.1%}")
        if max_daily_loss is not None:
            self.risk_manager.max_daily_loss = max_daily_loss
            logger.info(f"Max daily loss: {max_daily_loss:.1%}")
        if max_concurrent_trades is not None:
            self.risk_manager.max_concurrent_trades = max(1, max_concurrent_trades)
            logger.info(f"Max concurrent trades: {max_concurrent_trades}")
        if max_lot is not None:
            self.risk_manager.max_lot = max_lot
            logger.info(f"Max lot: {max_lot}")

    async def _log_event(self, event_type: BotEventType, message: str):
        try:
            event = BotEvent(event_type=event_type, message=message)
            self.db.add(event)
            await self.db.commit()
        except Exception as e:
            logger.error(f"Failed to log event: {e}")
            try:
                await self.db.rollback()
            except Exception:
                pass

    async def _push_event(self, channel: str, data: dict):
        try:
            await self.redis.publish(channel, json.dumps(data))
        except Exception as e:
            logger.error(f"Failed to push event: {e}")
