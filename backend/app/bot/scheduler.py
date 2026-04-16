"""
Scheduler — APScheduler jobs for bot operations (multi-symbol).
"""

import asyncio
from collections import defaultdict
from datetime import UTC, datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from loguru import logger

from app.bot.engine import BotEngine, BotState
from app.config import settings

# Market close windows (UTC). None = 24/7 (e.g. crypto).
# daily_close: (start_hour, end_hour) when MT5 daily maintenance occurs.
MARKET_SCHEDULE = {
    "GOLD":    {"weekend": True, "daily_close": (22, 23)},
    "OILCash": {"weekend": True, "daily_close": (22, 23)},
    "BTCUSD":  {"weekend": False, "daily_close": None},
    "USDJPY":  {"weekend": True, "daily_close": (22, 22)},
}


def is_market_open(symbol: str) -> bool:
    """Check if the market for *symbol* is likely open on MT5."""
    from app.config import get_canonical_symbol
    now = datetime.utcnow()
    canonical = get_canonical_symbol(symbol)
    schedule = MARKET_SCHEDULE.get(canonical, MARKET_SCHEDULE.get(symbol, {"weekend": True, "daily_close": None}))

    # Weekend check (Saturday 00:00 – Sunday 23:59 UTC, approximate)
    if schedule["weekend"] and now.weekday() >= 5:
        return False

    # Daily close window
    dc = schedule.get("daily_close")
    if dc and dc[0] <= now.hour < dc[1]:
        return False

    return True

# Timeframe → cron schedule mapping
TIMEFRAME_CRON = {
    "M1":  {"minute": "*"},                          # every 1 min
    "M5":  {"minute": "0,5,10,15,20,25,30,35,40,45,50,55"},  # every 5 min
    "M15": {"minute": "0,15,30,45"},                 # every 15 min
    "M30": {"minute": "0,30"},                       # every 30 min
    "H1":  {"minute": "0"},                          # every hour
    "H4":  {"minute": "0", "hour": "0,4,8,12,16,20"},  # every 4 hours
    "D1":  {"minute": "0", "hour": "0"},             # daily
}


