"""
Runner Manager — orchestrates runner lifecycle and coordinates with backend, vault, and DB.

State machine: stopped → starting → online → degraded/error
"""

from datetime import datetime

import redis.asyncio as redis_lib
from loguru import logger
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    JobStatus,
    Runner,
    RunnerJob,
    RunnerLog,
    RunnerMetric,
    RunnerStatus,
    Secret,
)
from app.runner.backend import RunnerBackend
from app.vault import VaultService


class RunnerManager:
    """Manages runner lifecycle: register, start, stop, kill, restart, remove."""

    def __init__(
        self,
        db: AsyncSession,
        redis: redis_lib.Redis,
        backend: RunnerBackend,
        vault: VaultService | None = None,
    ):
        self.db = db
        self.redis = redis
        self.backend = backend
        self.vault = vault

    # ─── Runner CRUD ─────────────────────────────────────────────────────────

    async def register(
        self,
        name: str,
        image: str,
        max_concurrent_jobs: int = 3,
        tags: list | None = None,
        resource_limits: dict | None = None,
    ) -> Runner:
        """Register a new runner (does not start it)."""
        runner = Runner(
            name=name,
            image=image,
            max_concurrent_jobs=max_concurrent_jobs,
            tags=tags or ["process"],
            resource_limits=resource_limits or {"memory": "1G", "cpus": "1.0"},
            status=RunnerStatus.STOPPED,
        )
        self.db.add(runner)
        await self.db.commit()
        await self.db.refresh(runner)
        logger.info(f"Runner registered: {name} (id={runner.id})")
        return runner

    async def get(self, runner_id: int) -> Runner | None:
        result = await self.db.execute(select(Runner).where(Runner.id == runner_id))
        return result.scalar_one_or_none()

    async def list_all(self) -> list[Runner]:
        result = await self.db.execute(select(Runner).order_by(Runner.created_at.desc()))
        return list(result.scalars().all())

    async def update_config(
        self,
        runner_id: int,
        name: str | None = None,
        image: str | None = None,
        max_concurrent_jobs: int | None = None,
        tags: list | None = None,
        resource_limits: dict | None = None,
    ) -> Runner | None:
        runner = await self.get(runner_id)
        if not runner:
            return None
        if name is not None:
            runner.name = name
        if image is not None:
            runner.image = image
        if max_concurrent_jobs is not None:
            runner.max_concurrent_jobs = max_concurrent_jobs
        if tags is not None:
            runner.tags = tags
        if resource_limits is not None:
            runner.resource_limits = resource_limits
        runner.updated_at = datetime.utcnow()
        await self.db.commit()
        await self.db.refresh(runner)
        return runner

    async def remove(self, runner_id: int) -> bool:
        """Stop and deregister a runner."""
        runner = await self.get(runner_id)
        if not runner:
            return False

        # Stop if running
        if runner.status in (RunnerStatus.ONLINE, RunnerStatus.STARTING, RunnerStatus.DEGRADED):
            await self.stop(runner_id, force=True)

        await self.db.delete(runner)
        await self.db.commit()
        logger.info(f"Runner removed: {runner.name} (id={runner_id})")
        return True

    # ─── Lifecycle Control ───────────────────────────────────────────────────

    async def start(self, runner_id: int) -> Runner:
        """Start a runner: decrypt secrets → pass to backend → update status."""
        runner = await self.get(runner_id)
        if not runner:
            raise ValueError(f"Runner {runner_id} not found")

        if runner.status == RunnerStatus.ONLINE:
            raise RuntimeError(f"Runner {runner.name} already online")

        # Update status to starting
        runner.status = RunnerStatus.STARTING
        runner.updated_at = datetime.utcnow()
        await self.db.commit()

        try:
            # Decrypt secrets from vault
            secrets = await self._get_decrypted_secrets()

            # Start via backend
            container_id = await self.backend.start(runner_id, runner.image, secrets)

            runner.container_id = container_id
            runner.status = RunnerStatus.ONLINE
            runner.last_heartbeat_at = datetime.utcnow()
            runner.updated_at = datetime.utcnow()
            await self.db.commit()
            await self.db.refresh(runner)

            await self._log(runner_id, "info", f"Runner started (container_id={container_id})")
            logger.info(f"Runner {runner.name} started successfully")
            return runner

        except Exception as e:
            runner.status = RunnerStatus.ERROR
            runner.updated_at = datetime.utcnow()
            await self.db.commit()
            await self._log(runner_id, "error", f"Failed to start: {e}")
            raise

    async def stop(self, runner_id: int, force: bool = False) -> Runner:
        """Graceful or forced stop."""
        runner = await self.get(runner_id)
        if not runner:
            raise ValueError(f"Runner {runner_id} not found")

        await self.backend.stop(runner_id, force=force)

        runner.status = RunnerStatus.STOPPED
        runner.container_id = None
        runner.updated_at = datetime.utcnow()
        await self.db.commit()
        await self.db.refresh(runner)

        action = "force-killed" if force else "stopped"
        await self._log(runner_id, "info", f"Runner {action}")
        logger.info(f"Runner {runner.name} {action}")
        return runner

    async def kill(self, runner_id: int) -> Runner:
        """Force kill (emergency)."""
        return await self.stop(runner_id, force=True)

    async def restart(self, runner_id: int) -> Runner:
        """Stop then start."""
        await self.stop(runner_id, force=False)
        return await self.start(runner_id)

    # ─── Heartbeat ───────────────────────────────────────────────────────────

    async def record_heartbeat(self, runner_id: int) -> None:
        """Called by heartbeat monitor when a runner responds."""
        await self.db.execute(update(Runner).where(Runner.id == runner_id).values(last_heartbeat_at=datetime.utcnow()))
        await self.db.commit()

    async def mark_degraded(self, runner_id: int, reason: str) -> None:
        runner = await self.get(runner_id)
        if runner and runner.status == RunnerStatus.ONLINE:
            runner.status = RunnerStatus.DEGRADED
            runner.updated_at = datetime.utcnow()
            await self.db.commit()
            await self._log(runner_id, "warn", f"Runner degraded: {reason}")

    # ─── Observability ───────────────────────────────────────────────────────

    async def get_logs(
        self,
        runner_id: int,
        level: str | None = None,
        since: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[RunnerLog]:
        """Get logs from DB (persistent history)."""
        query = select(RunnerLog).where(RunnerLog.runner_id == runner_id)
        if level:
            query = query.where(RunnerLog.level == level)
        if since:
            query = query.where(RunnerLog.timestamp >= since)
        query = query.order_by(RunnerLog.timestamp.desc()).offset(offset).limit(limit)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_metrics(
        self,
        runner_id: int,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[RunnerMetric]:
        """Get resource metrics history from DB."""
        query = select(RunnerMetric).where(RunnerMetric.runner_id == runner_id)
        if since:
            query = query.where(RunnerMetric.timestamp >= since)
        query = query.order_by(RunnerMetric.timestamp.desc()).limit(limit)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_jobs(
        self,
        runner_id: int,
        status: JobStatus | None = None,
        limit: int = 50,
    ) -> list[RunnerJob]:
        query = select(RunnerJob).where(RunnerJob.runner_id == runner_id)
        if status:
            query = query.where(RunnerJob.status == status)
        query = query.order_by(RunnerJob.created_at.desc()).limit(limit)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def collect_metrics(self, runner_id: int) -> RunnerMetric | None:
        """Collect current metrics from backend and persist to DB."""
        metrics = await self.backend.get_metrics(runner_id)
        metric = RunnerMetric(
            runner_id=runner_id,
            cpu_percent=metrics.cpu_percent,
            memory_mb=metrics.memory_mb,
            memory_limit_mb=metrics.memory_limit_mb,
            network_rx_bytes=metrics.network_rx_bytes,
            network_tx_bytes=metrics.network_tx_bytes,
        )
        self.db.add(metric)
        await self.db.commit()
        return metric

    # ─── Shutdown ────────────────────────────────────────────────────────────

    async def shutdown(self) -> None:
        """Stop all runners and cleanup backend resources."""
        runners = await self.list_all()
        for runner in runners:
            if runner.status in (RunnerStatus.ONLINE, RunnerStatus.STARTING, RunnerStatus.DEGRADED):
                try:
                    await self.stop(runner.id, force=True)
                except Exception as e:
                    logger.error(f"Error stopping runner {runner.name}: {e}")
        await self.backend.cleanup()
        logger.info("RunnerManager shutdown complete")

    # ─── Internal Helpers ────────────────────────────────────────────────────

    async def _get_decrypted_secrets(self) -> dict[str, str]:
        """Decrypt all secrets from vault for injection into runner."""
        if not self.vault or not self.vault._derived_key:
            return {}

        result = await self.db.execute(
            select(Secret).where(Secret.is_deleted == False)  # noqa: E712
        )
        secrets = result.scalars().all()

        decrypted = {}
        for secret in secrets:
            try:
                value = self.vault.decrypt(secret.encrypted_value, secret.nonce)
                decrypted[secret.key] = value
            except Exception as e:
                logger.warning(f"Failed to decrypt a secret: {type(e).__name__}")
        return decrypted

    async def _log(self, runner_id: int, level: str, message: str, metadata: dict | None = None) -> None:
        """Persist a log entry to DB and publish to Redis for live streaming."""
        log = RunnerLog(
            runner_id=runner_id,
            level=level,
            message=message,
            log_metadata=metadata,
        )
        self.db.add(log)
        await self.db.commit()

        # Publish to Redis for WebSocket live streaming
        try:
            import json

            await self.redis.publish(
                f"runner:{runner_id}:logs",
                json.dumps(
                    {
                        "timestamp": datetime.utcnow().isoformat(),
                        "level": level,
                        "message": message,
                        "metadata": metadata,
                    }
                ),
            )
        except Exception:
            pass  # Redis publish failure is non-critical
