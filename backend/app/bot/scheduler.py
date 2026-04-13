"""
Scheduler — APScheduler jobs for bot operations (multi-symbol).
"""

import asyncio
from collections import defaultdict
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from loguru import logger

from app.bot.engine import BotEngine

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

        self.scheduler.start()
        logger.info("Scheduler started")

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
        # AI Agent is the primary decision-maker (no rule-based strategies)
        await self._run_ai_agent(symbols)

    async def _sentiment_job(self):
        """Fetch news sentiment regardless of bot state — news comes out 24/7.

        Runs every 15 min on weekdays, but skips 3 out of 4 runs on weekends
        (effectively hourly) to save API cost.
        """
        now = datetime.utcnow()
        is_weekend = now.weekday() >= 5  # Saturday=5, Sunday=6
        if is_weekend and now.minute not in (2,):
            # On weekends, only run at :02 past each hour (skip :17, :32, :47)
            logger.debug("Sentiment job skipped (weekend, hourly mode)")
            return

        logger.debug("Sentiment job triggered")
        tasks = [e.fetch_and_analyze_sentiment() for e in self._engines.values()]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _run_ai_agent(self, symbols: list[str]):
        """Run AI agent for each symbol — the primary trading decision-maker."""
        try:
            from mcp_server.agent_config import run_agent
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

        for sym in symbols:
            engine = self._engines.get(sym)
            if not engine or engine.state.value != "RUNNING":
                continue
            try:
                result = await run_agent(
                    job_type="candle_analysis",
                    job_input={"symbol": sym, "timeframe": engine.timeframe},
                )
                decision = result.get("decision", "HOLD")
                logger.info(f"AI agent [{sym}]: {decision[:200]}")

                # Store last AI decision for dashboard display
                engine._last_ai_decision = {
                    "decision": decision[:3000],
                    "strategy": result.get("strategy_used", "ai_autonomous"),
                    "turns": result.get("turns", 0),
                    "tool_calls": len(result.get("tool_calls", [])),
                    "duration_s": result.get("duration_s", 0),
                }

                # Publish to WebSocket for real-time dashboard update
                await engine._push_event("bot_event", {
                    "type": "AI_DECISION",
                    "symbol": sym,
                    "decision": decision[:3000],
                    "strategy": result.get("strategy_used", "ai_autonomous"),
                    "turns": result.get("turns", 0),
                })
            except Exception as e:
                logger.warning(f"AI agent [{sym}] error: {e}")

    async def _sync_job(self):
        tasks = [e.sync_positions() for e in self._engines.values() if e.state.value == "RUNNING"]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _weekly_optimize_job(self):
        logger.info("Weekly optimization triggered")
        # Run optimization on first engine that has an optimizer
        for engine in self._engines.values():
            if not engine._optimizer:
                continue
            try:
                result = await engine._optimizer.optimize(engine.strategy.get_params())
                if result:
                    logger.info(f"Optimization result [{engine.symbol}]: {result.assessment} (confidence={result.confidence})")
                    await engine._notify(engine.notifier.send_optimization_report(
                        result.assessment, result.confidence,
                    ))
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

    async def _daily_reset_job(self):
        logger.info("Daily reset triggered")
        tasks = [e.circuit_breaker.reset() for e in self._engines.values()]
        await asyncio.gather(*tasks, return_exceptions=True)

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

            from app.config import settings
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
