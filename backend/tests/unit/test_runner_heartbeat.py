"""
Unit tests for runner/heartbeat.py — RunnerHeartbeatMonitor.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.db.models import RunnerStatus
from app.runner.heartbeat import RunnerHeartbeatMonitor


def _make_runner(id: int, name: str, status: RunnerStatus):
    r = MagicMock()
    r.id = id
    r.name = name
    r.status = status
    return r


class TestCheckAll:
    @pytest.mark.asyncio
    async def test_only_checks_online_and_degraded(self):
        manager = AsyncMock()
        runners = [
            _make_runner(1, "online-r", RunnerStatus.ONLINE),
            _make_runner(2, "stopped-r", RunnerStatus.STOPPED),
            _make_runner(3, "degraded-r", RunnerStatus.DEGRADED),
            _make_runner(4, "error-r", RunnerStatus.ERROR),
        ]
        manager.list_all.return_value = runners
        manager.backend.is_alive = AsyncMock(return_value=True)

        monitor = RunnerHeartbeatMonitor(manager, max_misses=3)
        await monitor.check_all()

        # is_alive should be called for runners 1 and 3 only
        assert manager.backend.is_alive.call_count == 2
        called_ids = [call.args[0] for call in manager.backend.is_alive.call_args_list]
        assert set(called_ids) == {1, 3}

    @pytest.mark.asyncio
    async def test_check_all_handles_manager_error(self):
        manager = AsyncMock()
        manager.list_all.side_effect = Exception("db error")
        monitor = RunnerHeartbeatMonitor(manager)
        # Should not raise
        await monitor.check_all()


class TestCheckRunnerAlive:
    @pytest.mark.asyncio
    async def test_alive_records_heartbeat(self):
        manager = AsyncMock()
        manager.backend.is_alive = AsyncMock(return_value=True)
        monitor = RunnerHeartbeatMonitor(manager, max_misses=3)

        runner = _make_runner(1, "r1", RunnerStatus.ONLINE)
        await monitor._check_runner(runner)

        manager.record_heartbeat.assert_awaited_once_with(1)
        assert monitor._miss_counts.get(1) == 0

    @pytest.mark.asyncio
    async def test_alive_recovers_from_degraded(self):
        manager = AsyncMock()
        manager.backend.is_alive = AsyncMock(return_value=True)
        monitor = RunnerHeartbeatMonitor(manager, max_misses=3)

        runner = _make_runner(1, "r1", RunnerStatus.DEGRADED)
        await monitor._check_runner(runner)

        # Status should be set to ONLINE
        assert runner.status == RunnerStatus.ONLINE
        manager.db.commit.assert_awaited()
        manager._log.assert_awaited()


class TestCheckRunnerNotAlive:
    @pytest.mark.asyncio
    async def test_first_miss_marks_degraded(self):
        manager = AsyncMock()
        manager.backend.is_alive = AsyncMock(return_value=False)
        monitor = RunnerHeartbeatMonitor(manager, max_misses=3)

        runner = _make_runner(1, "r1", RunnerStatus.ONLINE)
        await monitor._check_runner(runner)

        assert monitor._miss_counts[1] == 1
        manager.mark_degraded.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_second_miss_increments_only(self):
        manager = AsyncMock()
        manager.backend.is_alive = AsyncMock(return_value=False)
        monitor = RunnerHeartbeatMonitor(manager, max_misses=3)
        monitor._miss_counts[1] = 1  # already had one miss

        runner = _make_runner(1, "r1", RunnerStatus.DEGRADED)
        await monitor._check_runner(runner)

        assert monitor._miss_counts[1] == 2
        # mark_degraded not called because status is already DEGRADED
        manager.mark_degraded.assert_not_awaited()
        manager.restart.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_max_misses_triggers_restart(self):
        manager = AsyncMock()
        manager.backend.is_alive = AsyncMock(return_value=False)
        monitor = RunnerHeartbeatMonitor(manager, max_misses=3)
        monitor._miss_counts[1] = 2  # will be 3 = max

        runner = _make_runner(1, "r1", RunnerStatus.DEGRADED)
        await monitor._check_runner(runner)

        assert monitor._miss_counts[1] == 0  # reset after restart
        manager.restart.assert_awaited_once_with(1)

    @pytest.mark.asyncio
    async def test_restart_failure_marks_degraded(self):
        manager = AsyncMock()
        manager.backend.is_alive = AsyncMock(return_value=False)
        manager.restart.side_effect = Exception("restart failed")
        monitor = RunnerHeartbeatMonitor(manager, max_misses=3)
        monitor._miss_counts[1] = 2

        runner = _make_runner(1, "r1", RunnerStatus.DEGRADED)
        await monitor._check_runner(runner)

        manager.mark_degraded.assert_awaited()
        # miss count stays at 3 because restart failed
        assert monitor._miss_counts[1] == 3


class TestReset:
    def test_reset_clears_miss_count(self):
        monitor = RunnerHeartbeatMonitor(manager=AsyncMock(), max_misses=3)
        monitor._miss_counts[1] = 5
        monitor.reset(1)
        assert 1 not in monitor._miss_counts

    def test_reset_nonexistent_runner_is_noop(self):
        monitor = RunnerHeartbeatMonitor(manager=AsyncMock(), max_misses=3)
        monitor.reset(999)  # should not raise
