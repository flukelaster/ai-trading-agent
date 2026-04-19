"""
Unit tests for runner/job_queue.py — JobQueue.

Uses real SQLite DB session + fakeredis for dual-storage testing.
"""

import pytest

from app.db.models import JobStatus, Runner, RunnerStatus
from app.runner.job_queue import PENDING_QUEUE_KEY, RUNNING_SET_KEY, JobQueue


@pytest.fixture
def queue(db_session, redis_client):
    return JobQueue(db=db_session, redis=redis_client)


async def _create_runner(db_session, name="test-runner", status=RunnerStatus.ONLINE, max_jobs=3):
    runner = Runner(
        name=name,
        image="agent:latest",
        status=status,
        max_concurrent_jobs=max_jobs,
    )
    db_session.add(runner)
    await db_session.commit()
    await db_session.refresh(runner)
    return runner


class TestEnqueue:
    @pytest.mark.asyncio
    async def test_enqueue_creates_job_in_db(self, queue, db_session):
        job = await queue.enqueue("candle_analysis", input_data={"symbol": "GOLD"})
        assert job.id is not None
        assert job.job_type == "candle_analysis"
        assert job.status == JobStatus.PENDING
        assert job.input == {"symbol": "GOLD"}

    @pytest.mark.asyncio
    async def test_enqueue_pushes_to_redis(self, queue, redis_client):
        await queue.enqueue("candle_analysis")
        count = await redis_client.llen(PENDING_QUEUE_KEY)
        assert count == 1

    @pytest.mark.asyncio
    async def test_enqueue_with_runner_id(self, queue, db_session):
        runner = await _create_runner(db_session)
        job = await queue.enqueue("manual_trade", runner_id=runner.id)
        assert job.runner_id == runner.id


class TestDispatch:
    @pytest.mark.asyncio
    async def test_dispatch_assigns_to_available_runner(self, queue, db_session):
        runner = await _create_runner(db_session)
        await queue.enqueue("candle_analysis")

        dispatched = await queue.dispatch()
        assert dispatched is not None
        assert dispatched.status == JobStatus.RUNNING
        assert dispatched.runner_id == runner.id
        assert dispatched.started_at is not None

    @pytest.mark.asyncio
    async def test_dispatch_tracks_in_running_set(self, queue, db_session, redis_client):
        await _create_runner(db_session)
        await queue.enqueue("candle_analysis")

        await queue.dispatch()
        count = await redis_client.scard(RUNNING_SET_KEY)
        assert count == 1

    @pytest.mark.asyncio
    async def test_dispatch_returns_none_when_empty(self, queue):
        result = await queue.dispatch()
        assert result is None

    @pytest.mark.asyncio
    async def test_dispatch_requeues_when_no_runner_available(self, queue, redis_client):
        # No online runners exist
        await queue.enqueue("candle_analysis")
        result = await queue.dispatch()
        assert result is None
        # Job should be re-queued
        count = await redis_client.llen(PENDING_QUEUE_KEY)
        assert count == 1

    @pytest.mark.asyncio
    async def test_dispatch_respects_max_concurrent_jobs(self, queue, db_session):
        runner = await _create_runner(db_session, max_jobs=1)
        # Enqueue 2 jobs
        await queue.enqueue("job1")
        await queue.enqueue("job2")

        # First dispatch should succeed
        job1 = await queue.dispatch()
        assert job1 is not None
        assert job1.runner_id == runner.id

        # Second dispatch should fail — runner at capacity
        job2 = await queue.dispatch()
        assert job2 is None

    @pytest.mark.asyncio
    async def test_dispatch_with_preferred_runner(self, queue, db_session):
        await _create_runner(db_session, name="r1")
        runner2 = await _create_runner(db_session, name="r2")
        await queue.enqueue("task", runner_id=runner2.id)

        dispatched = await queue.dispatch()
        assert dispatched is not None
        assert dispatched.runner_id == runner2.id


class TestComplete:
    @pytest.mark.asyncio
    async def test_complete_updates_status(self, queue, db_session, redis_client):
        await _create_runner(db_session)
        await queue.enqueue("task")
        job = await queue.dispatch()

        completed = await queue.complete(job.id, output={"result": "no trade"})
        assert completed.status == JobStatus.COMPLETED
        assert completed.output == {"result": "no trade"}
        assert completed.completed_at is not None
        assert completed.duration_ms is not None

    @pytest.mark.asyncio
    async def test_complete_removes_from_running_set(self, queue, db_session, redis_client):
        await _create_runner(db_session)
        await queue.enqueue("task")
        job = await queue.dispatch()

        await queue.complete(job.id)
        count = await redis_client.scard(RUNNING_SET_KEY)
        assert count == 0

    @pytest.mark.asyncio
    async def test_complete_nonexistent_raises(self, queue):
        with pytest.raises(ValueError, match="not found"):
            await queue.complete(9999)


class TestFail:
    @pytest.mark.asyncio
    async def test_fail_updates_status(self, queue, db_session, redis_client):
        await _create_runner(db_session)
        await queue.enqueue("task")
        job = await queue.dispatch()

        failed = await queue.fail(job.id, "Token expired")
        assert failed.status == JobStatus.FAILED
        assert failed.error == "Token expired"
        assert failed.completed_at is not None

    @pytest.mark.asyncio
    async def test_fail_nonexistent_raises(self, queue):
        with pytest.raises(ValueError, match="not found"):
            await queue.fail(9999, "error")


