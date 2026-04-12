"""
Redis-backed job queue for runner tasks.

Dual storage: Redis for fast dispatch, DB for persistence and history.
On restart, pending jobs are rebuilt from DB.
"""

import json
from datetime import datetime
from typing import Optional

import redis.asyncio as redis_lib
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import RunnerJob, JobStatus, Runner, RunnerStatus

PENDING_QUEUE_KEY = "runner:jobs:pending"
RUNNING_SET_KEY = "runner:jobs:running"


class JobQueue:
    """Redis-backed job queue with DB persistence."""

    def __init__(self, db: AsyncSession, redis: redis_lib.Redis):
        self.db = db
        self.redis = redis

    async def enqueue(
        self,
        job_type: str,
        input_data: Optional[dict] = None,
        runner_id: Optional[int] = None,
    ) -> RunnerJob:
        """Create a new job and add to pending queue."""
        job = RunnerJob(
            runner_id=runner_id,
            job_type=job_type,
            status=JobStatus.PENDING,
            input=input_data,
        )
        self.db.add(job)
        await self.db.commit()
        await self.db.refresh(job)

        # Push to Redis pending queue
        await self.redis.lpush(
            PENDING_QUEUE_KEY,
            json.dumps({
                "job_id": job.id,
                "runner_id": runner_id,
                "job_type": job_type,
                "input": input_data,
            }, default=str),
        )

        logger.info(f"Job {job.id} enqueued: type={job_type}")
        return job

    async def dispatch(self) -> Optional[RunnerJob]:
        """Pop next pending job and assign to an available runner.

        Returns the job if dispatched, None if no pending jobs or no available runners.
        """
        # Pop from Redis queue (non-blocking)
        raw = await self.redis.rpop(PENDING_QUEUE_KEY)
        if not raw:
            return None

        data = json.loads(raw)
        job_id = data["job_id"]
        preferred_runner_id = data.get("runner_id")

        # Get the job from DB
        result = await self.db.execute(
            select(RunnerJob).where(RunnerJob.id == job_id)
        )
        job = result.scalar_one_or_none()
        if not job or job.status != JobStatus.PENDING:
            return None

        # Find an available runner
        runner_id = preferred_runner_id
        if not runner_id:
            runner_id = await self._find_available_runner()

        if not runner_id:
            # No available runner — re-queue
            await self.redis.lpush(PENDING_QUEUE_KEY, raw)
            return None

        # Assign job
        job.runner_id = runner_id
        job.status = JobStatus.RUNNING
        job.started_at = datetime.utcnow()
        await self.db.commit()
        await self.db.refresh(job)

        # Track in running set
        await self.redis.sadd(RUNNING_SET_KEY, str(job.id))

        logger.info(f"Job {job.id} dispatched to runner {runner_id}")
        return job

    async def complete(self, job_id: int, output: Optional[dict] = None) -> RunnerJob:
        """Mark a job as completed."""
        result = await self.db.execute(
            select(RunnerJob).where(RunnerJob.id == job_id)
        )
        job = result.scalar_one_or_none()
        if not job:
            raise ValueError(f"Job {job_id} not found")

        now = datetime.utcnow()
        job.status = JobStatus.COMPLETED
        job.output = output
        job.completed_at = now
        if job.started_at:
            job.duration_ms = int((now - job.started_at).total_seconds() * 1000)
        await self.db.commit()
        await self.db.refresh(job)

        await self.redis.srem(RUNNING_SET_KEY, str(job_id))
        logger.info(f"Job {job_id} completed in {job.duration_ms}ms")
        return job

    async def fail(self, job_id: int, error: str) -> RunnerJob:
        """Mark a job as failed."""
        result = await self.db.execute(
            select(RunnerJob).where(RunnerJob.id == job_id)
        )
        job = result.scalar_one_or_none()
        if not job:
            raise ValueError(f"Job {job_id} not found")

        now = datetime.utcnow()
        job.status = JobStatus.FAILED
        job.error = error
        job.completed_at = now
        if job.started_at:
            job.duration_ms = int((now - job.started_at).total_seconds() * 1000)
        await self.db.commit()
        await self.db.refresh(job)

        await self.redis.srem(RUNNING_SET_KEY, str(job_id))
        logger.warning(f"Job {job_id} failed: {error}")
        return job

    async def cancel(self, job_id: int) -> RunnerJob:
        """Cancel a pending or running job."""
        result = await self.db.execute(
            select(RunnerJob).where(RunnerJob.id == job_id)
        )
        job = result.scalar_one_or_none()
        if not job:
            raise ValueError(f"Job {job_id} not found")

        if job.status not in (JobStatus.PENDING, JobStatus.RUNNING):
            raise ValueError(f"Cannot cancel job in {job.status.value} state")

        job.status = JobStatus.CANCELLED
        job.completed_at = datetime.utcnow()
        await self.db.commit()
        await self.db.refresh(job)

        await self.redis.srem(RUNNING_SET_KEY, str(job_id))
        logger.info(f"Job {job_id} cancelled")
        return job

    async def retry(self, job_id: int) -> RunnerJob:
        """Re-enqueue a failed job."""
        result = await self.db.execute(
            select(RunnerJob).where(RunnerJob.id == job_id)
        )
        job = result.scalar_one_or_none()
        if not job:
            raise ValueError(f"Job {job_id} not found")

        if job.status != JobStatus.FAILED:
            raise ValueError(f"Can only retry failed jobs, got {job.status.value}")

        # Create a new job based on the failed one
        new_job = await self.enqueue(
            job_type=job.job_type,
            input_data=job.input,
            runner_id=job.runner_id,
        )
        logger.info(f"Job {job_id} retried as new job {new_job.id}")
        return new_job

    async def get(self, job_id: int) -> Optional[RunnerJob]:
        result = await self.db.execute(
            select(RunnerJob).where(RunnerJob.id == job_id)
        )
        return result.scalar_one_or_none()

    async def list_jobs(
        self,
        status: Optional[JobStatus] = None,
        runner_id: Optional[int] = None,
        job_type: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[RunnerJob]:
        query = select(RunnerJob)
        if status:
            query = query.where(RunnerJob.status == status)
        if runner_id:
            query = query.where(RunnerJob.runner_id == runner_id)
        if job_type:
            query = query.where(RunnerJob.job_type == job_type)
        query = query.order_by(RunnerJob.created_at.desc()).offset(offset).limit(limit)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def rebuild_from_db(self) -> int:
        """Rebuild Redis pending queue from DB on startup.

        Returns count of re-queued jobs.
        """
        # Clear stale Redis state
        await self.redis.delete(PENDING_QUEUE_KEY)
        await self.redis.delete(RUNNING_SET_KEY)

        # Re-queue pending jobs
        result = await self.db.execute(
            select(RunnerJob)
            .where(RunnerJob.status == JobStatus.PENDING)
            .order_by(RunnerJob.created_at.asc())
        )
        pending_jobs = result.scalars().all()

        for job in pending_jobs:
            await self.redis.lpush(
                PENDING_QUEUE_KEY,
                json.dumps({
                    "job_id": job.id,
                    "runner_id": job.runner_id,
                    "job_type": job.job_type,
                    "input": job.input,
                }, default=str),
            )

        # Mark stale running jobs as failed
        result = await self.db.execute(
            select(RunnerJob).where(RunnerJob.status == JobStatus.RUNNING)
        )
        stale_jobs = result.scalars().all()
        for job in stale_jobs:
            job.status = JobStatus.FAILED
            job.error = "Process terminated unexpectedly (server restart)"
            job.completed_at = datetime.utcnow()
        if stale_jobs:
            await self.db.commit()

        count = len(pending_jobs)
        if count or stale_jobs:
            logger.info(
                f"Job queue rebuilt: {count} pending re-queued, {len(stale_jobs)} stale marked failed"
            )
        return count

    async def pending_count(self) -> int:
        return await self.redis.llen(PENDING_QUEUE_KEY)

    async def running_count(self) -> int:
        return await self.redis.scard(RUNNING_SET_KEY)

    # ─── Internal ────────────────────────────────────────────────────────────

    async def _find_available_runner(self) -> Optional[int]:
        """Find a runner that has capacity for more jobs (single query)."""
        from sqlalchemy import func, literal_column

        # Subquery: count running jobs per runner
        running_counts = (
            select(
                RunnerJob.runner_id,
                func.count(RunnerJob.id).label("running_count"),
            )
            .where(RunnerJob.status == JobStatus.RUNNING)
            .group_by(RunnerJob.runner_id)
            .subquery()
        )

        # Find online runner with capacity
        query = (
            select(Runner.id)
            .outerjoin(running_counts, Runner.id == running_counts.c.runner_id)
            .where(Runner.status == RunnerStatus.ONLINE)
            .where(
                func.coalesce(running_counts.c.running_count, 0) < Runner.max_concurrent_jobs
            )
            .limit(1)
        )

        result = await self.db.execute(query)
        row = result.scalar_one_or_none()
        return row
