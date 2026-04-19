"""Runner Management API — CRUD, lifecycle control, and observability."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import log_audit
from app.auth import require_auth
from app.db.models import JobStatus
from app.db.session import get_db

router = APIRouter(prefix="/api/runners", tags=["runners"])


# ─── Schemas ──────────────────────────────────────────────────────────────────


class RunnerCreateRequest(BaseModel):
    name: str
    image: str = "trading-agent:latest"
    max_concurrent_jobs: int = 3
    tags: list[str] | None = None
    resource_limits: dict | None = None


class RunnerUpdateRequest(BaseModel):
    name: str | None = None
    image: str | None = None
    max_concurrent_jobs: int | None = None
    tags: list[str] | None = None
    resource_limits: dict | None = None


class RunnerResponse(BaseModel):
    id: int
    name: str
    container_id: str | None
    image: str
    status: str
    max_concurrent_jobs: int
    tags: list | None
    resource_limits: dict | None
    last_heartbeat_at: str | None
    created_at: str
    updated_at: str | None


def _runner_to_response(r) -> RunnerResponse:
    return RunnerResponse(
        id=r.id,
        name=r.name,
        container_id=r.container_id,
        image=r.image,
        status=r.status.value if r.status else "stopped",
        max_concurrent_jobs=r.max_concurrent_jobs,
        tags=r.tags,
        resource_limits=r.resource_limits,
        last_heartbeat_at=r.last_heartbeat_at.isoformat() if r.last_heartbeat_at else None,
        created_at=r.created_at.isoformat() if r.created_at else "",
        updated_at=r.updated_at.isoformat() if r.updated_at else None,
    )


def _get_manager(request: Request):
    manager = getattr(request.app.state, "runner_manager", None)
    if not manager:
        raise HTTPException(status_code=503, detail="Runner manager not initialized")
    return manager


# ─── CRUD ─────────────────────────────────────────────────────────────────────


@router.post("", dependencies=[Depends(require_auth)])
async def register_runner(
    req: RunnerCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Register a new runner."""
    manager = _get_manager(request)
    runner = await manager.register(
        name=req.name,
        image=req.image,
        max_concurrent_jobs=req.max_concurrent_jobs,
        tags=req.tags,
        resource_limits=req.resource_limits,
    )
    await log_audit(
        db,
        "runner_registered",
        resource=f"runner:{runner.name}",
        detail={"image": req.image},
        ip=request.client.host if request.client else None,
    )
    return _runner_to_response(runner)


@router.get("", dependencies=[Depends(require_auth)])
async def list_runners(request: Request):
    """List all runners with status."""
    manager = _get_manager(request)
    runners = await manager.list_all()
    return [_runner_to_response(r) for r in runners]


@router.get("/{runner_id}", dependencies=[Depends(require_auth)])
async def get_runner(runner_id: int, request: Request):
    """Get runner detail."""
    manager = _get_manager(request)
    runner = await manager.get(runner_id)
    if not runner:
        raise HTTPException(status_code=404, detail="Runner not found")

    response = _runner_to_response(runner)
    # Include current jobs
    jobs = await manager.get_jobs(runner_id, status=JobStatus.RUNNING)
    current_jobs = [
        {
            "id": j.id,
            "job_type": j.job_type,
            "started_at": j.started_at.isoformat() if j.started_at else None,
        }
        for j in jobs
    ]
    return {**response.model_dump(), "current_jobs": current_jobs}


