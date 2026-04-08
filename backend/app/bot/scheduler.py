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

        # Daily reset: midnight UTC
        self.scheduler.add_job(
            self._daily_reset_job,
            "cron",
            hour=0,
            minute=0,
            id="daily_reset",
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

    async def _daily_reset_job(self):
        logger.info("Daily reset triggered")
        await self.bot.circuit_breaker.reset()