class BotScheduler:
    def __init__(self, manager):
        """Accept a BotManager (or legacy BotEngine for backward compat)."""
        from app.bot.manager import BotManager

        if isinstance(manager, BotManager):
            self.manager = manager
            self._legacy_bot: BotEngine | None = None
        else:
            # Backward compat: wrap single engine
            self.manager = None
            self._legacy_bot = manager

        self.scheduler = AsyncIOScheduler()
        self._candle_job_ids: dict[str, str] = {}  # timeframe → job_id
        self._health_monitor = None  # set via set_health_monitor()

    def set_health_monitor(self, monitor):
        self._health_monitor = monitor

    @property
    def _engines(self) -> dict[str, BotEngine]:
        if self.manager:
            return self.manager.engines
        return {self._legacy_bot.symbol: self._legacy_bot}

    def _get_cron_kwargs(self, timeframe: str) -> dict:
        return TIMEFRAME_CRON.get(timeframe, {"minute": "0,15,30,45"})

    def start(self):
        # Update price cache every 1 second
        self.scheduler.add_job(
            self._tick_job,
            "interval",
            seconds=1,
            id="bot_tick",
            max_instances=1,
            coalesce=True,
        )

        # Schedule candle jobs — one per unique timeframe
        self._schedule_candle_jobs()

        # Fetch sentiment every 15 minutes (offset by 2 min)
        self.scheduler.add_job(
            self._sentiment_job,
            "cron",
            minute="2,17,32,47",
            id="fetch_sentiment",
            max_instances=1,
            coalesce=True,
        )

        # Sync positions every 30 seconds
        self.scheduler.add_job(
            self._sync_job,
            "interval",
            seconds=30,
            id="sync_positions",
            max_instances=1,
            coalesce=True,
        )

        # Weekly optimization: Monday 06:00 UTC
        self.scheduler.add_job(
            self._weekly_optimize_job,
            "cron",
            day_of_week="mon",
            hour=6,
            minute=0,
            id="weekly_optimize",
            max_instances=1,
        )

        # Daily macro data collection: 07:00 UTC
        self.scheduler.add_job(
            self._macro_collect_job,
            "cron",
            hour=7,
            minute=0,
            id="macro_collect",
            max_instances=1,
        )

        # Daily reset: midnight UTC
        self.scheduler.add_job(
            self._daily_reset_job,
            "cron",
            hour=0,
            minute=0,
            id="daily_reset",
            max_instances=1,
        )

        # Weekly ML retrain: Monday 04:00 UTC (before market open, after macro collect)
        self.scheduler.add_job(
            self._ml_retrain_job,
            "cron",
            day_of_week="mon",
            hour=4,
            minute=0,
            id="ml_retrain",
            max_instances=1,
        )

        # Daily memory consolidation: 02:00 UTC (promote, expire, decay)
        self.scheduler.add_job(
            self._memory_consolidation_job,
            "cron",
            hour=2,
            minute=0,
            id="memory_consolidation",
            max_instances=1,
        )

        # Health check heartbeat every 30 seconds
        if self._health_monitor:
            self.scheduler.add_job(
                self._health_check_job,
                "interval",
                seconds=30,
                id="health_check",
                max_instances=1,
                coalesce=True,
            )

        # Pending trades recovery every 5 minutes
        self.scheduler.add_job(
            self._pending_trades_recovery_job,
            "interval",
            minutes=5,
            id="pending_trades_recovery",
            max_instances=1,
            coalesce=True,
        )

        # Position reconciliation every 5 minutes
        self.scheduler.add_job(
            self._reconciliation_job,
            "interval",
            minutes=5,
            id="position_reconciliation",
            max_instances=1,
            coalesce=True,
        )

        # Vault: OAuth token health check every 5 minutes
        self.scheduler.add_job(
            self._vault_health_job,
            "interval",
            minutes=5,
            id="vault_health_check",
            max_instances=1,
            coalesce=True,
        )

        # Daily trading summary: 22:00 UTC (forex market close)
        self.scheduler.add_job(
            self._daily_summary_job,
            "cron",
            hour=22,
            minute=0,
            id="daily_summary",
            max_instances=1,
        )

        # Economic calendar refresh every hour
        self.scheduler.add_job(
            self._refresh_economic_calendar,
            "interval",
            hours=1,
            id="economic_calendar_refresh",
            max_instances=1,
            coalesce=True,
        )

        self.scheduler.start()
        logger.info("Scheduler started")

        # Initial calendar refresh
        asyncio.create_task(self._refresh_economic_calendar())

    def _schedule_candle_jobs(self):
        """Create one cron job per unique timeframe across all engines."""
        # Remove existing candle jobs
        for job_id in self._candle_job_ids.values():
            try:
                self.scheduler.remove_job(job_id)
            except Exception:
                pass
        self._candle_job_ids.clear()

        # Group engines by timeframe
        tf_groups: dict[str, list[str]] = defaultdict(list)
        for symbol, engine in self._engines.items():
            tf_groups[engine.timeframe].append(symbol)

        for tf, symbols in tf_groups.items():
            cron_kwargs = self._get_cron_kwargs(tf)
            job_id = f"bot_candle_{tf}"
            self.scheduler.add_job(
                self._candle_job,
                "cron",
                **cron_kwargs,
                id=job_id,
                max_instances=1,
                coalesce=True,
                args=[symbols],
            )
            self._candle_job_ids[tf] = job_id
            logger.info(f"Candle job scheduled for {tf} ({symbols}): {cron_kwargs}")

    def reschedule_candle(self, symbol: str, timeframe: str):
        """Reschedule when a symbol's timeframe changes."""
        engine = self._engines.get(symbol)
        if engine:
            engine.timeframe = timeframe
        self._schedule_candle_jobs()
        logger.info(f"Candle jobs rescheduled after {symbol} changed to {timeframe}")

    def stop(self):
        self.scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")

    async def _tick_job(self):
        # Fetch ticks for ALL symbols (even STOPPED) so dashboard shows prices
        tasks = [self._fetch_tick(sym, eng) for sym, eng in self._engines.items()]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _fetch_tick(self, symbol: str, engine: BotEngine):
        try:
            tick = await engine.market_data.get_current_tick(symbol)
            if tick:
                tick["symbol"] = symbol
                await engine._push_event("price_update", tick)
        except Exception as e:
            logger.error(f"Tick job error [{symbol}]: {e}")

    async def _candle_job(self, symbols: list[str]):
        logger.debug(f"Candle job triggered for {symbols}")

        # Read trading_mode from Redis (survives redeploy), fallback to settings/env
        trading_mode = getattr(settings, "trading_mode", "strategy")
        try:
            first_engine = next(iter(self._engines.values()), None)
            if first_engine and first_engine.redis:
                cached_mode = await first_engine.redis.get("trading_mode")
                if cached_mode:
                    cached = cached_mode if isinstance(cached_mode, str) else cached_mode.decode()
                    if cached in ("strategy", "ai_autonomous"):
                        trading_mode = cached
                        settings.trading_mode = cached
                    else:
                        logger.warning(f"Invalid trading_mode in Redis: '{cached}', ignoring")
        except Exception as e:
            logger.debug(f"Redis trading_mode read failed: {e}")

        # Filter to symbols with open markets
        active_symbols = [sym for sym in symbols if is_market_open(sym)]
        skipped = [sym for sym in symbols if sym not in active_symbols]
        if skipped:
            logger.debug(f"Candle job: skipped {skipped} (market closed)")
        if not active_symbols:
            return

        if trading_mode == "strategy":
            for sym in active_symbols:
                engine = self._engines.get(sym)
                if engine and engine.state.value == "RUNNING":
                    try:
                        await engine.process_candle()
                    except Exception as e:
                        logger.error(f"process_candle error [{sym}]: {e}")
            asyncio.create_task(self._run_ai_agent(active_symbols))
        else:
            for sym in active_symbols:
                engine = self._engines.get(sym)
                if engine and engine.state.value == "RUNNING":
                    try:
                        await engine._detect_regime()
                    except Exception as e:
                        logger.debug(f"Regime detection [{sym}]: {e}")
            await self._run_ai_agent(active_symbols)

    async def _sentiment_job(self):
        """Fetch news sentiment only for symbols whose market is open and bot is running.

        Skips when market is closed (weekends for forex/metals, daily maintenance window)
        to reduce unnecessary API calls (~50% reduction).
        """
        tasks = []
        for sym, engine in self._engines.items():
            if engine.state != BotState.RUNNING:
                continue
            if not is_market_open(sym):
                logger.debug(f"Sentiment skipped [{sym}]: market closed")
                continue
            tasks.append(engine.fetch_and_analyze_sentiment())

        if tasks:
            logger.info(f"Sentiment job triggered for {len(tasks)} symbol(s)")
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for i, r in enumerate(results):
                if isinstance(r, Exception):
                    sym = list(self._engines.keys())[i] if i < len(self._engines) else "?"
                    logger.error(f"Sentiment fetch failed [{sym}]: {r}")
        else:
            logger.info("Sentiment job skipped: no active symbols with open market")

    async def _run_ai_agent(self, symbols: list[str]):
        """Run AI agent for each symbol — the primary trading decision-maker."""
        try:
            from mcp_server.agent_config import run_agent, run_multi_agent
        except ImportError:
            logger.error("CRITICAL: AI agent not available — trading disabled for this cycle!")
            # Notify via Telegram so operator knows trading is offline
            if self.manager:
                for engine in self.manager.engines.values():
                    if engine.notifier:
                        await engine._notify(engine.notifier.send_error_alert(
                            "⚠️ AI agent unavailable (mcp_server not importable) — trading disabled"
                        ))
                        break  # one notification is enough
            return

        async def _run_for_symbol(sym: str):
            engine = self._engines.get(sym)
            if not engine or engine.state.value != "RUNNING":
                return
            if not is_market_open(sym):
                logger.debug(f"AI agent skipped [{sym}]: market closed")
                return
            try:
                # Use multi-agent pipeline when agent_mode=multi (Reflector + Specialists + Orchestrator)
                # Single agent mode is analysis-only — it cannot place trades
                use_multi = getattr(settings, "agent_mode", "single") == "multi"
                if use_multi:
                    result = await run_multi_agent(
                        job_type="candle_analysis",
                        job_input={"symbol": sym, "timeframe": engine.timeframe},
                    )
                else:
                    result = await run_agent(
                        job_type="candle_analysis",
                        job_input={"symbol": sym, "timeframe": engine.timeframe},
                    )
                decision = result.get("decision", "HOLD")
                tool_calls = result.get("tool_calls", [])
                duration = result.get("duration_s", 0)
                logger.info(f"AI agent [{sym}]: {decision[:200]}")

                # Store last AI decision for dashboard display
                engine._last_ai_decision = {
                    "decision": decision[:3000],
                    "strategy": result.get("strategy_used", "ai_autonomous"),
                    "turns": result.get("turns", 0),
                    "tool_calls": len(tool_calls),
                    "duration_s": duration,
                    "timestamp": datetime.utcnow().isoformat(),
                }

                # Hallucination check — validate AI claims against real data
                try:
                    from app.ai.hallucination_check import check_hallucination
                    hc = await check_hallucination(decision, sym, engine.market_data)
                    engine._last_ai_decision["hallucination_check"] = hc
                    if hc.get("high_severity_count", 0) > 0:
                        logger.warning(f"AI hallucination [{sym}]: {hc['high_severity_count']} high-severity flags: {hc['flags']}")
                except Exception as e:
                    logger.debug(f"Hallucination check failed [{sym}]: {e}")

                # Log AI analysis to DB for activity page
                from app.db.models import BotEventType
                summary = f"[{sym}] {decision[:500]}"
                if tool_calls:
                    summary += f" | Tools: {len(tool_calls)}, {duration:.1f}s"
                await engine._log_event(BotEventType.AI_ANALYSIS, summary)

                # Publish to WebSocket for real-time dashboard update
                await engine._push_event("bot_event", {
                    "type": "AI_ANALYSIS",
                    "symbol": sym,
                    "decision": decision[:3000],
                    "strategy": result.get("strategy_used", "ai_autonomous"),
                    "turns": result.get("turns", 0),
                })
            except Exception as e:
                logger.warning(f"AI agent [{sym}] error: {e}")

        await asyncio.gather(*[_run_for_symbol(sym) for sym in symbols], return_exceptions=True)

    async def _sync_job(self):
        tasks = [e.sync_positions() for e in self._engines.values() if e.state.value == "RUNNING"]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _weekly_optimize_job(self):
        logger.info("Weekly optimization triggered")
        # Run optimization on first engine that has an optimizer
        for engine in self._engines.values():
            if not engine._optimizer or engine.strategy is None:
                continue
            try:
                result = await engine._optimizer.optimize(engine.strategy.get_params())
                if result:
                    logger.info(f"Optimization result [{engine.symbol}]: {result.assessment} (confidence={result.confidence})")
                    await engine._notify(engine.notifier.send_optimization_report(
                        result.assessment, result.confidence,
                    ))
                    # Auto-apply if feature flag ON and backtest confirms improvement.
                    # Read from Redis (not in-memory settings) so the flag survives restarts.
                    if result.backtest_validation and result.backtest_validation.get("suggested_better"):
                        flag_raw = await engine.redis.get("enable_auto_strategy_switch")
                        flag_on = (flag_raw == b"1" or flag_raw == "1") if flag_raw else False
                        if flag_on:
                            from mcp_server.strategy_switch_guard import StrategySwitchGuard
                            guard = StrategySwitchGuard(engine.redis)
                            strategy_name = engine.strategy.name if engine.strategy else "ema_crossover"
                            validation = await guard.validate_switch(engine.symbol, strategy_name)
                            if validation.allowed:
                                await engine.update_strategy(strategy_name, result.suggested_params)
                                await guard.record_switch(
                                    engine.symbol, strategy_name,
                                    f"Weekly optimizer: confidence={result.confidence}",
                                )
                                logger.info(
                                    f"[Optimizer Auto-Apply] [{engine.symbol}] "
                                    f"params={result.suggested_params} confidence={result.confidence}"
                                )
                            else:
                                logger.info(
                                    f"[Optimizer Auto-Apply] [{engine.symbol}] blocked: {validation.reason}"
                                )
            except Exception as e:
                logger.error(f"Weekly optimization error [{engine.symbol}]: {e}")

    async def _macro_collect_job(self):
        logger.info("Daily macro collection triggered")
        # Macro data is global, just use first engine
        for engine in self._engines.values():
            if hasattr(engine, '_macro_service') and engine._macro_service:
                try:
                    stats = await engine._macro_service.collect_all()
                    logger.info(f"Macro data collected: {stats}")
                except Exception as e:
                    logger.error(f"Macro collection error: {e}")
                break

    async def _refresh_economic_calendar(self):
        """Refresh economic calendar from API for all engines."""
        for engine in self._engines.values():
            try:
                count = await engine._event_calendar.refresh()
                logger.debug(f"Economic calendar refreshed: {count} events")
                break  # Only need to refresh once (shared cache)
            except Exception as e:
                logger.warning(f"Economic calendar refresh failed: {e}")

    async def _daily_reset_job(self):
        logger.info("Daily reset triggered")
        tasks = [e.circuit_breaker.reset() for e in self._engines.values()]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _daily_summary_job(self):
        """Daily trading summary at market close — sends Telegram report."""
        logger.info("Daily summary triggered")
        try:
            from datetime import datetime

            from sqlalchemy import and_, select

            from app.db.models import Trade

            symbol_stats = []
            total_pnl = 0.0
            total_trades = 0
            total_wins = 0

            for symbol, engine in self._engines.items():
                # Get today's closed trades
                today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
                stmt = select(Trade).where(and_(
                    Trade.symbol == symbol,
                    Trade.close_time >= today_start,
                    Trade.profit.isnot(None),
                ))
                result = await engine.db.execute(stmt)
                trades = result.scalars().all()

                pnl = sum(t.profit for t in trades)
                wins = sum(1 for t in trades if t.profit > 0)
                total_pnl += pnl
                total_trades += len(trades)
                total_wins += wins

                symbol_stats.append({
                    "symbol": symbol,
                    "pnl": round(pnl, 2),
                    "trades": len(trades),
                    "regime": engine.risk_manager.current_regime,
                })

            total_win_rate = total_wins / total_trades if total_trades > 0 else 0

            # Send via first engine's notifier
            notifier = next((e.notifier for e in self._engines.values() if e.notifier), None)
            if notifier:
                await notifier.send_daily_summary(symbol_stats, round(total_pnl, 2), total_trades, total_win_rate)
                logger.info(f"Daily summary sent: PnL=${total_pnl:.2f}, trades={total_trades}")
        except Exception as e:
            logger.error(f"Daily summary failed: {e}")

    async def _ml_retrain_job(self):
        """Weekly ML retrain — trains per-symbol on last 6 months of data."""
        logger.info("Weekly ML retrain triggered")
        for symbol, engine in self._engines.items():
            await self._ml_retrain_symbol(symbol, engine)

    async def _health_check_job(self):
        if self._health_monitor:
            await self._health_monitor.check()

    async def _pending_trades_recovery_job(self):
        tasks = [e._recover_pending_trades() for e in self._engines.values()]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _reconciliation_job(self):
        tasks = [
            e.reconcile_positions()
            for e in self._engines.values()
            if e.state.value in ("RUNNING", "PAUSED") and not e.paper_trade
        ]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _memory_consolidation_job(self):
        """Daily memory consolidation — promote, expire, decay memories."""
        try:
            from app.db.session import async_session
            from app.memory.consolidator import run_consolidation

            async with async_session() as db:
                result = await run_consolidation(db)
                logger.info(f"Memory consolidation: {result}")
        except Exception as e:
            logger.warning(f"Memory consolidation failed: {e}")

    async def _vault_health_job(self):
        """Check OAuth token health via vault."""
        try:
            from app.db.session import async_session
            from app.vault_health import check_oauth_health

            notifier = getattr(self.manager, "_notifier", None) if self.manager else None
            async with async_session() as db:
                await check_oauth_health(db, notifier=notifier)
        except Exception as e:
            logger.warning(f"Vault health check failed: {e}")

    async def _ml_retrain_symbol(self, symbol: str, engine):
        """Train ML model for a single symbol."""
        try:
            import io
            import json
            from datetime import timedelta

            import joblib
            from sqlalchemy import select, update

            from app.data.collector import DataCollector
            from app.db.models import MLModelLog
            from app.db.session import async_session

            model_name = f"lightgbm_{symbol.lower()}_auto"
            model_path = f"models/{symbol.lower()}_signal.pkl"

            async with async_session() as session:
                # Get current model accuracy for this symbol
                result = await session.execute(
                    select(MLModelLog)
                    .where(MLModelLog.is_active == True, MLModelLog.model_name == model_name)
                    .limit(1)
                )
                current_log = result.scalar_one_or_none()
                current_accuracy = 0.0
                if current_log and current_log.metrics:
                    metrics = json.loads(current_log.metrics)
                    current_accuracy = metrics.get("accuracy", 0.0)

                # Load last 90 days of data (sliding window)
                from_date = (datetime.utcnow() - timedelta(days=90)).strftime("%Y-%m-%d")
                collector = DataCollector(session)
                df = await collector.load_from_db(symbol, engine.timeframe, from_date=from_date)

                if df.empty or len(df) < 500:
                    logger.warning(f"ML retrain [{symbol}] skipped: insufficient data ({len(df)} bars)")
                    return

                # Load macro data for feature enrichment
                macro_df = None
                try:
                    from app.data.macro import MacroDataService
                    macro_service = MacroDataService(session)
                    macro_df = await macro_service.get_macro_df_for_ml(from_date=from_date)
                except Exception as e:
                    logger.warning(f"ML retrain [{symbol}]: macro data unavailable ({e}), proceeding without")

                # Load sentiment data for feature enrichment
                sentiment_df = None
                try:
                    from app.ml.sentiment_features import get_sentiment_df_for_ml
                    sentiment_df = await get_sentiment_df_for_ml(session, from_date=from_date)
                except Exception as e:
                    logger.debug(f"ML retrain [{symbol}]: sentiment data unavailable ({e})")

                from app.ml.trainer import ModelTrainer
                trainer = ModelTrainer()
                X, y = trainer.prepare_dataset(df, macro_df=macro_df, sentiment_df=sentiment_df)
                if len(X) < 200:
                    logger.warning(f"ML retrain [{symbol}] skipped: insufficient labeled samples ({len(X)})")
                    return

                # 14-day holdout validation split (~85/15)
                split_idx = int(len(X) * 0.85)
                X_train, X_val = X.iloc[:split_idx], X.iloc[split_idx:]
                y_train, y_val = y.iloc[:split_idx], y.iloc[split_idx:]

                # Train on training portion using walk-forward
                loop = asyncio.get_event_loop()
                new_result = await loop.run_in_executor(None, trainer.train_walk_forward, X_train, y_train)

                # Evaluate on holdout validation set
                if len(X_val) > 20 and trainer.model is not None:
                    available = [c for c in trainer.feature_columns if c in X_val.columns]
                    val_preds = trainer.model.predict(X_val[available])
                    import numpy as np
                    val_pred_classes = np.array([p.argmax() for p in val_preds])
                    signal_map = {0: -1, 1: 0, 2: 1}
                    val_pred_signals = np.array([signal_map[c] for c in val_pred_classes])
                    new_accuracy = float((val_pred_signals == y_val.values).mean())
                else:
                    new_accuracy = new_result.accuracy

                logger.info(f"ML retrain [{symbol}]: new_val={new_accuracy:.4f}, current={current_accuracy:.4f}")

                # Require 5% relative improvement
                if new_accuracy < current_accuracy * 1.05:
                    logger.info(f"ML retrain [{symbol}]: new model not better — keeping existing")
                    msg = (f"ML Retrain [{symbol}]: {new_accuracy:.1%} did NOT beat "
                           f"{current_accuracy:.1%} — keeping existing")
                else:
                    trainer.save_model(model_path)

                    buf = io.BytesIO()
                    joblib.dump({"model": trainer.model, "features": trainer.feature_columns}, buf)
                    model_bytes = buf.getvalue()

                    # Deactivate old model for this symbol
                    await session.execute(
                        update(MLModelLog)
                        .where(MLModelLog.is_active == True, MLModelLog.model_name == model_name)
                        .values(is_active=False)
                    )
                    log = MLModelLog(
                        model_name=model_name,
                        timeframe=engine.timeframe,
                        train_start=df.index[0].to_pydatetime(),
                        train_end=df.index[int(len(df) * 0.8)].to_pydatetime(),
                        test_start=df.index[int(len(df) * 0.8)].to_pydatetime(),
                        test_end=df.index[-1].to_pydatetime(),
                        metrics=json.dumps(new_result.report),
                        feature_importance=json.dumps(new_result.feature_importance),
                        model_path=model_path,
                        model_binary=model_bytes,
                        is_active=True,
                    )
                    session.add(log)
                    await session.commit()

                    # Reload model in strategy
                    if hasattr(engine, 'strategy') and hasattr(engine.strategy, '_model_loaded'):
                        engine.strategy._model_loaded = False
                        await engine.strategy._ensure_model()

                    msg = (f"ML Retrain [{symbol}]: accuracy {current_accuracy:.1%} → "
                           f"{new_accuracy:.1%} — deployed!")
                    logger.info(msg)

                if hasattr(engine, 'notifier') and engine.notifier:
                    try:
                        await engine.notifier.send_message(msg)
                    except Exception:
                        pass

        except Exception as e:
            logger.error(f"ML retrain [{symbol}] error: {e}")