@router.put("/{runner_id}", dependencies=[Depends(require_auth)])
async def update_runner(
    runner_id: int,
    req: RunnerUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Update runner config."""
    manager = _get_manager(request)
    runner = await manager.update_config(
        runner_id,
        name=req.name,
        image=req.image,
        max_concurrent_jobs=req.max_concurrent_jobs,
        tags=req.tags,
        resource_limits=req.resource_limits,
    )
    if not runner:
        raise HTTPException(status_code=404, detail="Runner not found")

    await log_audit(
        db,
        "runner_updated",
        resource=f"runner:{runner.name}",
        ip=request.client.host if request.client else None,
    )
    return _runner_to_response(runner)


@router.delete("/{runner_id}", dependencies=[Depends(require_auth)])
async def delete_runner(
    runner_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Stop + remove + deregister a runner."""
    manager = _get_manager(request)
    runner = await manager.get(runner_id)
    if not runner:
        raise HTTPException(status_code=404, detail="Runner not found")

    name = runner.name
    removed = await manager.remove(runner_id)
    if not removed:
        raise HTTPException(status_code=500, detail="Failed to remove runner")

    await log_audit(
        db,
        "runner_deleted",
        resource=f"runner:{name}",
        ip=request.client.host if request.client else None,
    )
    return {"status": "deleted", "name": name}


# ─── Lifecycle Control ───────────────────────────────────────────────────────


@router.post("/{runner_id}/start", dependencies=[Depends(require_auth)])
async def start_runner(
    runner_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Pull image → create container → inject secrets → start."""
    manager = _get_manager(request)
    try:
        runner = await manager.start(runner_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e)) from None

    await log_audit(
        db,
        "runner_started",
        resource=f"runner:{runner.name}",
        ip=request.client.host if request.client else None,
    )
    return _runner_to_response(runner)


@router.post("/{runner_id}/stop", dependencies=[Depends(require_auth)])
async def stop_runner(
    runner_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Graceful stop (finish current job → stop)."""
    manager = _get_manager(request)
    try:
        runner = await manager.stop(runner_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None

    await log_audit(
        db,
        "runner_stopped",
        resource=f"runner:{runner.name}",
        ip=request.client.host if request.client else None,
    )
    return _runner_to_response(runner)


@router.post("/{runner_id}/restart", dependencies=[Depends(require_auth)])
async def restart_runner(
    runner_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Stop + start."""
    manager = _get_manager(request)
    try:
        runner = await manager.restart(runner_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None

    await log_audit(
        db,
        "runner_restarted",
        resource=f"runner:{runner.name}",
        ip=request.client.host if request.client else None,
    )
    return _runner_to_response(runner)


@router.post("/{runner_id}/kill", dependencies=[Depends(require_auth)])
async def kill_runner(
    runner_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Force kill (emergency)."""
    manager = _get_manager(request)
    try:
        runner = await manager.kill(runner_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None

    await log_audit(
        db,
        "runner_killed",
        resource=f"runner:{runner.name}",
        ip=request.client.host if request.client else None,
    )
    return _runner_to_response(runner)


# ─── Observability ───────────────────────────────────────────────────────────


@router.get("/{runner_id}/logs", dependencies=[Depends(require_auth)])
async def get_runner_logs(
    runner_id: int,
    request: Request,
    level: str | None = None,
    since: str | None = None,
    limit: int = 100,
    offset: int = 0,
):
    """Get paginated runner logs (filter by level, since timestamp)."""
    manager = _get_manager(request)
    runner = await manager.get(runner_id)
    if not runner:
        raise HTTPException(status_code=404, detail="Runner not found")

    since_dt = None
    if since:
        try:
            since_dt = datetime.fromisoformat(since)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid 'since' datetime format") from None

    logs = await manager.get_logs(runner_id, level=level, since=since_dt, limit=limit, offset=offset)
    return [
        {
            "id": log.id,
            "timestamp": log.timestamp.isoformat() if log.timestamp else None,
            "level": log.level,
            "message": log.message,
            "metadata": log.log_metadata,
        }
        for log in logs
    ]


@router.get("/{runner_id}/metrics", dependencies=[Depends(require_auth)])
async def get_runner_metrics(
    runner_id: int,
    request: Request,
    since: str | None = None,
    limit: int = 100,
):
    """Get resource usage history."""
    manager = _get_manager(request)
    runner = await manager.get(runner_id)
    if not runner:
        raise HTTPException(status_code=404, detail="Runner not found")

    since_dt = None
    if since:
        try:
            since_dt = datetime.fromisoformat(since)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid 'since' datetime format") from None

    metrics = await manager.get_metrics(runner_id, since=since_dt, limit=limit)
    return [
        {
            "id": m.id,
            "timestamp": m.timestamp.isoformat() if m.timestamp else None,
            "cpu_percent": m.cpu_percent,
            "memory_mb": m.memory_mb,
            "memory_limit_mb": m.memory_limit_mb,
            "network_rx_bytes": m.network_rx_bytes,
            "network_tx_bytes": m.network_tx_bytes,
        }
        for m in metrics
    ]


@router.get("/{runner_id}/jobs", dependencies=[Depends(require_auth)])
async def get_runner_jobs(
    runner_id: int,
    request: Request,
    status: str | None = None,
    limit: int = 50,
):
    """Get job history for this runner."""
    manager = _get_manager(request)
    runner = await manager.get(runner_id)
    if not runner:
        raise HTTPException(status_code=404, detail="Runner not found")

    job_status = None
    if status:
        try:
            job_status = JobStatus(status)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}") from None

    jobs = await manager.get_jobs(runner_id, status=job_status, limit=limit)
    return [
        {
            "id": j.id,
            "job_type": j.job_type,
            "status": j.status.value if j.status else None,
            "started_at": j.started_at.isoformat() if j.started_at else None,
            "completed_at": j.completed_at.isoformat() if j.completed_at else None,
            "duration_ms": j.duration_ms,
            "error": j.error,
            "created_at": j.created_at.isoformat() if j.created_at else None,
        }
        for j in jobs
    ]
