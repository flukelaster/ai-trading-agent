"""Job Management API — create, list, cancel, retry jobs."""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import log_audit
from app.db.models import JobStatus
from app.db.session import get_db

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


# ─── Schemas ──────────────────────────────────────────────────────────────────


class JobCreateRequest(BaseModel):
    job_type: str
    input: dict | None = None
    runner_id: int | None = None


class JobResponse(BaseModel):
    id: int
    runner_id: int | None
    job_type: str
    status: str
    input: dict | None
    output: dict | None
    started_at: str | None
    completed_at: str | None
    duration_ms: int | None
    error: str | None
    created_at: str


def _job_to_response(j) -> JobResponse:
    return JobResponse(
        id=j.id,
        runner_id=j.runner_id,
        job_type=j.job_type,
        status=j.status.value if j.status else "pending",
        input=j.input,
        output=j.output,
        started_at=j.started_at.isoformat() if j.started_at else None,
        completed_at=j.completed_at.isoformat() if j.completed_at else None,
        duration_ms=j.duration_ms,
        error=j.error,
        created_at=j.created_at.isoformat() if j.created_at else "",
    )


def _get_job_queue(request: Request):
    queue = getattr(request.app.state, "job_queue", None)
    if not queue:
        raise HTTPException(status_code=503, detail="Job queue not initialized")
    return queue


# ─── Endpoints ────────────────────────────────────────────────────────────────


@router.post("")
async def create_job(
    req: JobCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Create a new job (manual trigger)."""
    queue = _get_job_queue(request)
    job = await queue.enqueue(
        job_type=req.job_type,
        input_data=req.input,
        runner_id=req.runner_id,
    )
    await log_audit(
        db, "job_created", resource=f"job:{job.id}",
        detail={"job_type": req.job_type, "runner_id": req.runner_id},
        ip=request.client.host if request.client else None,
    )
    return _job_to_response(job)


@router.get("")
async def list_jobs(
    request: Request,
    status: str | None = None,
    runner_id: int | None = None,
    job_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
):
    """List all jobs with optional filters."""
    queue = _get_job_queue(request)

    job_status = None
    if status:
        try:
            job_status = JobStatus(status)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}") from None

    jobs = await queue.list_jobs(
        status=job_status,
        runner_id=runner_id,
        job_type=job_type,
        limit=limit,
        offset=offset,
    )
    return [_job_to_response(j) for j in jobs]


@router.get("/{job_id}")
async def get_job(job_id: int, request: Request):
    """Get job detail including agent output."""
    queue = _get_job_queue(request)
    job = await queue.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return _job_to_response(job)


@router.post("/{job_id}/cancel")
async def cancel_job(
    job_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Cancel a pending or running job."""
    queue = _get_job_queue(request)
    try:
        job = await queue.cancel(job_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None

    await log_audit(
        db, "job_cancelled", resource=f"job:{job_id}",
        ip=request.client.host if request.client else None,
    )
    return _job_to_response(job)


@router.post("/{job_id}/retry")
async def retry_job(
    job_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Re-enqueue a failed job."""
    queue = _get_job_queue(request)
    try:
        new_job = await queue.retry(job_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None

    await log_audit(
        db, "job_retried", resource=f"job:{job_id}",
        detail={"new_job_id": new_job.id},
        ip=request.client.host if request.client else None,
    )
    return _job_to_response(new_job)
