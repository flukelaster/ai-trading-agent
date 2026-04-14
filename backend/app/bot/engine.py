"""
Bot Engine — main trading loop integrating strategy, risk, AI sentiment, and orders.
"""

import enum
import json
import random
import time
from datetime import datetime, timedelta, timezone

from app.constants import (
    BREAKEVEN_ATR_MULT,
    DEFAULT_ATR_FALLBACK,
    DEFAULT_ATR_PCT_FALLBACK,
    DEFAULT_OHLCV_BARS,
    DEFAULT_TRAILING_START_ATR,
    DEFAULT_TRAILING_STEP_ATR,
    H1_BARS,
    HIGH_VOL_THRESHOLD,
    HIGH_VOL_TRAIL_FACTOR,
    KELLY_MIN_WIN_RATE,
    KELLY_RECENT_TRADES,
    LOW_VOL_THRESHOLD,
    LOW_VOL_TRAIL_FACTOR,
    MIN_KELLY_TRADES,
    MIN_LOT,
    MT5_MAGIC_NUMBER,
    MTF_EMA_ABOVE,
    MTF_EMA_BELOW,
    PAPER_INITIAL_BALANCE,
    PAPER_TICKET_START,
    PARTIAL_TP_CLOSE_PCT,
    PROFIT_LOCK_ATR_MULT,
    SCALE_IN_ATR_MULT,
    SCALE_IN_LOT_FACTOR,
    STREAK_RECENT_TRADES,
    TIGHT_TRAIL_STEP_ATR,
    WARMUP_MIN_LOT_PCT,
    WARMUP_SECONDS,
)


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
        if current_price > ema_val * MTF_EMA_ABOVE:
            return 1
        elif current_price < ema_val * MTF_EMA_BELOW:
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
from app.db.models import BotEvent, BotEventType, OrderAudit, Trade
from app.mt5.connector import MT5BridgeConnector
from app.mt5.market_data import MarketDataService
from app.mt5.order_executor import OrderExecutor
from app.news.fetcher import NewsFetcher
from app.risk.circuit_breaker import CircuitBreaker
from app.risk.manager import RiskManager
from app.strategy import get_strategy
from app.strategy.base import BaseStrategy


