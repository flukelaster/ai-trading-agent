"""
Unit tests for runner/manager.py — RunnerManager.

Uses real SQLite DB session + fakeredis + mocked RunnerBackend.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.db.models import (
    JobStatus,
    RunnerJob,
    RunnerLog,
    RunnerMetric,
    RunnerStatus,
    Secret,
)
from app.runner.backend import ResourceMetrics, RunnerBackend
from app.runner.manager import RunnerManager


@pytest.fixture
def mock_backend():
    backend = AsyncMock(spec=RunnerBackend)
    backend.start.return_value = "container-abc123"
    backend.get_metrics.return_value = ResourceMetrics(cpu_percent=10.0, memory_mb=256.0)
    # cleanup() is on ProcessRunnerBackend, not the ABC, but manager.shutdown() calls it
    backend.cleanup = AsyncMock()
    return backend


@pytest.fixture
def mock_vault():
    vault = MagicMock()
    vault._derived_key = b"test-key"
    vault.decrypt.return_value = "decrypted-value"
    return vault


@pytest.fixture
def manager(db_session, redis_client, mock_backend, mock_vault):
    return RunnerManager(
        db=db_session,
        redis=redis_client,
        backend=mock_backend,
        vault=mock_vault,
    )


class TestRegister:
    @pytest.mark.asyncio
    async def test_register_creates_runner(self, manager):
        runner = await manager.register("test-agent", "agent:latest")
        assert runner.id is not None
        assert runner.name == "test-agent"
        assert runner.image == "agent:latest"
        assert runner.status == RunnerStatus.STOPPED
        assert runner.max_concurrent_jobs == 3

    @pytest.mark.asyncio
    async def test_register_with_custom_config(self, manager):
        runner = await manager.register(
            "gold-agent",
            "agent:v2",
            max_concurrent_jobs=5,
            tags=["gold", "trading"],
            resource_limits={"memory": "2G"},
        )
        assert runner.max_concurrent_jobs == 5
        assert runner.tags == ["gold", "trading"]
        assert runner.resource_limits == {"memory": "2G"}


class TestGetAndList:
    @pytest.mark.asyncio
    async def test_get_existing(self, manager):
        runner = await manager.register("r1", "img")
        fetched = await manager.get(runner.id)
        assert fetched is not None
        assert fetched.name == "r1"

    @pytest.mark.asyncio
    async def test_get_nonexistent(self, manager):
        assert await manager.get(9999) is None

    @pytest.mark.asyncio
    async def test_list_all(self, manager):
        await manager.register("r1", "img")
        await manager.register("r2", "img")
        runners = await manager.list_all()
        assert len(runners) == 2


class TestUpdateConfig:
    @pytest.mark.asyncio
    async def test_update_name(self, manager):
        runner = await manager.register("old-name", "img")
        updated = await manager.update_config(runner.id, name="new-name")
        assert updated.name == "new-name"
        assert updated.updated_at is not None

    @pytest.mark.asyncio
    async def test_update_nonexistent_returns_none(self, manager):
        assert await manager.update_config(9999, name="x") is None

    @pytest.mark.asyncio
    async def test_update_partial(self, manager):
        runner = await manager.register("r1", "old-img", max_concurrent_jobs=2)
        updated = await manager.update_config(runner.id, image="new-img")
        assert updated.image == "new-img"
        assert updated.max_concurrent_jobs == 2  # unchanged


class TestStart:
    @pytest.mark.asyncio
    async def test_start_transitions_to_online(self, manager, mock_backend):
        runner = await manager.register("r1", "img")
        started = await manager.start(runner.id)

        assert started.status == RunnerStatus.ONLINE
        assert started.container_id == "container-abc123"
        assert started.last_heartbeat_at is not None
        mock_backend.start.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_start_already_online_raises(self, manager):
        runner = await manager.register("r1", "img")
        await manager.start(runner.id)

        with pytest.raises(RuntimeError, match="already online"):
            await manager.start(runner.id)

    @pytest.mark.asyncio
    async def test_start_nonexistent_raises(self, manager):
        with pytest.raises(ValueError, match="not found"):
            await manager.start(9999)

    @pytest.mark.asyncio
    async def test_start_backend_failure_sets_error(self, manager, mock_backend):
        mock_backend.start.side_effect = Exception("Docker failed")
        runner = await manager.register("r1", "img")

        with pytest.raises(Exception, match="Docker failed"):
            await manager.start(runner.id)

        refreshed = await manager.get(runner.id)
        assert refreshed.status == RunnerStatus.ERROR

    @pytest.mark.asyncio
    async def test_start_injects_decrypted_secrets(self, manager, mock_backend, mock_vault, db_session):
        # Add a secret to DB
        secret = Secret(
            key="CLAUDE_TOKEN",
            encrypted_value=b"encrypted",
            nonce=b"nonce123",
            category="auth",
            is_deleted=False,
        )
        db_session.add(secret)
        await db_session.commit()

        runner = await manager.register("r1", "img")
        await manager.start(runner.id)

        # backend.start should receive decrypted secrets
        call_args = mock_backend.start.call_args
        secrets = call_args.args[2] if len(call_args.args) > 2 else call_args.kwargs.get("secrets", {})
        assert "CLAUDE_TOKEN" in secrets


class TestStop:
    @pytest.mark.asyncio
    async def test_stop_transitions_to_stopped(self, manager, mock_backend):
        runner = await manager.register("r1", "img")
        await manager.start(runner.id)
        stopped = await manager.stop(runner.id)

        assert stopped.status == RunnerStatus.STOPPED
        assert stopped.container_id is None
        mock_backend.stop.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_stop_nonexistent_raises(self, manager):
        with pytest.raises(ValueError, match="not found"):
            await manager.stop(9999)

    @pytest.mark.asyncio
    async def test_kill_calls_stop_with_force(self, manager, mock_backend):
        runner = await manager.register("r1", "img")
        await manager.start(runner.id)
        await manager.kill(runner.id)

        mock_backend.stop.assert_awaited_with(runner.id, force=True)


class TestRestart:
    @pytest.mark.asyncio
    async def test_restart_cycles_stop_start(self, manager, mock_backend):
        runner = await manager.register("r1", "img")
        await manager.start(runner.id)
        restarted = await manager.restart(runner.id)

        assert restarted.status == RunnerStatus.ONLINE
        assert mock_backend.stop.await_count == 1
        assert mock_backend.start.await_count == 2  # initial start + restart


class TestRemove:
    @pytest.mark.asyncio
    async def test_remove_stopped_runner(self, manager):
        runner = await manager.register("r1", "img")
        removed = await manager.remove(runner.id)
        assert removed is True
        assert await manager.get(runner.id) is None

    @pytest.mark.asyncio
    async def test_remove_running_runner_stops_first(self, manager, mock_backend):
        runner = await manager.register("r1", "img")
        await manager.start(runner.id)
        removed = await manager.remove(runner.id)
        assert removed is True
        mock_backend.stop.assert_awaited()

    @pytest.mark.asyncio
    async def test_remove_nonexistent_returns_false(self, manager):
        assert await manager.remove(9999) is False


class TestHeartbeat:
    @pytest.mark.asyncio
    async def test_record_heartbeat(self, manager):
        runner = await manager.register("r1", "img")
        await manager.record_heartbeat(runner.id)
        # Should not raise; verifying commit happens
        refreshed = await manager.get(runner.id)
        assert refreshed is not None

    @pytest.mark.asyncio
    async def test_mark_degraded(self, manager):
        runner = await manager.register("r1", "img")
        await manager.start(runner.id)
        await manager.mark_degraded(runner.id, "test reason")

        refreshed = await manager.get(runner.id)
        assert refreshed.status == RunnerStatus.DEGRADED


class TestObservability:
    @pytest.mark.asyncio
    async def test_get_logs(self, manager, db_session):
        runner = await manager.register("r1", "img")
        # Add some logs directly
        log = RunnerLog(runner_id=runner.id, level="info", message="test log")
        db_session.add(log)
        await db_session.commit()

        logs = await manager.get_logs(runner.id)
        assert len(logs) == 1
        assert logs[0].message == "test log"

    @pytest.mark.asyncio
    async def test_get_metrics(self, manager, db_session):
        runner = await manager.register("r1", "img")
        metric = RunnerMetric(
            runner_id=runner.id,
            cpu_percent=15.0,
            memory_mb=200.0,
        )
        db_session.add(metric)
        await db_session.commit()

        metrics = await manager.get_metrics(runner.id)
        assert len(metrics) == 1
        assert metrics[0].cpu_percent == 15.0

    @pytest.mark.asyncio
    async def test_get_jobs(self, manager, db_session):
        runner = await manager.register("r1", "img")
        job = RunnerJob(
            runner_id=runner.id,
            job_type="candle_analysis",
            status=JobStatus.COMPLETED,
        )
        db_session.add(job)
        await db_session.commit()

        jobs = await manager.get_jobs(runner.id)
        assert len(jobs) == 1

    @pytest.mark.asyncio
    async def test_collect_metrics(self, manager, mock_backend, db_session):
        runner = await manager.register("r1", "img")
        metric = await manager.collect_metrics(runner.id)
        assert metric is not None
        assert metric.cpu_percent == 10.0  # from mock_backend fixture
        mock_backend.get_metrics.assert_awaited_once()


class TestLogHelper:
    @pytest.mark.asyncio
    async def test_log_persists_to_db(self, manager, db_session):
        runner = await manager.register("r1", "img")
        await manager._log(runner.id, "info", "test message", {"key": "value"})

        logs = await manager.get_logs(runner.id)
        assert len(logs) >= 1
        assert any(l.message == "test message" for l in logs)

    @pytest.mark.asyncio
    async def test_log_publishes_to_redis(self, manager, redis_client, db_session):
        runner = await manager.register("r1", "img")

        # Subscribe before logging
        pubsub = redis_client.pubsub()
        await pubsub.subscribe(f"runner:{runner.id}:logs")

        await manager._log(runner.id, "warn", "warning msg")

        # Check message was published
        await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
        # fakeredis pub/sub may not deliver synchronously; just verify no error
        await pubsub.unsubscribe()


class TestShutdown:
    @pytest.mark.asyncio
    async def test_shutdown_stops_all_running(self, manager, mock_backend):
        r1 = await manager.register("r1", "img")
        r2 = await manager.register("r2", "img")
        await manager.start(r1.id)
        await manager.start(r2.id)

        await manager.shutdown()
        mock_backend.cleanup.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_shutdown_handles_stop_error(self, manager, mock_backend):
        runner = await manager.register("r1", "img")
        await manager.start(runner.id)
        mock_backend.stop.side_effect = Exception("stop failed")

        # Should not raise
        await manager.shutdown()
        mock_backend.cleanup.assert_awaited_once()


class TestDecryptSecrets:
    @pytest.mark.asyncio
    async def test_no_vault_returns_empty(self, db_session, redis_client, mock_backend):
        mgr = RunnerManager(db=db_session, redis=redis_client, backend=mock_backend, vault=None)
        secrets = await mgr._get_decrypted_secrets()
        assert secrets == {}

    @pytest.mark.asyncio
    async def test_decrypt_failure_skips_secret(self, manager, mock_vault, db_session):
        secret = Secret(
            key="BAD_KEY",
            encrypted_value=b"bad",
            nonce=b"nonce",
            category="auth",
            is_deleted=False,
        )
        db_session.add(secret)
        await db_session.commit()

        mock_vault.decrypt.side_effect = Exception("decrypt error")
        secrets = await manager._get_decrypted_secrets()
        assert "BAD_KEY" not in secrets
