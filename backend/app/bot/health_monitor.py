"""
Health Monitor — periodic heartbeat check for MT5 Bridge connectivity.
Auto-pauses trading on prolonged outage, auto-recovers when connectivity returns.
"""

from loguru import logger

from app.bot.engine import BotState
from app.db.models import BotEventType


class HealthMonitor:
    def __init__(self, connector, manager, notifier=None):
        self._connector = connector
        self._manager = manager
        self._notifier = notifier
        self._consecutive_failures: int = 0
        self._max_failures: int = 3  # pause after 3 consecutive failures (~90s at 30s interval)
        self._is_degraded: bool = False

    async def check(self) -> dict:
        """Run health check against MT5 Bridge. Returns status dict."""
        try:
            result = await self._connector.get_health()
            # Bridge returns {"status": "ok", "mt5": {...}} on success
            # Connector returns {"success": False, "error": "..."} on HTTP/network error
            if result.get("status") == "ok" or result.get("success"):
                return await self._on_success()
            else:
                return await self._on_failure(
                    f"Bridge returned error: {result.get('error', result.get('status', 'unknown'))}"
                )
        except Exception as e:
            return await self._on_failure(str(e))

    async def _on_success(self) -> dict:
        """Handle successful health check."""
        was_degraded = self._is_degraded
        self._consecutive_failures = 0

        if was_degraded:
            self._is_degraded = False
            logger.info("MT5 Bridge connectivity restored — resuming trading")

            # Resume all paused engines
            for _symbol, engine in self._manager.engines.items():
                if engine.state == BotState.PAUSED:
                    engine.state = BotState.RUNNING
                    await engine._log_event(BotEventType.STARTED, "Auto-resumed: MT5 Bridge connectivity restored")

            if self._notifier:
                try:
                    await self._notifier.send_health_alert(
                        "recovered", "MT5 Bridge connectivity restored — trading resumed"
                    )
                except Exception:
                    pass

        return {"status": "healthy", "consecutive_failures": 0, "degraded": False}

    async def _on_failure(self, error: str) -> dict:
        """Handle failed health check."""
        self._consecutive_failures += 1
        logger.warning(f"MT5 Bridge health check failed ({self._consecutive_failures}/{self._max_failures}): {error}")

        if self._consecutive_failures >= self._max_failures and not self._is_degraded:
            self._is_degraded = True
            logger.error(f"MT5 Bridge unreachable for {self._consecutive_failures} checks — pausing all trading")

            # Pause all running engines
            for _symbol, engine in self._manager.engines.items():
                if engine.state == BotState.RUNNING:
                    engine.state = BotState.PAUSED
                    await engine._log_event(
                        BotEventType.ERROR,
                        f"MT5 Bridge unreachable ({self._consecutive_failures} consecutive failures) — trading paused",
                    )

            if self._notifier:
                try:
                    await self._notifier.send_health_alert(
                        "degraded",
                        f"MT5 Bridge unreachable for {self._consecutive_failures} checks — new trades paused",
                    )
                except Exception:
                    pass

        return {
            "status": "unhealthy",
            "consecutive_failures": self._consecutive_failures,
            "degraded": self._is_degraded,
            "error": error,
        }

    @property
    def is_degraded(self) -> bool:
        return self._is_degraded