_UNSET = object()  # Sentinel for "parameter not passed" (distinct from None)


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
        self.strategy: BaseStrategy = get_strategy("ema_crossover", symbol=self.symbol)
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

        # Lot sizing mode: None = auto (AI/Kelly/risk-based), float = fixed lot
        self.fixed_lot: float | None = None

        # Regime-aware risk + event filter
        from app.data.macro_events import MacroEventCalendar
        self._event_calendar = MacroEventCalendar(redis_client)
        self._last_regime = "normal"
        self._multi_tf_regime = None  # MultiTFRegime, set in process_candle

        # Paper trade mode
        self.paper_trade = settings.paper_trade
        self._paper_positions: list[dict] = []
        self._paper_ticket_counter = PAPER_TICKET_START
        self._paper_balance = PAPER_INITIAL_BALANCE

        # Trailing stop config
        self.trailing_stop_enabled = True
        self.trailing_start_atr = DEFAULT_TRAILING_START_ATR
        self.trailing_step_atr = DEFAULT_TRAILING_STEP_ATR
        self._position_atr: dict[int, float] = {}  # ticket → ATR at entry time
        self._position_atr_pct: dict[int, float] = {}  # ticket → ATR% at entry time
        self._position_entry_time: dict[int, datetime] = {}  # ticket → entry time
        self._position_group: dict[int, list[int]] = {}  # parent ticket → add-on tickets
        self._position_partial_closed: set[int] = set()  # tickets that had partial TP taken
        self._position_breakeven: set[int] = set()  # tickets moved to breakeven
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

        # Load cached sentiment from Redis
        try:
            cached = await self.sentiment_analyzer.get_latest_sentiment(symbol=self.symbol)
            if cached and cached.label != "neutral":
                self._last_sentiment = cached.to_dict()
        except Exception:
            pass

        await self._log_event(BotEventType.STARTED, "Bot started")
        logger.info(f"Bot started: strategy={self.strategy.name}, symbol={self.symbol}")
        if self.notifier:
            await self._notify(self.notifier.send_start_alert(self.symbol, self.timeframe, "AI Autonomous"))

    async def stop(self):
        self.state = BotState.STOPPED
        await self._log_event(BotEventType.STOPPED, "Bot stopped")
        logger.info("Bot stopped")
        if self.notifier:
            await self._notify(self.notifier.send_stop_alert(self.symbol))

    async def emergency_stop(self):
        self.state = BotState.STOPPED
        result = await self.executor.close_all_positions(self.symbol)
        await self._log_event(BotEventType.STOPPED, f"Emergency stop: {result}")
        logger.warning(f"EMERGENCY STOP executed: {result}")
        return result

    def get_status(self) -> dict:
        ai_decision = getattr(self, "_last_ai_decision", None)
        sentiment = getattr(self, "_last_sentiment", None)
        return {
            "state": self.state.value,
            "strategy": self.strategy.name if self.strategy else "ai_autonomous",
            "strategy_params": {},
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "use_ai_filter": True,
            "paper_trade": self.paper_trade,
            "max_risk_per_trade": self.risk_manager.max_risk_per_trade,
            "max_daily_loss": self.risk_manager.max_daily_loss,
            "max_concurrent_trades": self.risk_manager.max_concurrent_trades,
            "max_lot": self.risk_manager.max_lot,
            "fixed_lot": self.fixed_lot,
            "regime": self._last_regime,
            "multi_tf_regime": self._multi_tf_regime.to_dict() if self._multi_tf_regime else None,
            "ai_decision": ai_decision,
            "sentiment": sentiment,
        }

    async def process_candle(self):
        """Main trading logic — called every candle close."""
        # Auto-recovery: check if paused bot can resume after cooldown
        if self.state == BotState.PAUSED:
            if await self.circuit_breaker.can_resume():
                logger.info(f"Circuit breaker cooldown complete [{self.symbol}] — resuming")
                self.state = BotState.RUNNING
                await self._log_event(BotEventType.STARTED, "Auto-resumed after circuit breaker cooldown")
            else:
                return

        if self.state != BotState.RUNNING:
            return

        try:
            # 1. Check circuit breakers (per-symbol + global portfolio)
            account = await self.connector.get_account()
            if not account.get("success"):
                logger.error("Cannot get account info")
                return
            balance = account["data"]["balance"]

            # Track peak balance for absolute drawdown detection
            await CircuitBreaker.update_peak_balance(self.redis, balance)

            if await self._check_circuit_breakers(balance):
                return

            # 1b. Multi-timeframe regime detection + HMM overlay
            try:
                from app.strategy.regime import detect_multi_tf_regime, HMMRegimeDetector
                self._multi_tf_regime = await detect_multi_tf_regime(self.market_data, self.symbol)
                regime_label = self._multi_tf_regime.composite

                # HMM regime overlay — refine with probability distribution
                try:
                    if not hasattr(self, "_hmm_detector"):
                        self._hmm_detector = HMMRegimeDetector(n_states=2)
                    ohlcv = await self.market_data.get_ohlcv(self.symbol, self.timeframe, 200)
                    if ohlcv is not None and len(ohlcv) > 100:
                        prices = ohlcv["close"].values
                        if not self._hmm_detector._fitted:
                            self._hmm_detector.fit(prices)
                        if self._hmm_detector._fitted:
                            hmm_result = self._hmm_detector.predict(prices)
                            regime_label = hmm_result.label
                            self._last_hmm_probs = hmm_result.probabilities
                            logger.debug(f"HMM [{self.symbol}]: {hmm_result.label} probs={hmm_result.probabilities}")
                except Exception as e:
                    logger.debug(f"HMM overlay unavailable [{self.symbol}]: {e}")

                self.risk_manager.set_regime(regime_label)
                self._last_regime = regime_label
                # Cache for dashboard
                regime_cache = self._multi_tf_regime.to_dict()
                regime_cache["hmm_probs"] = getattr(self, "_last_hmm_probs", None)
                await self.redis.setex(f"mtf_regime:{self.symbol}", 300, json.dumps(regime_cache))
            except Exception as e:
                logger.warning(f"Multi-TF regime detection failed: {e}")

            # 1c. Check macro event proximity — reduce exposure or skip
            from app.constants import EVENT_BLOCK_HOURS
            near_event = self._event_calendar.is_near_event(hours_before=EVENT_BLOCK_HOURS)
            if near_event:
                logger.info(f"Near macro event [{self.symbol}]: {near_event.get('event', 'unknown')} — reducing exposure")

            # 2. Generate trading signal
            result = await self._generate_signal()
            if result is None:
                return
            signal, signal_label, df = result

            # 3. Get AI sentiment and check trade permissions
            ai_sentiment = await self._get_ai_sentiment()

            if not await self._check_trade_permission(signal, signal_label, balance, ai_sentiment):
                return

            # 3b. Confirmation gate — require confirmations before trading
            #     Graceful: if data sources aren't ready, reduce required count
            try:
                from app.ai.confirmation_gate import ConfirmationGate
                from app.strategy.quant_signals import compute_all_signals

                prices = df["close"].values if len(df) > 30 else None
                # Count available data sources to set proportional requirement
                available_sources = sum([
                    prices is not None and len(prices) > 30,     # quant
                    hasattr(self.strategy, "_last_ml_signal"),     # ML
                    hasattr(self, "_last_hmm_probs"),              # regime
                    True,                                          # risk/reward (always available)
                    ai_sentiment is not None,                      # AI
                ])
                # Skip gate if not enough data sources ready (< 3)
                if available_sources < 3:
                    logger.debug(f"Confirmation gate skipped [{self.symbol}]: only {available_sources}/5 sources available")
                    raise RuntimeError("skip")  # caught by except below → proceed without gate
                # Require majority of available sources (at least 2)
                required = max(2, (available_sources + 1) // 2)
                gate = ConfirmationGate(required=required)

                quant_data = None
                if prices is not None and len(prices) > 30:
                    qs = compute_all_signals(prices)
                    quant_data = qs.to_dict()

                ml_data = None
                if hasattr(self.strategy, "_last_ml_signal"):
                    ml_data = {
                        "signal": getattr(self.strategy, "_last_ml_signal", 0),
                        "confidence": getattr(self.strategy, "_last_ml_confidence", 0),
                    }

                regime_data = None
                if hasattr(self, "_last_hmm_probs"):
                    regime_data = {"label": str(self._last_regime), "probabilities": self._last_hmm_probs}

                atr_val = df.iloc[-2].get("atr", 0)
                entry_est = df["close"].iloc[-1]
                sl_est = atr_val * self.risk_manager.sl_atr_mult
                tp_est = atr_val * self.risk_manager.tp_atr_mult
                rr_data = {"ratio": tp_est / sl_est if sl_est > 0 else 0}

                ai_agrees = ai_sentiment and ai_sentiment.get("label") in (
                    "bullish" if signal == 1 else "bearish",
                    "neutral",
                )
                ai_data = {
                    "agrees": bool(ai_agrees),
                    "confidence": ai_sentiment.get("confidence", 0) if ai_sentiment else 0,
                    "reasoning": ai_sentiment.get("label", "") if ai_sentiment else "",
                }

                gate_result = gate.evaluate(
                    signal=signal,
                    quant_signals=quant_data,
                    ml_prediction=ml_data,
                    regime=regime_data,
                    risk_reward=rr_data,
                    ai_reasoning=ai_data,
                )

                self._last_confirmation = gate_result.to_dict()
                logger.info(
                    f"Confirmation gate [{self.symbol}]: {gate_result.passed_count}/5 "
                    f"(need {gate_result.required}) → {gate_result.decision}"
                )

                if not gate_result.approved:
                    await self._log_event(
                        BotEventType.TRADE_BLOCKED,
                        f"{signal_label} blocked: confirmation gate {gate_result.passed_count}/{gate_result.required}",
                    )
                    return

            except Exception as e:
                logger.debug(f"Confirmation gate skipped [{self.symbol}]: {e}")

            # 4. Size position and place order
            await self._size_and_place_order(signal, signal_label, df, balance, ai_sentiment, near_event=near_event)

        except Exception as e:
            logger.error(f"Bot engine error: {e}")
            self.state = BotState.ERROR
            await self._log_event(BotEventType.ERROR, str(e))
            if self.notifier:
                await self._notify(self.notifier.send_error_alert(f"Bot engine error: {e}"))

    async def _check_circuit_breakers(self, balance: float) -> bool:
        """Check per-symbol and global circuit breakers. Returns True if trading should stop."""
        import asyncio as _asyncio

        all_symbols = settings.symbol_list
        symbol_triggered, global_triggered = await _asyncio.gather(
            self.circuit_breaker.is_triggered(balance),
            CircuitBreaker.is_global_triggered(self.redis, all_symbols, balance),
        )

        if symbol_triggered:
            self.state = BotState.PAUSED
            await self._log_event(BotEventType.CIRCUIT_BREAKER, "Circuit breaker triggered")
            if self.notifier:
                await self._notify(self.notifier.send_error_alert("⚡ Circuit breaker triggered — bot paused"))
            return True

        if global_triggered:
            self.state = BotState.PAUSED
            await self._log_event(BotEventType.CIRCUIT_BREAKER, "Portfolio circuit breaker triggered (global daily loss)")
            if self.notifier:
                await self._notify(self.notifier.send_error_alert("⚡ Portfolio circuit breaker — ALL symbols paused"))
            return True

        # Absolute drawdown from peak balance
        drawdown_halted = await CircuitBreaker.is_drawdown_halted(
            self.redis, balance, settings.max_drawdown_from_peak,
        )
        if drawdown_halted:
            self.state = BotState.PAUSED
            await self._log_event(BotEventType.CIRCUIT_BREAKER, "Absolute drawdown limit reached — trading halted")
            if self.notifier:
                await self._notify(self.notifier.send_error_alert(
                    f"🛑 DRAWDOWN HALT: Balance dropped >{settings.max_drawdown_from_peak:.0%} from peak"
                ))
            return True

        return False

    async def _generate_signal(self) -> tuple[int, str, "pd.DataFrame"] | None:
        """Fetch OHLCV, calculate strategy, apply MTF filter. Returns (signal, label, df) or None."""
        df = await self.market_data.get_ohlcv(self.symbol, self.timeframe, DEFAULT_OHLCV_BARS)
        if df.empty:
            return None

        # Lazy-load ML model from DB if strategy supports it
        if hasattr(self.strategy, "_ensure_model"):
            await self.strategy._ensure_model()

        # Fetch cross-symbol data for quant strategies (risk parity, momentum rank, pair spread)
        if hasattr(self.strategy, "_prepare_cross_data"):
            await self.strategy._prepare_cross_data(self.market_data)

        df = self.strategy.calculate(df)
        if len(df) < 2:
            return None

        signal = int(df.iloc[-2]["signal"])  # Previous bar's signal (confirmed candle)
        if signal == 0:
            return None

        # Multi-timeframe H1 trend confirmation
        if settings.use_mtf_filter:
            h1_df = await self.market_data.get_ohlcv(self.symbol, "H1", H1_BARS)
            h1_trend = _get_h1_trend(h1_df)
            if h1_trend != 0 and h1_trend != signal:
                h1_label = "uptrend" if h1_trend == 1 else "downtrend"
                signal_label_tmp = "BUY" if signal == 1 else "SELL"
                logger.info(f"MTF filter blocked: M15={signal_label_tmp}, H1={h1_label}")
                await self._log_event(
                    BotEventType.TRADE_BLOCKED,
                    f"{signal_label_tmp} blocked: H1 {h1_label} disagrees"
                )
                return None

        self.last_signal_time = datetime.now(timezone.utc)
        signal_label = "BUY" if signal == 1 else "SELL"
        logger.info(f"Signal detected: {signal_label}")
        await self._log_event(BotEventType.SIGNAL_DETECTED, f"{signal_label} signal on {self.symbol}")
        await self._push_event("bot_event", {"type": "signal_detected", "signal": signal_label, "symbol": self.symbol})
        if self.notifier:
            await self._notify(self.notifier._send(f"📊 <b>Signal: {signal_label}</b> on {self.symbol}"))

        return signal, signal_label, df

    async def _get_ai_sentiment(self) -> dict | None:
        """Get AI sentiment if enabled. Returns sentiment dict or None."""
        if self.sentiment_analyzer and self.risk_manager.use_ai_filter:
            sentiment = await self.sentiment_analyzer.get_latest_sentiment(self.symbol)
            if sentiment.confidence > 0:
                return {"label": sentiment.label, "confidence": sentiment.confidence}
        return None

    async def _check_trade_permission(
        self, signal: int, signal_label: str, balance: float, ai_sentiment: dict | None,
    ) -> bool:
        """Check risk limits, portfolio exposure, and correlation conflicts. Returns True if allowed."""
        import asyncio as _asyncio

        positions, daily_pnl = await _asyncio.gather(
            self.executor.get_open_positions(self.symbol),
            self.circuit_breaker.get_daily_pnl(),
        )

        trade_patterns = None
        if self._ai_context:
            trade_patterns = self.context_builder.get_trade_patterns_for_risk(self._ai_context)

        # Adaptive confidence: compute effective threshold
        eff_threshold = None
        try:
            from app.config import SESSION_PROFILES
            current_hour = datetime.now(timezone.utc).hour
            session_boost = 0.0
            for prof in SESSION_PROFILES.values():
                h_start, h_end = prof["hours"]
                if h_start <= current_hour < h_end:
                    session_boost = prof.get("confidence_boost", 0.0)
                    break

            # Recent win rate
            recent_wr = None
            from app.constants import CONFIDENCE_RECENT_TRADES_WINDOW
            from sqlalchemy import select as _sel2
            stmt = (_sel2(Trade).where(Trade.symbol == self.symbol, Trade.profit.isnot(None))
                    .order_by(Trade.id.desc()).limit(CONFIDENCE_RECENT_TRADES_WINDOW))
            result = await self.db.execute(stmt)
            recent = result.scalars().all()
            if len(recent) >= 10:
                recent_wr = sum(1 for t in recent if t.profit > 0) / len(recent)

            # Drawdown
            dd_pct = 0.0
            peak_raw = await self.redis.get("circuit:peak_balance")
            if peak_raw and balance > 0:
                peak = float(peak_raw)
                if peak > 0:
                    dd_pct = (peak - balance) / peak

            regime = self._multi_tf_regime.composite if self._multi_tf_regime else self._last_regime
            eff_threshold = self.risk_manager.compute_effective_confidence(
                session_boost=session_boost, regime=regime,
                recent_win_rate=recent_wr, drawdown_pct=dd_pct,
            )
            self._last_effective_threshold = eff_threshold
        except Exception:
            pass

        can_trade, reason = self.risk_manager.can_open_trade(
            current_positions=len(positions),
            daily_pnl=daily_pnl,
            balance=balance,
            signal=signal,
            ai_sentiment=ai_sentiment,
            trade_patterns=trade_patterns,
            effective_threshold=eff_threshold,
        )
        if not can_trade:
            logger.info(f"Trade blocked: {reason}")
            await self._log_event(BotEventType.TRADE_BLOCKED, f"{signal_label} blocked: {reason}")
            await self._push_event("bot_event", {"type": "trade_blocked", "signal": signal_label, "reason": reason})
            if self.notifier:
                await self._notify(self.notifier._send(f"🚫 <b>{signal_label} Blocked</b>\n{reason}"))
            return False

        # Check portfolio exposure limit
        if self._manager:
            can_trade_portfolio, portfolio_reason = await self._manager.check_portfolio_limit(balance)
            if not can_trade_portfolio:
                logger.info(f"Portfolio limit: {portfolio_reason}")
                await self._log_event(BotEventType.TRADE_BLOCKED, portfolio_reason)
                await self._push_event("bot_event", {"type": "trade_blocked", "signal": signal_label, "reason": portfolio_reason})
                return False

        # Check symbol correlation conflicts (rolling correlation if data available)
        if self._manager:
            from app.risk.correlation import check_correlation_conflict, compute_rolling_correlation
            active_positions = await self._manager.get_active_positions()

            # Try rolling correlation, fall back to static
            try:
                price_series = {}
                for sym, eng in self._manager.engines.items():
                    ohlcv = await eng.market_data.get_ohlcv(sym, eng.timeframe, 60)
                    if ohlcv is not None and len(ohlcv) > 30:
                        price_series[sym] = ohlcv["close"].values
                if len(price_series) >= 2:
                    rolling_matrix = compute_rolling_correlation(price_series, window=30)
                    # Update global CORRELATIONS with rolling values for this check
                    from app.risk import correlation as _corr_mod
                    _corr_mod.CORRELATIONS = {**_corr_mod.STATIC_CORRELATIONS, **rolling_matrix.matrix}
            except Exception as e:
                logger.debug(f"Rolling correlation unavailable, using static: {e}")

            has_conflict, conflict_reason = check_correlation_conflict(self.symbol, signal, active_positions)
            if has_conflict:
                logger.info(f"Correlation conflict: {conflict_reason}")
                await self._log_event(BotEventType.TRADE_BLOCKED, conflict_reason)
                await self._push_event("bot_event", {"type": "trade_blocked", "signal": signal_label, "reason": conflict_reason})
                return False

        return True

    async def _size_and_place_order(
        self, signal: int, signal_label: str, df, balance: float, ai_sentiment: dict | None,
        near_event: dict | None = None,
    ) -> None:
        """Calculate lot size, apply adjustments, and place order (real or paper)."""
        atr = df.iloc[-2].get("atr", DEFAULT_ATR_FALLBACK)
        tick = await self.market_data.get_current_tick(self.symbol)
        if not tick:
            return

        entry_price = tick["ask"] if signal == 1 else tick["bid"]
        atr_pct = atr / entry_price if entry_price > 0 else 0

        # GARCH volatility forecast (use for sizing, fallback to ATR if fails)
        garch_vol = None
        try:
            from app.risk.garch import fit_garch
            prices = df["close"].values
            if len(prices) > 50:
                garch_result = fit_garch(prices, window=min(200, len(prices)))
                garch_vol = garch_result.forecast_1
                self._last_garch = garch_result.to_dict()
                logger.debug(f"GARCH [{self.symbol}]: forecast={garch_vol:.6f} method={garch_result.method}")
        except Exception as e:
            logger.debug(f"GARCH unavailable [{self.symbol}]: {e}")

        # Use GARCH vol for sizing if available, otherwise ATR
        effective_vol_pct = garch_vol * 100 if garch_vol else atr_pct

        # Detect regime and apply to risk manager
        from app.strategy.regime import detect_regime as _detect_regime
        adx_value = df.iloc[-2].get("adx", 20)
        regime = _detect_regime(atr_pct, adx_value)
        self.risk_manager.set_regime(regime)

        # Log regime change (Telegram skipped — view in dashboard instead)
        if regime != self._last_regime:
            old_regime = self._last_regime
            self._last_regime = regime
            await self._log_event(BotEventType.SIGNAL_DETECTED, f"Regime: {old_regime} → {regime}")

        sl_tp = self.risk_manager.calculate_sl_tp(entry_price, signal, atr)
        sl_pips = abs(entry_price - sl_tp.sl)

        # Position sizing: fixed lot or AI-calculated (Kelly/risk-based)
        if self.fixed_lot is not None:
            lot = round(min(self.fixed_lot, self.risk_manager.max_lot), 2)
            lot = max(lot, MIN_LOT)
        else:
            lot = await self._calculate_position_size(balance, sl_pips, effective_vol_pct)
            # Apply warmup ramp-in
            lot = self._apply_warmup(lot)
            # Apply consecutive loss streak reduction
            lot = await self._apply_streak_adjustment(lot)

        # Event filter: reduce lot near high-impact events
        if near_event:
            from app.constants import EVENT_LOT_FACTOR
            lot = round(lot * EVENT_LOT_FACTOR, 2)
            lot = max(lot, MIN_LOT)
            logger.info(f"Event filter [{self.symbol}]: lot reduced to {lot} (event: {near_event.get('event', 'unknown')})")

        # Place order (real or paper)
        order_type = "BUY" if signal == 1 else "SELL"
        comment = f"{self.strategy.name}"
        tag = "📝 PAPER" if self.paper_trade else ""

        start_time = time.monotonic()
        if self.paper_trade:
            result = self._create_paper_order(order_type, lot, entry_price, sl_tp, comment)
        else:
            result = await self.executor.place_order(
                self.symbol, order_type, lot, sl_tp.sl, sl_tp.tp, comment
            )
        latency_ms = int((time.monotonic() - start_time) * 1000)

        # Audit log (truly fire-and-forget — don't block order path)
        import asyncio as _asyncio
        _asyncio.create_task(self._log_order_audit(
            order_type, lot, sl_tp.sl, sl_tp.tp, entry_price, result,
            self.strategy.name, latency_ms,
        ))

        if not result.get("success"):
            error_msg = result.get("error", "Unknown error")
            logger.error(f"Order failed: {order_type} {lot} {self.symbol} — {error_msg}")
            await self._log_event(BotEventType.ORDER_FAILED, f"{order_type} {lot} {self.symbol}: {error_msg}")
            await self._push_event("bot_event", {"type": "order_failed", "order": order_type, "symbol": self.symbol, "lot": lot, "error": error_msg})
            if self.notifier:
                await self._notify(self.notifier._send(f"❌ <b>Order Failed</b>\n{order_type} {lot} {self.symbol}\n{error_msg}"))
            return

        # Save trade to DB
        sentiment_data = ai_sentiment or {}
        actual_fill = result["data"].get("price", entry_price)

        slippage_price = abs(actual_fill - entry_price)
        if slippage_price > 0:
            logger.info(f"Slippage [{self.symbol}]: expected={entry_price}, fill={actual_fill}, diff={slippage_price:.{self.risk_manager.price_decimals}f}")

        # Pre-trade snapshot — complete decision context for tracing
        snapshot = {
            "balance": balance,
            "regime": self._multi_tf_regime.to_dict() if self._multi_tf_regime else {"composite": self._last_regime},
            "indicators": {
                "atr": round(atr, 4),
                "atr_pct": round(atr_pct, 6),
                "garch_vol": round(garch_vol, 6) if garch_vol else None,
                "effective_vol_pct": round(effective_vol_pct, 6),
                "adx": round(float(df.iloc[-2].get("adx", 0)), 2) if "adx" in df.columns else None,
            },
            "risk": {
                "effective_confidence": getattr(self, "_last_effective_threshold", None),
                "lot_final": lot,
                "near_event": bool(near_event),
            },
            "ai_sentiment": ai_sentiment,
            "strategy": self.strategy.name,
            "strategy_reason": self.strategy.last_reason,
        }

        trade = Trade(
            ticket=result["data"]["ticket"],
            symbol=self.symbol,
            type=order_type,
            lot=lot,
            open_price=actual_fill,
            expected_price=entry_price,
            sl=sl_tp.sl,
            tp=sl_tp.tp,
            open_time=_naive_utc(),
            strategy_name=self.strategy.name,
            ai_sentiment_score=sentiment_data.get("confidence"),
            ai_sentiment_label=sentiment_data.get("label"),
            trade_reason=self.strategy.last_reason or None,
            pre_trade_snapshot=snapshot,
        )
        await self._save_trade(trade)

        await self._log_event(
            BotEventType.TRADE_OPENED,
            f"{tag}{order_type} {lot} {self.symbol} @ {entry_price} SL={sl_tp.sl} TP={sl_tp.tp}",
        )
        await self._push_event("bot_event", {
            "type": "trade_opened",
            "data": result["data"],
            "sentiment": sentiment_data,
        })

        # Store ATR for trailing stop
        self._position_atr[result["data"]["ticket"]] = atr
        self._position_atr_pct[result["data"]["ticket"]] = atr_pct
        self._position_entry_time[result["data"]["ticket"]] = _naive_utc()

        if self.notifier:
            paper_label = " [PAPER]" if self.paper_trade else ""
            await self._notify(self.notifier.send_trade_alert(
                f"{order_type}{paper_label}", self.symbol, entry_price, sl_tp.sl, sl_tp.tp, lot,
                sentiment_data.get("label", ""),
            ))

    def _apply_warmup(self, lot: float) -> float:
        """Reduce lot during warmup period."""
        if not self.started_at:
            return lot
        elapsed = (datetime.now(timezone.utc) - self.started_at).total_seconds()
        if elapsed < WARMUP_SECONDS:
            ramp_pct = max(elapsed / WARMUP_SECONDS, WARMUP_MIN_LOT_PCT)
            lot = max(round(lot * ramp_pct, 2), MIN_LOT)
            logger.info(f"Warmup ramp-in [{self.symbol}]: {ramp_pct:.0%} — lot={lot}")
        return lot

    async def _apply_streak_adjustment(self, lot: float) -> float:
        """Reduce lot after consecutive losses."""
        try:
            from sqlalchemy import select as _select
            stmt = (
                _select(Trade)
                .where(Trade.symbol == self.symbol, Trade.profit.isnot(None))
                .order_by(Trade.id.desc())
                .limit(STREAK_RECENT_TRADES)
            )
            result = await self.db.execute(stmt)
            recent = result.scalars().all()
            consecutive_losses = 0
            for t in recent:
                if t.profit <= 0:
                    consecutive_losses += 1
                else:
                    break
            if consecutive_losses >= 2:
                lot = self.risk_manager.adjust_for_streak(lot, consecutive_losses, 0)
                logger.info(f"Loss streak [{self.symbol}]: {consecutive_losses} consecutive → lot={lot}")
                # Alert on significant losing streak
                from app.constants import LOSING_STREAK_ALERT_THRESHOLD
                if consecutive_losses >= LOSING_STREAK_ALERT_THRESHOLD and self.notifier:
                    factor = STREAK_3_FACTOR if consecutive_losses >= 3 else STREAK_2_FACTOR
                    import asyncio as _asyncio
                    _asyncio.create_task(self.notifier.send_losing_streak_alert(self.symbol, consecutive_losses, factor))
        except Exception:
            pass
        return lot

    def _create_paper_order(self, order_type: str, lot: float, entry_price: float, sl_tp, comment: str) -> dict:
        """Create a simulated paper trade order."""
        self._paper_ticket_counter += 1
        ticket = self._paper_ticket_counter
        signal = 1 if order_type == "BUY" else -1
        tick_size = 10 ** (-self.risk_manager.price_decimals)
        slippage = random.uniform(1, 3) * tick_size
        fill_price = entry_price + slippage if signal == 1 else entry_price - slippage
        fill_price = round(fill_price, self.risk_manager.price_decimals)
        result = {"success": True, "data": {
            "ticket": ticket, "price": fill_price,
            "lot": lot, "type": order_type,
        }}
        self._paper_positions.append({
            "ticket": ticket, "symbol": self.symbol,
            "type": order_type, "lot": lot,
            "open_price": fill_price, "current_price": fill_price,
            "sl": sl_tp.sl, "tp": sl_tp.tp,
            "profit": 0.0, "open_time": datetime.now(timezone.utc).isoformat(),
            "comment": comment, "magic": MT5_MAGIC_NUMBER,
        })
        logger.info(f"PAPER trade: {order_type} {lot} {self.symbol} @ {entry_price}")
        return result

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
                self._last_sentiment = result.to_dict()
                await self._push_event("sentiment_update", {**result.to_dict(), "symbol": self.symbol})
                # Sentiment alerts skipped from Telegram — view in dashboard instead
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

            # Safety: if fetch returned empty but we have known positions, skip sync
            # (likely a timeout, not all positions actually closed)
            if not positions and len(self._known_tickets) > 0 and not self.paper_trade:
                logger.warning(f"Position fetch returned empty but {len(self._known_tickets)} known — skipping sync (possible timeout)")
                return

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
                    self._position_entry_time.pop(ticket, None)
                    self._position_partial_closed.discard(ticket)
                    self._position_breakeven.discard(ticket)

            self._known_tickets = current_tickets

            # Apply trailing stops (real mode only — paper handles SL/TP internally)
            if self.trailing_stop_enabled and positions and not self.paper_trade:
                await self._apply_trailing_stops(positions)

            await self._push_event("position_update", {"symbol": self.symbol, "positions": positions})
        except Exception as e:
            logger.error(f"Position sync error: {e}")

    async def _handle_closed_trades(self, closed_tickets: set[int]):
        """Fetch close details from MT5 history and update DB."""
        history_result = await self.connector.get_history(days=1)
        history_deals = history_result.get("data", []) if history_result.get("success") else []
        history_map = {d["ticket"]: d for d in history_deals}

        for ticket in closed_tickets:
            self._position_atr.pop(ticket, None)
            self._position_entry_time.pop(ticket, None)
            self._position_partial_closed.discard(ticket)
            self._position_breakeven.discard(ticket)
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
                # Post-trade analysis
                analysis = self._build_post_trade_analysis(trade, deal, self._multi_tf_regime)
                trade.post_trade_analysis = analysis
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

            # Telegram notification (enhanced with analysis)
            if self.notifier:
                if trade and trade.post_trade_analysis:
                    await self._notify(self.notifier.send_trade_close_with_analysis(
                        self.symbol, close_price, deal.get("lot", 0) if deal else 0,
                        profit, trade.post_trade_analysis,
                    ))
                else:
                    await self._notify(self.notifier.send_trade_alert(
                        "CLOSE", self.symbol, close_price, 0, 0, deal.get("lot", 0) if deal else 0,
                        extra=profit_str,
                    ))

            # ML prediction feedback: link closed trade outcome to recent prediction
            await self._update_prediction_feedback(profit)

    @staticmethod
    def _build_post_trade_analysis(trade, deal: dict | None, mtf_regime) -> dict:
        """Generate post-trade analysis: exit reason, duration, outcome summary."""
        exit_reason = "unknown"
        if trade.close_price and trade.sl and trade.tp:
            sl_dist = abs(trade.close_price - trade.sl)
            tp_dist = abs(trade.close_price - trade.tp)
            entry_to_sl = abs(trade.open_price - trade.sl) or 1
            entry_to_tp = abs(trade.open_price - trade.tp) or 1
            if sl_dist < entry_to_sl * 0.2:
                exit_reason = "stop_loss"
            elif tp_dist < entry_to_tp * 0.2:
                exit_reason = "take_profit"
            else:
                exit_reason = "manual_close"

        duration_hours = None
        if trade.open_time and trade.close_time:
            delta = trade.close_time - trade.open_time
            duration_hours = round(delta.total_seconds() / 3600, 2)

        profit = trade.profit or 0
        outcome = "win" if profit > 0 else ("breakeven" if profit == 0 else "loss")

        parts = []
        if exit_reason == "stop_loss":
            parts.append("SL ถูกชน")
        elif exit_reason == "take_profit":
            parts.append("ถึง TP สำเร็จ")
        else:
            parts.append("ปิดด้วยตนเอง/ระบบ")
        if duration_hours is not None:
            parts.append(f"ถือ {int(duration_hours * 60)} นาที" if duration_hours < 1 else f"ถือ {duration_hours:.1f} ชม.")

        snap = trade.pre_trade_snapshot or {}
        entry_regime = snap.get("regime", {}).get("composite", "unknown")

        return {
            "exit_reason": exit_reason,
            "duration_hours": duration_hours,
            "outcome": outcome,
            "profit_usd": round(profit, 2),
            "entry_regime": entry_regime,
            "exit_regime": mtf_regime.composite if mtf_regime else None,
            "summary_th": " | ".join(parts),
        }

    async def _update_prediction_feedback(self, profit: float) -> None:
        """Find matching MLPredictionLog and set was_correct + actual_outcome."""
        try:
            from app.db.models import MLPredictionLog
            from app.constants import PREDICTION_FEEDBACK_HOURS
            from sqlalchemy import select, and_
            cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=PREDICTION_FEEDBACK_HOURS)
            stmt = (
                select(MLPredictionLog)
                .where(and_(
                    MLPredictionLog.symbol == self.symbol,
                    MLPredictionLog.was_correct.is_(None),
                    MLPredictionLog.created_at >= cutoff,
                ))
                .order_by(MLPredictionLog.created_at.desc())
                .limit(1)
            )
            result = await self.db.execute(stmt)
            pred = result.scalar_one_or_none()
            if pred:
                actual = 1 if profit > 0 else -1
                pred.actual_outcome = actual
                # BUY prediction (+1) correct if profit > 0, SELL (-1) correct if profit > 0
                pred.was_correct = (pred.predicted_signal == actual) or (pred.predicted_signal == 0 and abs(profit) < 1)
                await self.db.commit()
                logger.info(f"ML feedback [{self.symbol}]: prediction={pred.predicted_signal}, outcome={actual}, correct={pred.was_correct}")
        except Exception as e:
            try:
                await self.db.rollback()
            except Exception:
                pass
            logger.warning(f"ML feedback update failed: {e}")

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
        """Enhanced trailing: time exit → breakeven → partial TP → chandelier trail."""
        for pos in positions:
            ticket = pos["ticket"]
            pos_atr = self._position_atr.get(ticket)
            if not pos_atr or pos_atr <= 0:
                continue

            current_price = pos.get("current_price", 0)
            open_price = pos.get("open_price", 0)
            current_sl = pos.get("sl", 0)
            pos_type = pos.get("type", "")
            lot = pos.get("lot", 0)

            # Stage 0: Time-based exit — close after max duration
            entry_time = self._position_entry_time.get(ticket)
            if entry_time:
                elapsed_hours = (_naive_utc() - entry_time).total_seconds() / 3600
                max_hours = settings.max_position_duration_hours
                if max_hours > 0 and elapsed_hours > max_hours:
                    logger.info(f"Time exit {pos_type} {ticket}: {elapsed_hours:.1f}h > {max_hours}h")
                    await self.executor.close_position(ticket)
                    continue

            if pos_type == "BUY":
                profit_distance = current_price - open_price
            elif pos_type == "SELL":
                profit_distance = open_price - current_price
            else:
                continue

            # Stage 1: Breakeven stop after profit > BREAKEVEN_ATR_MULT * ATR
            if profit_distance > pos_atr * BREAKEVEN_ATR_MULT and ticket not in self._position_breakeven:
                # Use symbol-appropriate tick size (1 pip above/below entry)
                tick_size = 10 ** (-self.risk_manager.price_decimals)
                be_price = open_price + (tick_size if pos_type == "BUY" else -tick_size)
                if pos_type == "BUY" and be_price > current_sl:
                    logger.info(f"Breakeven stop BUY {ticket}: SL → {be_price:.{self.risk_manager.price_decimals}f}")
                    await self.executor.modify_position(ticket, sl=round(be_price, self.risk_manager.price_decimals))
                    self._position_breakeven.add(ticket)
                elif pos_type == "SELL" and (current_sl == 0 or be_price < current_sl):
                    logger.info(f"Breakeven stop SELL {ticket}: SL → {be_price:.{self.risk_manager.price_decimals}f}")
                    await self.executor.modify_position(ticket, sl=round(be_price, self.risk_manager.price_decimals))
                    self._position_breakeven.add(ticket)

            # Stage 1b: Partial TP — close and reopen at reduced lot
            if ticket not in self._position_partial_closed and profit_distance >= pos_atr * settings.partial_tp_atr_mult:
                self._position_partial_closed.add(ticket)
                if settings.enable_partial_tp:
                    await self._execute_partial_tp(ticket, pos_type, lot, open_price, current_sl, pos.get("tp", 0))
                    continue  # skip trailing — position replaced
                else:
                    logger.info(f"Partial TP mark {pos_type} {ticket}: profit={profit_distance:.{self.risk_manager.price_decimals}f}")

            # Stage 2: Chandelier trailing after profit > start threshold
            # Adaptive trail step based on volatility at entry
            atr_pct = self._position_atr_pct.get(ticket, DEFAULT_ATR_PCT_FALLBACK)
            trail_step = self.trailing_step_atr
            if atr_pct > HIGH_VOL_THRESHOLD:
                trail_step *= HIGH_VOL_TRAIL_FACTOR  # wider in high vol
            elif atr_pct < LOW_VOL_THRESHOLD:
                trail_step *= LOW_VOL_TRAIL_FACTOR  # tighter in low vol

            # Profit-lock ratchet: tighten once profit exceeds 2x ATR
            if profit_distance >= pos_atr * PROFIT_LOCK_ATR_MULT:
                trail_step = TIGHT_TRAIL_STEP_ATR

            if profit_distance >= pos_atr * self.trailing_start_atr:
                if pos_type == "BUY":
                    new_sl = current_price - pos_atr * trail_step
                    if new_sl > current_sl:
                        logger.info(f"Trailing BUY {ticket}: SL {current_sl} → {new_sl:.{self.risk_manager.price_decimals}f}")
                        await self.executor.modify_position(ticket, sl=round(new_sl, self.risk_manager.price_decimals))
                elif pos_type == "SELL":
                    new_sl = current_price + pos_atr * trail_step
                    if current_sl == 0 or new_sl < current_sl:
                        logger.info(f"Trailing SELL {ticket}: SL {current_sl} → {new_sl:.{self.risk_manager.price_decimals}f}")
                        await self.executor.modify_position(ticket, sl=round(new_sl, self.risk_manager.price_decimals))

    async def _execute_partial_tp(self, ticket: int, pos_type: str, lot: float, entry_price: float, current_sl: float, current_tp: float):
        """Close position and reopen at reduced lot for partial take profit."""
        try:
            # Close the full position
            close_result = await self.executor.close_position(ticket)
            if not close_result.get("success"):
                logger.warning(f"Partial TP close failed for {ticket}: {close_result.get('error')}")
                return

            # Reopen at reduced lot with SL at breakeven
            new_lot = max(round(lot * (1 - PARTIAL_TP_CLOSE_PCT), 2), MIN_LOT)
            if new_lot < MIN_LOT:
                logger.info(f"Partial TP {ticket}: remaining lot too small, fully closed")
                return

            tick_size = 10 ** (-self.risk_manager.price_decimals)
            be_sl = entry_price + (tick_size if pos_type == "BUY" else -tick_size)

            result = await self.executor.place_order(
                self.symbol, pos_type, new_lot, be_sl, current_tp,
                comment=f"partial_tp_from_{ticket}",
            )
            if result.get("success"):
                new_ticket = result["data"]["ticket"]
                actual_fill = result["data"].get("price", entry_price)
                atr = self._position_atr.get(ticket, DEFAULT_ATR_FALLBACK)
                atr_pct = self._position_atr_pct.get(ticket, DEFAULT_ATR_PCT_FALLBACK)
                self._position_atr[new_ticket] = atr
                self._position_atr_pct[new_ticket] = atr_pct
                self._position_entry_time[new_ticket] = _naive_utc()
                self._position_breakeven.add(new_ticket)  # already at breakeven

                # Save reopened position to DB
                trade = Trade(
                    ticket=new_ticket,
                    symbol=self.symbol,
                    type=pos_type,
                    lot=new_lot,
                    open_price=actual_fill,
                    expected_price=entry_price,
                    sl=be_sl,
                    tp=current_tp,
                    open_time=_naive_utc(),
                    strategy_name=f"partial_tp_from_{ticket}",
                )
                await self._save_trade(trade)

                logger.info(f"Partial TP {pos_type} {ticket}: closed, reopened {new_ticket} @ lot={new_lot}")
            else:
                logger.warning(f"Partial TP reopen failed for {ticket}: {result.get('error')}")

            # Clean up old ticket tracking
            self._position_atr.pop(ticket, None)
            self._position_atr_pct.pop(ticket, None)
            self._position_entry_time.pop(ticket, None)
        except Exception as e:
            logger.error(f"Partial TP execution error for {ticket}: {e}")

    async def _save_trade(self, trade: Trade, max_retries: int = 3):
        """Save trade to DB with retry and Redis fallback."""
        import asyncio as _asyncio

        for attempt in range(max_retries):
            try:
                self.db.add(trade)
                await self.db.commit()
                return
            except Exception as e:
                logger.warning(f"Trade save attempt {attempt + 1}/{max_retries} failed: {e}")
                try:
                    await self.db.rollback()
                except Exception:
                    pass
                if attempt < max_retries - 1:
                    await _asyncio.sleep(2 ** attempt)

        # Fallback: save to Redis for later reconciliation
        logger.error(f"DB save failed after {max_retries} attempts — saving to Redis for reconciliation")
        try:
            await self.redis.rpush(f"pending_trades:{self.symbol}", json.dumps({
                "ticket": trade.ticket,
                "symbol": trade.symbol,
                "type": trade.type,
                "lot": trade.lot,
                "open_price": trade.open_price,
                "expected_price": trade.expected_price,
                "sl": trade.sl,
                "tp": trade.tp,
                "open_time": trade.open_time.isoformat() if trade.open_time else None,
                "strategy_name": trade.strategy_name,
            }))
        except Exception as e:
            logger.error(f"Redis fallback also failed: {e}")

    async def _calculate_position_size(self, balance: float, sl_pips: float, atr_pct: float) -> float:
        """Use Kelly Criterion if >= 20 closed trades, otherwise fixed risk sizing."""
        try:
            from sqlalchemy import select
            stmt = (
                select(Trade)
                .where(Trade.symbol == self.symbol, Trade.profit.isnot(None))
                .order_by(Trade.id.desc())
                .limit(KELLY_RECENT_TRADES)
            )
            result = await self.db.execute(stmt)
            trades = result.scalars().all()

            if len(trades) >= MIN_KELLY_TRADES:
                wins = [t for t in trades if t.profit > 0]
                losses = [t for t in trades if t.profit <= 0]
                win_rate = len(wins) / len(trades)
                avg_win = sum(t.profit for t in wins) / len(wins) if wins else 0
                avg_loss = abs(sum(t.profit for t in losses) / len(losses)) if losses else 1

                if win_rate >= KELLY_MIN_WIN_RATE and avg_win > 0 and avg_loss > 0:
                    lot = self.risk_manager.calculate_kelly_size(
                        balance, sl_pips, win_rate, avg_win, avg_loss,
                    )
                    logger.info(f"Kelly sizing [{self.symbol}]: WR={win_rate:.0%}, lot={lot}")
                    return lot
        except Exception as e:
            logger.warning(f"Kelly sizing failed, using fixed risk: {e}")

        return self.risk_manager.calculate_lot_size(balance, sl_pips, atr_pct=atr_pct)

    async def update_strategy(self, name: str, params: dict | None = None):
        self.strategy = get_strategy(name, params, symbol=self.symbol)
        logger.info(f"Strategy updated [{self.symbol}]: {name} params={params}")

    async def update_settings(self, use_ai_filter: bool | None = None, ai_confidence_threshold: float | None = None, paper_trade: bool | None = None, timeframe: str | None = None, max_risk_per_trade: float | None = None, max_daily_loss: float | None = None, max_concurrent_trades: int | None = None, max_lot: float | None = None, fixed_lot: float | None | object = _UNSET):
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
        if fixed_lot is not _UNSET:
            self.fixed_lot = fixed_lot if fixed_lot is None else float(fixed_lot)
            logger.info(f"Lot sizing: {'fixed ' + str(self.fixed_lot) if self.fixed_lot else 'auto (AI)'}")

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

    async def _log_order_audit(
        self, order_type: str, lot: float, sl: float, tp: float,
        expected_price: float, result: dict, strategy_name: str, latency_ms: int,
    ):
        """Log order attempt to audit table (fire-and-forget, uses own session)."""
        try:
            from app.db.session import async_session

            success = result.get("success", False)
            audit = OrderAudit(
                symbol=self.symbol,
                order_type=order_type,
                requested_lot=lot,
                requested_sl=sl,
                requested_tp=tp,
                expected_price=expected_price,
                fill_price=result.get("data", {}).get("price") if success else None,
                ticket=result.get("data", {}).get("ticket") if success else None,
                status="FILLED" if success else "ERROR",
                error_message=result.get("error") if not success else None,
                signal_source=strategy_name,
                attempt_count=result.get("attempt_count", 1),
                latency_ms=latency_ms,
            )
            async with async_session() as session:
                session.add(audit)
                await session.commit()
        except Exception as e:
            logger.debug(f"Order audit log failed (non-critical): {e}")

    async def _push_event(self, channel: str, data: dict):
        try:
            await self.redis.publish(channel, json.dumps(data))
        except Exception as e:
            logger.error(f"Failed to push event: {e}")

    async def _recover_pending_trades(self):
        """Recover trades that failed DB save and were stored in Redis fallback."""
        key = f"pending_trades:{self.symbol}"
        try:
            pending = await self.redis.lrange(key, 0, -1)
            if not pending:
                return

            logger.info(f"Recovering {len(pending)} pending trades [{self.symbol}]")
            for raw in pending:
                try:
                    data = json.loads(raw)
                    trade = Trade(
                        ticket=data["ticket"],
                        symbol=data["symbol"],
                        type=data["type"],
                        lot=data["lot"],
                        open_price=data["open_price"],
                        expected_price=data.get("expected_price"),
                        sl=data.get("sl"),
                        tp=data.get("tp"),
                        open_time=datetime.fromisoformat(data["open_time"]) if data.get("open_time") else _naive_utc(),
                        strategy_name=data.get("strategy_name"),
                    )
                    self.db.add(trade)
                    await self.db.commit()
                    await self.redis.lrem(key, 1, raw)
                    logger.info(f"Recovered pending trade: ticket={data['ticket']}")
                except Exception as e:
                    logger.warning(f"Failed to recover pending trade: {e}")
                    try:
                        await self.db.rollback()
                    except Exception:
                        pass
        except Exception as e:
            logger.error(f"Pending trades recovery error [{self.symbol}]: {e}")

    async def reconcile_positions(self):
        """Compare DB open trades with MT5 positions to detect orphans and phantoms."""
        if self.paper_trade:
            return

        try:
            from sqlalchemy import select

            # 1. Get current MT5 positions
            positions = await self.executor.get_open_positions(self.symbol)
            mt5_tickets = {p["ticket"] for p in positions}

            # 2. Get DB trades that should be open (no close_time)
            stmt = (
                select(Trade)
                .where(Trade.symbol == self.symbol, Trade.close_time.is_(None))
            )
            result = await self.db.execute(stmt)
            db_trades = result.scalars().all()
            db_tickets = {t.ticket for t in db_trades}

            # 3. Orphan detection: in MT5 but not in DB → auto-adopt
            orphans = mt5_tickets - db_tickets
            if orphans:
                pos_map = {p["ticket"]: p for p in positions}
                adopted = []
                for ticket in orphans:
                    p = pos_map.get(ticket)
                    if not p:
                        continue
                    try:
                        open_time = datetime.fromisoformat(p["open_time"]) if isinstance(p.get("open_time"), str) else _naive_utc()
                        trade = Trade(
                            ticket=ticket,
                            symbol=self.symbol,
                            type=p.get("type", "BUY"),
                            lot=p.get("lot", 0.01),
                            open_price=p.get("open_price", 0),
                            sl=p.get("sl", 0),
                            tp=p.get("tp", 0),
                            open_time=open_time,
                            strategy_name=p.get("comment", "adopted_from_mt5") or "adopted_from_mt5",
                        )
                        self.db.add(trade)
                        await self.db.commit()
                        adopted.append(ticket)
                        logger.info(f"Auto-adopted orphan [{self.symbol}]: ticket={ticket}")
                    except Exception as e:
                        logger.warning(f"Failed to adopt orphan {ticket}: {e}")
                        try:
                            await self.db.rollback()
                        except Exception:
                            pass

                if adopted:
                    tickets_str = ", ".join(str(t) for t in sorted(adopted))
                    await self._log_event(
                        BotEventType.ERROR,
                        f"Auto-adopted orphaned positions: {tickets_str}",
                    )
                    if self.notifier:
                        await self._notify(self.notifier._send(
                            f"🔄 <b>Auto-adopted positions</b> [{self.symbol}]\n"
                            f"Tickets: {tickets_str}\n"
                            f"สร้าง record ใน DB ให้อัตโนมัติแล้ว"
                        ))

            # 4. Phantom detection: in DB but not in MT5
            phantoms = db_tickets - mt5_tickets
            if phantoms:
                logger.warning(f"Phantom records [{self.symbol}]: {phantoms} (in DB, not in MT5)")
                # Try to find close details from MT5 history
                history_result = await self.connector.get_history(days=7)
                history_deals = history_result.get("data", []) if history_result.get("success") else []
                history_map = {d["ticket"]: d for d in history_deals}

                for trade in db_trades:
                    if trade.ticket not in phantoms:
                        continue
                    deal = history_map.get(trade.ticket)
                    if deal:
                        trade.close_price = deal["price"]
                        trade.close_time = (
                            datetime.fromisoformat(deal["time"]).replace(tzinfo=None)
                            if deal.get("time")
                            else _naive_utc()
                        )
                        trade.profit = deal.get("profit", 0)
                        logger.info(f"Reconciled phantom #{trade.ticket}: closed @ {trade.close_price}, profit={trade.profit}")
                    else:
                        trade.close_time = _naive_utc()
                        trade.profit = 0
                        logger.warning(f"Reconciled phantom #{trade.ticket}: not found in 7-day history, marked closed with profit=0")

                await self.db.commit()
                await self._log_event(
                    BotEventType.ERROR,
                    f"Phantom records reconciled: {phantoms}",
                )

        except Exception as e:
            logger.error(f"Position reconciliation error [{self.symbol}]: {e}")
            try:
                await self.db.rollback()
            except Exception:
                pass
