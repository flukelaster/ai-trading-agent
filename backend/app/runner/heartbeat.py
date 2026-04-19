"""
Heartbeat monitor for runners — checks liveness and triggers recovery.

Integrated with APScheduler (same pattern as BotScheduler).
"""

from datetime import datetime

from loguru import logger

from app.db.models import Runner, RunnerStatus


class RunnerHeartbeatMonitor:
    """Monitors runner health and triggers recovery actions."""

    def __init__(
        self,
        manager,  # RunnerManager — forward ref to avoid circular import
        interval_seconds: int = 30,
        max_misses: int = 3,
    ):
        self.manager = manager
        self.interval_seconds = interval_seconds
        self.max_misses = max_misses
        self._miss_counts: dict[int, int] = {}

    async def check_all(self) -> None:
        """Check heartbeat for all online/degraded runners."""
        try:
            runners = await self.manager.list_all()
            for runner in runners:
                if runner.status in (RunnerStatus.ONLINE, RunnerStatus.DEGRADED):
                    await self._check_runner(runner)
        except Exception as e:
            logger.error(f"Heartbeat check error: {e}")

    async def _check_runner(self, runner: Runner) -> None:
        """Check a single runner's heartbeat."""
        is_alive = await self.manager.backend.is_alive(runner.id)

        if is_alive:
            # Runner is responding
            await self.manager.record_heartbeat(runner.id)
            self._miss_counts[runner.id] = 0

            # Recover from degraded
            if runner.status == RunnerStatus.DEGRADED:
                runner.status = RunnerStatus.ONLINE
                runner.updated_at = datetime.utcnow()
                await self.manager.db.commit()
                await self.manager._log(runner.id, "info", "Runner recovered from degraded state")
                logger.info(f"Runner {runner.name} recovered")
        else:
            # Runner not responding
            misses = self._miss_counts.get(runner.id, 0) + 1
            self._miss_counts[runner.id] = misses

            if misses >= self.max_misses:
                # Too many misses — try auto-restart
                logger.warning(f"Runner {runner.name}: {misses} consecutive heartbeat misses, attempting restart")
                await self.manager._log(
                    runner.id,
                    "error",
                    f"Heartbeat timeout ({misses} misses), auto-restarting",
                )
                try:
                    await self.manager.restart(runner.id)
                    self._miss_counts[runner.id] = 0
                except Exception as e:
                    logger.error(f"Auto-restart failed for runner {runner.name}: {e}")
                    await self.manager.mark_degraded(runner.id, f"Auto-restart failed: {e}")

            elif misses == 1 and runner.status == RunnerStatus.ONLINE:
                # First miss — mark degraded
                await self.manager.mark_degraded(runner.id, f"Heartbeat miss ({misses}/{self.max_misses})")

    def reset(self, runner_id: int) -> None:
        """Reset miss count for a runner (e.g., after manual restart)."""
        self._miss_counts.pop(runner_id, None)
