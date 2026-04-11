"""
Scheduler — APScheduler jobs for bot operations (multi-symbol).
"""

import asyncio
from collections import defaultdict

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

        # Weekly ML retrain: Sunday 01:00 UTC
        self.scheduler.add_job(
            self._ml_retrain_job,
            "cron",
            day_of_week="sun",
            hour=1,
            minute=0,
            id="ml_retrain",
            max_instances=1,
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
        tasks = []
        for symbol, engine in self._engines.items():
            if engine.state.value == "RUNNING":
                tasks.append(self._fetch_tick(symbol, engine))
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
        tasks = []
        for sym in symbols:
            engine = self._engines.get(sym)
            if engine:
                tasks.append(engine.process_candle())
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _sentiment_job(self):
        logger.debug("Sentiment job triggered")
        tasks = [e.fetch_and_analyze_sentiment() for e in self._engines.values() if e.state.value == "RUNNING"]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

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

    async def _ml_retrain_symbol(self, symbol: str, engine):
        """Train ML model for a single symbol."""
        try:
            import asyncio
            import io
            import json
            from datetime import datetime, timedelta

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

                # Load last 6 months of data
                from_date = (datetime.utcnow() - timedelta(days=180)).strftime("%Y-%m-%d")
                collector = DataCollector(session)
                df = await collector.load_from_db(symbol, engine.timeframe, from_date=from_date)

                if df.empty or len(df) < 500:
                    logger.warning(f"ML retrain [{symbol}] skipped: insufficient data ({len(df)} bars)")
                    return

                from app.ml.trainer import ModelTrainer
                trainer = ModelTrainer()
                X, y = trainer.prepare_dataset(df)
                if len(X) < 200:
                    logger.warning(f"ML retrain [{symbol}] skipped: insufficient labeled samples ({len(X)})")
                    return

                # Train in executor to avoid blocking
                loop = asyncio.get_event_loop()
                new_result = await loop.run_in_executor(None, trainer.train_walk_forward, X, y)

                new_accuracy = new_result.accuracy
                logger.info(f"ML retrain [{symbol}]: new={new_accuracy:.4f}, current={current_accuracy:.4f}")

                if new_accuracy <= current_accuracy:
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