class TestCancel:
    @pytest.mark.asyncio
    async def test_cancel_pending_job(self, queue, db_session):
        job = await queue.enqueue("task")
        cancelled = await queue.cancel(job.id)
        assert cancelled.status == JobStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_cancel_running_job(self, queue, db_session):
        await _create_runner(db_session)
        await queue.enqueue("task")
        job = await queue.dispatch()

        cancelled = await queue.cancel(job.id)
        assert cancelled.status == JobStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_cancel_completed_job_raises(self, queue, db_session):
        await _create_runner(db_session)
        await queue.enqueue("task")
        job = await queue.dispatch()
        await queue.complete(job.id)

        with pytest.raises(ValueError, match="Cannot cancel"):
            await queue.cancel(job.id)

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_raises(self, queue):
        with pytest.raises(ValueError, match="not found"):
            await queue.cancel(9999)


class TestRetry:
    @pytest.mark.asyncio
    async def test_retry_failed_job_creates_new(self, queue, db_session, redis_client):
        await _create_runner(db_session)
        await queue.enqueue("candle_analysis", input_data={"symbol": "GOLD"})
        job = await queue.dispatch()
        await queue.fail(job.id, "error")

        new_job = await queue.retry(job.id)
        assert new_job.id != job.id
        assert new_job.job_type == "candle_analysis"
        assert new_job.input == {"symbol": "GOLD"}
        assert new_job.status == JobStatus.PENDING

    @pytest.mark.asyncio
    async def test_retry_non_failed_job_raises(self, queue, db_session):
        job = await queue.enqueue("task")
        with pytest.raises(ValueError, match="Can only retry failed"):
            await queue.retry(job.id)


class TestListAndGet:
    @pytest.mark.asyncio
    async def test_get_job(self, queue, db_session):
        job = await queue.enqueue("task")
        fetched = await queue.get(job.id)
        assert fetched is not None
        assert fetched.id == job.id

    @pytest.mark.asyncio
    async def test_get_nonexistent(self, queue):
        assert await queue.get(9999) is None

    @pytest.mark.asyncio
    async def test_list_all_jobs(self, queue, db_session):
        await queue.enqueue("job1")
        await queue.enqueue("job2")
        await queue.enqueue("job3")

        jobs = await queue.list_jobs()
        assert len(jobs) == 3

    @pytest.mark.asyncio
    async def test_list_filter_by_status(self, queue, db_session):
        await _create_runner(db_session)
        await queue.enqueue("task1")
        await queue.enqueue("task2")
        await queue.dispatch()

        pending_jobs = await queue.list_jobs(status=JobStatus.PENDING)
        assert len(pending_jobs) == 1
        running_jobs = await queue.list_jobs(status=JobStatus.RUNNING)
        assert len(running_jobs) == 1

    @pytest.mark.asyncio
    async def test_list_filter_by_job_type(self, queue, db_session):
        await queue.enqueue("candle_analysis")
        await queue.enqueue("manual_trade")
        await queue.enqueue("candle_analysis")

        candle_jobs = await queue.list_jobs(job_type="candle_analysis")
        assert len(candle_jobs) == 2

    @pytest.mark.asyncio
    async def test_list_with_limit_and_offset(self, queue, db_session):
        for i in range(5):
            await queue.enqueue(f"task_{i}")

        jobs = await queue.list_jobs(limit=2, offset=1)
        assert len(jobs) == 2


class TestRebuildFromDb:
    @pytest.mark.asyncio
    async def test_rebuild_requeues_pending(self, queue, db_session, redis_client):
        await queue.enqueue("task1")
        await queue.enqueue("task2")

        # Clear Redis (simulate server restart)
        await redis_client.delete(PENDING_QUEUE_KEY)
        assert await redis_client.llen(PENDING_QUEUE_KEY) == 0

        count = await queue.rebuild_from_db()
        assert count == 2
        assert await redis_client.llen(PENDING_QUEUE_KEY) == 2

    @pytest.mark.asyncio
    async def test_rebuild_marks_stale_running_as_failed(self, queue, db_session, redis_client):
        await _create_runner(db_session)
        await queue.enqueue("task")
        job = await queue.dispatch()
        assert job.status == JobStatus.RUNNING

        # Simulate restart
        await queue.rebuild_from_db()

        # Refresh the job
        refreshed = await queue.get(job.id)
        assert refreshed.status == JobStatus.FAILED
        assert "server restart" in refreshed.error


class TestCounts:
    @pytest.mark.asyncio
    async def test_pending_count(self, queue, db_session, redis_client):
        await queue.enqueue("t1")
        await queue.enqueue("t2")
        assert await queue.pending_count() == 2

    @pytest.mark.asyncio
    async def test_running_count(self, queue, db_session, redis_client):
        await _create_runner(db_session)
        await queue.enqueue("t1")
        await queue.dispatch()
        assert await queue.running_count() == 1
