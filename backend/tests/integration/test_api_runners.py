"""
Integration tests for Runner Management API routes.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.db.models import RunnerStatus, JobStatus, Runner, RunnerJob, RunnerLog, RunnerMetric
from app.db.session import get_db
from app.runner.backend import RunnerBackend, ResourceMetrics


def _make_test_app(db_session, runner_manager):
    from fastapi import FastAPI
    from app.api.routes import runners

    app = FastAPI()
    app.include_router(runners.router)
    app.state.runner_manager = runner_manager

    async def override_db():
        yield db_session

    app.dependency_overrides[get_db] = override_db
    return app


@pytest.fixture
def mock_backend():
    backend = AsyncMock(spec=RunnerBackend)
    backend.start.return_value = "container-xyz"
    backend.get_metrics.return_value = ResourceMetrics()
    return backend


@pytest_asyncio.fixture
async def setup(db_session, redis_client, mock_backend):
    """Create a RunnerManager and return (client, manager, db_session)."""
    from app.runner.manager import RunnerManager

    manager = RunnerManager(
        db=db_session, redis=redis_client, backend=mock_backend, vault=None
    )
    app = _make_test_app(db_session, manager)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, manager, db_session


class TestRunnerCRUD:
    @pytest.mark.asyncio
    async def test_register_runner(self, setup):
        client, manager, _ = setup
        resp = await client.post("/api/runners", json={
            "name": "gold-agent",
            "image": "agent:v1",
            "max_concurrent_jobs": 5,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "gold-agent"
        assert data["image"] == "agent:v1"
        assert data["status"] == "stopped"
        assert data["max_concurrent_jobs"] == 5

    @pytest.mark.asyncio
    async def test_list_runners_empty(self, setup):
        client, _, _ = setup
        resp = await client.get("/api/runners")
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_list_runners(self, setup):
        client, manager, _ = setup
        await manager.register("r1", "img")
        await manager.register("r2", "img")

        resp = await client.get("/api/runners")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    @pytest.mark.asyncio
    async def test_get_runner(self, setup):
        client, manager, _ = setup
        runner = await manager.register("r1", "img")

        resp = await client.get(f"/api/runners/{runner.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "r1"
        assert "current_jobs" in data

    @pytest.mark.asyncio
    async def test_get_runner_not_found(self, setup):
        client, _, _ = setup
        resp = await client.get("/api/runners/9999")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_update_runner(self, setup):
        client, manager, _ = setup
        runner = await manager.register("old", "img")

        resp = await client.put(f"/api/runners/{runner.id}", json={
            "name": "new-name",
            "max_concurrent_jobs": 10,
        })
        assert resp.status_code == 200
        assert resp.json()["name"] == "new-name"
        assert resp.json()["max_concurrent_jobs"] == 10

    @pytest.mark.asyncio
    async def test_update_runner_not_found(self, setup):
        client, _, _ = setup
        resp = await client.put("/api/runners/9999", json={"name": "x"})
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_runner(self, setup):
        client, manager, _ = setup
        runner = await manager.register("to-delete", "img")

        resp = await client.delete(f"/api/runners/{runner.id}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "deleted"

    @pytest.mark.asyncio
    async def test_delete_runner_not_found(self, setup):
        client, _, _ = setup
        resp = await client.delete("/api/runners/9999")
        assert resp.status_code == 404


class TestRunnerLifecycle:
    @pytest.mark.asyncio
    async def test_start_runner(self, setup):
        client, manager, _ = setup
        runner = await manager.register("r1", "img")

        resp = await client.post(f"/api/runners/{runner.id}/start")
        assert resp.status_code == 200
        assert resp.json()["status"] == "online"

    @pytest.mark.asyncio
    async def test_start_runner_not_found(self, setup):
        client, _, _ = setup
        resp = await client.post("/api/runners/9999/start")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_start_runner_already_online(self, setup):
        client, manager, _ = setup
        runner = await manager.register("r1", "img")
        await manager.start(runner.id)

        resp = await client.post(f"/api/runners/{runner.id}/start")
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_stop_runner(self, setup):
        client, manager, _ = setup
        runner = await manager.register("r1", "img")
        await manager.start(runner.id)

        resp = await client.post(f"/api/runners/{runner.id}/stop")
        assert resp.status_code == 200
        assert resp.json()["status"] == "stopped"

    @pytest.mark.asyncio
    async def test_restart_runner(self, setup):
        client, manager, _ = setup
        runner = await manager.register("r1", "img")
        await manager.start(runner.id)

        resp = await client.post(f"/api/runners/{runner.id}/restart")
        assert resp.status_code == 200
        assert resp.json()["status"] == "online"

    @pytest.mark.asyncio
    async def test_kill_runner(self, setup):
        client, manager, _ = setup
        runner = await manager.register("r1", "img")
        await manager.start(runner.id)

        resp = await client.post(f"/api/runners/{runner.id}/kill")
        assert resp.status_code == 200
        assert resp.json()["status"] == "stopped"


class TestRunnerObservability:
    @pytest.mark.asyncio
    async def test_get_logs(self, setup):
        client, manager, db = setup
        runner = await manager.register("r1", "img")
        log = RunnerLog(runner_id=runner.id, level="info", message="hello")
        db.add(log)
        await db.commit()

        resp = await client.get(f"/api/runners/{runner.id}/logs")
        assert resp.status_code == 200
        assert len(resp.json()) == 1
        assert resp.json()[0]["message"] == "hello"

    @pytest.mark.asyncio
    async def test_get_logs_not_found(self, setup):
        client, _, _ = setup
        resp = await client.get("/api/runners/9999/logs")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_get_logs_invalid_since(self, setup):
        client, manager, _ = setup
        runner = await manager.register("r1", "img")
        resp = await client.get(f"/api/runners/{runner.id}/logs?since=not-a-date")
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_get_logs_with_level_filter(self, setup):
        client, manager, db = setup
        runner = await manager.register("r1", "img")
        db.add(RunnerLog(runner_id=runner.id, level="info", message="info msg"))
        db.add(RunnerLog(runner_id=runner.id, level="error", message="err msg"))
        await db.commit()

        resp = await client.get(f"/api/runners/{runner.id}/logs?level=error")
        assert resp.status_code == 200
        assert len(resp.json()) == 1
        assert resp.json()[0]["level"] == "error"

    @pytest.mark.asyncio
    async def test_get_metrics(self, setup):
        client, manager, db = setup
        runner = await manager.register("r1", "img")
        metric = RunnerMetric(runner_id=runner.id, cpu_percent=20.0, memory_mb=512.0)
        db.add(metric)
        await db.commit()

        resp = await client.get(f"/api/runners/{runner.id}/metrics")
        assert resp.status_code == 200
        assert len(resp.json()) == 1
        assert resp.json()[0]["cpu_percent"] == 20.0

    @pytest.mark.asyncio
    async def test_get_metrics_not_found(self, setup):
        client, _, _ = setup
        resp = await client.get("/api/runners/9999/metrics")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_get_runner_jobs(self, setup):
        client, manager, db = setup
        runner = await manager.register("r1", "img")
        job = RunnerJob(
            runner_id=runner.id,
            job_type="candle_analysis",
            status=JobStatus.COMPLETED,
        )
        db.add(job)
        await db.commit()

        resp = await client.get(f"/api/runners/{runner.id}/jobs")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    @pytest.mark.asyncio
    async def test_get_runner_jobs_invalid_status(self, setup):
        client, manager, _ = setup
        runner = await manager.register("r1", "img")
        resp = await client.get(f"/api/runners/{runner.id}/jobs?status=invalid")
        assert resp.status_code == 400


class TestManagerNotInitialized:
    @pytest.mark.asyncio
    async def test_503_when_no_manager(self, db_session):
        from fastapi import FastAPI
        from app.api.routes import runners

        app = FastAPI()
        app.include_router(runners.router)
        # Intentionally don't set app.state.runner_manager

        async def override_db():
            yield db_session

        app.dependency_overrides[get_db] = override_db

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/runners")
            assert resp.status_code == 503
