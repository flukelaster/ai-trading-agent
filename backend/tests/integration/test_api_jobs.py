"""
Integration tests for Job Management API routes.
"""

from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.db.models import RunnerStatus, JobStatus, Runner
from app.db.session import get_db
from app.runner.backend import RunnerBackend, ResourceMetrics
from app.runner.job_queue import JobQueue


def _make_test_app(db_session, job_queue):
    from fastapi import FastAPI
    from app.api.routes import jobs

    app = FastAPI()
    app.include_router(jobs.router)
    app.state.job_queue = job_queue

    async def override_db():
        yield db_session

    app.dependency_overrides[get_db] = override_db
    return app


async def _create_runner(db_session, name="test-runner", status=RunnerStatus.ONLINE):
    runner = Runner(
        name=name, image="agent:latest", status=status, max_concurrent_jobs=3
    )
    db_session.add(runner)
    await db_session.commit()
    await db_session.refresh(runner)
    return runner


@pytest_asyncio.fixture
async def setup(db_session, redis_client):
    queue = JobQueue(db=db_session, redis=redis_client)
    app = _make_test_app(db_session, queue)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, queue, db_session


class TestCreateJob:
    @pytest.mark.asyncio
    async def test_create_job(self, setup):
        client, queue, _ = setup
        resp = await client.post("/api/jobs", json={
            "job_type": "candle_analysis",
            "input": {"symbol": "GOLD", "timeframe": "M15"},
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["job_type"] == "candle_analysis"
        assert data["status"] == "pending"
        assert data["input"] == {"symbol": "GOLD", "timeframe": "M15"}

    @pytest.mark.asyncio
    async def test_create_job_with_runner_id(self, setup):
        client, queue, db = setup
        runner = await _create_runner(db)
        resp = await client.post("/api/jobs", json={
            "job_type": "manual_trade",
            "runner_id": runner.id,
        })
        assert resp.status_code == 200
        assert resp.json()["runner_id"] == runner.id


class TestListJobs:
    @pytest.mark.asyncio
    async def test_list_empty(self, setup):
        client, _, _ = setup
        resp = await client.get("/api/jobs")
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_list_all(self, setup):
        client, queue, _ = setup
        await queue.enqueue("job1")
        await queue.enqueue("job2")

        resp = await client.get("/api/jobs")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    @pytest.mark.asyncio
    async def test_list_filter_by_status(self, setup):
        client, queue, db = setup
        runner = await _create_runner(db)
        await queue.enqueue("task1")
        await queue.enqueue("task2")
        await queue.dispatch()  # task1 or task2 -> RUNNING

        resp = await client.get("/api/jobs?status=pending")
        assert resp.status_code == 200
        pending = resp.json()
        assert all(j["status"] == "pending" for j in pending)

    @pytest.mark.asyncio
    async def test_list_invalid_status(self, setup):
        client, _, _ = setup
        resp = await client.get("/api/jobs?status=bogus")
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_list_filter_by_job_type(self, setup):
        client, queue, _ = setup
        await queue.enqueue("candle_analysis")
        await queue.enqueue("manual_trade")

        resp = await client.get("/api/jobs?job_type=candle_analysis")
        assert resp.status_code == 200
        assert len(resp.json()) == 1
        assert resp.json()[0]["job_type"] == "candle_analysis"


class TestGetJob:
    @pytest.mark.asyncio
    async def test_get_existing(self, setup):
        client, queue, _ = setup
        job = await queue.enqueue("task")

        resp = await client.get(f"/api/jobs/{job.id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == job.id

    @pytest.mark.asyncio
    async def test_get_not_found(self, setup):
        client, _, _ = setup
        resp = await client.get("/api/jobs/9999")
        assert resp.status_code == 404


class TestCancelJob:
    @pytest.mark.asyncio
    async def test_cancel_pending(self, setup):
        client, queue, _ = setup
        job = await queue.enqueue("task")

        resp = await client.post(f"/api/jobs/{job.id}/cancel")
        assert resp.status_code == 200
        assert resp.json()["status"] == "cancelled"

    @pytest.mark.asyncio
    async def test_cancel_completed_fails(self, setup):
        client, queue, db = setup
        runner = await _create_runner(db)
        await queue.enqueue("task")
        job = await queue.dispatch()
        await queue.complete(job.id)

        resp = await client.post(f"/api/jobs/{job.id}/cancel")
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_cancel_not_found(self, setup):
        client, _, _ = setup
        resp = await client.post("/api/jobs/9999/cancel")
        assert resp.status_code == 400  # ValueError from queue


class TestRetryJob:
    @pytest.mark.asyncio
    async def test_retry_failed(self, setup):
        client, queue, db = setup
        runner = await _create_runner(db)
        await queue.enqueue("candle_analysis", input_data={"symbol": "GOLD"})
        job = await queue.dispatch()
        await queue.fail(job.id, "token error")

        resp = await client.post(f"/api/jobs/{job.id}/retry")
        assert resp.status_code == 200
        new_job = resp.json()
        assert new_job["id"] != job.id
        assert new_job["job_type"] == "candle_analysis"
        assert new_job["status"] == "pending"

    @pytest.mark.asyncio
    async def test_retry_non_failed_fails(self, setup):
        client, queue, _ = setup
        job = await queue.enqueue("task")

        resp = await client.post(f"/api/jobs/{job.id}/retry")
        assert resp.status_code == 400


class TestQueueNotInitialized:
    @pytest.mark.asyncio
    async def test_503_when_no_queue(self, db_session):
        from fastapi import FastAPI
        from app.api.routes import jobs

        app = FastAPI()
        app.include_router(jobs.router)

        async def override_db():
            yield db_session

        app.dependency_overrides[get_db] = override_db

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/jobs")
            assert resp.status_code == 503
