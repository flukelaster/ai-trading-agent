"""
Scheduler — APScheduler jobs for bot operations.
"""

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
    def __init__(self, bot: BotEngine):
        self.bot = bot
        self.scheduler = AsyncIOScheduler()
        self._current_tf = bot.timeframe

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

        # Run strategy on candle close — schedule based on timeframe
        cron_kwargs = self._get_cron_kwargs(self.bot.timeframe)
        self.scheduler.add_job(
            self._candle_job,
            "cron",
            **cron_kwargs,
            id="bot_candle",
            max_instances=1,
            coalesce=True,
        )
        logger.info(f"Candle job scheduled for {self.bot.timeframe}: {cron_kwargs}")

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

    def reschedule_candle(self, timeframe: str):
        """Reschedule the candle job when timeframe changes."""
        if timeframe == self._current_tf:
            return
        cron_kwargs = self._get_cron_kwargs(timeframe)
        self.scheduler.remove_job("bot_candle")
        self.scheduler.add_job(
            self._candle_job,
            "cron",
            **cron_kwargs,
            id="bot_candle",
            max_instances=1,
            coalesce=True,
        )
        self._current_tf = timeframe
        logger.info(f"Candle job rescheduled for {timeframe}: {cron_kwargs}")

    def stop(self):
        self.scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")

    async def _tick_job(self):
        if self.bot.state.value != "RUNNING":
            return
        try:
            tick = await self.bot.market_data.get_current_tick(self.bot.symbol)
            if tick:
                await self.bot._push_event("price_update", tick)
        except Exception as e:
            logger.error(f"Tick job error: {e}")

    async def _candle_job(self):
        logger.debug("Candle job triggered")
        await self.bot.process_candle()

    async def _sentiment_job(self):
        logger.debug("Sentiment job triggered")
        await self.bot.fetch_and_analyze_sentiment()

    async def _sync_job(self):
        await self.bot.sync_positions()

    async def _weekly_optimize_job(self):
        logger.info("Weekly optimization triggered")
        if not self.bot._optimizer:
            logger.warning("Optimizer not configured, skipping")
            return
        try:
            result = await self.bot._optimizer.optimize(self.bot.strategy.get_params())
            if result:
                logger.info(f"Optimization result: {result.assessment} (confidence={result.confidence})")
                await self.bot._notify(self.bot.notifier.send_optimization_report(
                    result.assessment, result.confidence,
                ))
            else:
                logger.warning("Optimization returned no result")
        except Exception as e:
            logger.error(f"Weekly optimization error: {e}")

    async def _macro_collect_job(self):
        logger.info("Daily macro collection triggered")
        if not hasattr(self.bot, '_macro_service') or not self.bot._macro_service:
            return
        try:
            stats = await self.bot._macro_service.collect_all()
            logger.info(f"Macro data collected: {stats}")
        except Exception as e:
            logger.error(f"Macro collection error: {e}")

    async def _daily_reset_job(self):
        logger.info("Daily reset triggered")
        await self.bot.circuit_breaker.reset()

    async def _ml_retrain_job(self):
        """Weekly ML retrain — trains on last 6 months of data, replaces model only if accuracy improves."""
        logger.info("Weekly ML retrain triggered")
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
            from app.ml.trainer import ModelTrainer

            async with async_session() as session:
                # Get current model accuracy for comparison
                result = await session.execute(
                    select(MLModelLog).where(MLModelLog.is_active == True).limit(1)
                )
                current_log = result.scalar_one_or_none()
                current_accuracy = 0.0
                if current_log and current_log.metrics:
                    metrics = json.loads(current_log.metrics)
                    current_accuracy = metrics.get("accuracy", 0.0)

                # Load last 6 months of data
                from_date = (datetime.utcnow() - timedelta(days=180)).strftime("%Y-%m-%d")
                collector = DataCollector(session)
                df = await collector.load_from_db(settings.symbol, settings.timeframe, from_date=from_date)

                if df.empty or len(df) < 500:
                    logger.warning(f"ML retrain skipped: insufficient data ({len(df)} bars)")
                    return

                trainer = ModelTrainer()
                X, y = trainer.prepare_dataset(df)
                if len(X) < 200:
                    logger.warning(f"ML retrain skipped: insufficient labeled samples ({len(X)})")
                    return

                # Train in executor to avoid blocking
                loop = asyncio.get_event_loop()
                new_result = await loop.run_in_executor(None, trainer.train_walk_forward, X, y)

                new_accuracy = new_result.accuracy
                logger.info(f"ML retrain complete: new_accuracy={new_accuracy:.4f}, current_accuracy={current_accuracy:.4f}")

                # Only replace if new model is better
                if new_accuracy <= current_accuracy:
                    logger.info("New model not better than current — keeping existing model")
                    msg = (f"ML Retrain (weekly): new accuracy {new_accuracy:.1%} did NOT beat "
                           f"current {current_accuracy:.1%} — keeping existing model")
                else:
                    # Save to file and DB
                    trainer.save_model(settings.ml_model_path)

                    buf = io.BytesIO()
                    joblib.dump({"model": trainer.model, "features": trainer.feature_columns}, buf)
                    model_bytes = buf.getvalue()

                    await session.execute(
                        update(MLModelLog).where(MLModelLog.is_active == True).values(is_active=False)
                    )
                    log = MLModelLog(
                        model_name="lightgbm_xauusd_auto",
                        timeframe=settings.timeframe,
                        train_start=df.index[0].to_pydatetime(),
                        train_end=df.index[int(len(df) * 0.8)].to_pydatetime(),
                        test_start=df.index[int(len(df) * 0.8)].to_pydatetime(),
                        test_end=df.index[-1].to_pydatetime(),
                        metrics=json.dumps(new_result.report),
                        feature_importance=json.dumps(new_result.feature_importance),
                        model_path=settings.ml_model_path,
                        model_binary=model_bytes,
                        is_active=True,
                    )
                    session.add(log)
                    await session.commit()

                    # Reload model in strategy
                    if hasattr(self.bot, 'strategy') and hasattr(self.bot.strategy, '_model_loaded'):
                        self.bot.strategy._model_loaded = False
                        await self.bot.strategy._ensure_model()

                    msg = (f"ML Retrain (weekly): accuracy improved {current_accuracy:.1%} → "
                           f"{new_accuracy:.1%} — new model deployed!")
                    logger.info(msg)

                # Send Telegram notification
                if hasattr(self.bot, 'notifier') and self.bot.notifier:
                    try:
                        await self.bot.notifier.send_message(msg)
                    except Exception:
                        pass

        except Exception as e:
            logger.error(f"ML retrain job error: {e}")
