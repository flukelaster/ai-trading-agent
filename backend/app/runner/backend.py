"""
Runner backend abstraction — allows swapping between process-based and Docker-based execution.

ProcessRunnerBackend: runs agent tasks as async subprocesses (works on Railway).
DockerRunnerBackend: connects to remote Docker host (added in Phase B.4).
"""

import asyncio
import json
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from loguru import logger


@dataclass
class LogEntry:
    timestamp: datetime
    level: str
    message: str
    metadata: Optional[dict] = None


@dataclass
class ResourceMetrics:
    cpu_percent: float = 0.0
    memory_mb: float = 0.0
    memory_limit_mb: float = 0.0
    network_rx_bytes: int = 0
    network_tx_bytes: int = 0


@dataclass
class ProcessInfo:
    """Tracks a running subprocess."""
    process: asyncio.subprocess.Process
    pid: int
    started_at: datetime
    log_buffer: deque[LogEntry] = field(default_factory=lambda: deque(maxlen=1000))
    _log_task: Optional[asyncio.Task] = field(default=None, repr=False)


class RunnerBackend(ABC):
    """Abstract interface for runner execution backends."""

    @abstractmethod
    async def start(self, runner_id: int, image: str, secrets: dict[str, str]) -> str:
        """Start a runner. Returns container/process ID."""

    @abstractmethod
    async def stop(self, runner_id: int, force: bool = False) -> None:
        """Stop a running runner."""

    @abstractmethod
    async def get_logs(
        self, runner_id: int, since: Optional[datetime] = None, limit: int = 100
    ) -> list[LogEntry]:
        """Get recent logs from a runner."""

    @abstractmethod
    async def get_metrics(self, runner_id: int) -> ResourceMetrics:
        """Get current resource usage metrics."""

    @abstractmethod
    async def is_alive(self, runner_id: int) -> bool:
        """Check if the runner process/container is still running."""


class ProcessRunnerBackend(RunnerBackend):
    """
    Runs agent tasks as async subprocesses.
    Works on Railway without Docker dependency.
    """

    def __init__(self):
        self._processes: dict[int, ProcessInfo] = {}

    async def start(self, runner_id: int, image: str, secrets: dict[str, str]) -> str:
        if runner_id in self._processes:
            info = self._processes[runner_id]
            if info.process.returncode is None:
                raise RuntimeError(f"Runner {runner_id} already running (pid={info.pid})")

        env = {**secrets}
        env["RUNNER_ID"] = str(runner_id)
        env["RUNNER_IMAGE"] = image

        # The entrypoint is the agent script — for process backend,
        # we run a Python module that listens for jobs from Redis
        process = await asyncio.create_subprocess_exec(
            "python", "-m", "app.runner.agent_entrypoint",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env,
        )

        info = ProcessInfo(
            process=process,
            pid=process.pid,
            started_at=datetime.utcnow(),
        )

        # Start log capture task
        info._log_task = asyncio.create_task(
            self._capture_logs(runner_id, info)
        )

        self._processes[runner_id] = info
        logger.info(f"Runner {runner_id} started as process pid={process.pid}")
        return str(process.pid)

    async def stop(self, runner_id: int, force: bool = False) -> None:
        info = self._processes.get(runner_id)
        if not info or info.process.returncode is not None:
            return

        if force:
            info.process.kill()
            logger.warning(f"Runner {runner_id} force-killed (pid={info.pid})")
        else:
            info.process.terminate()
            try:
                await asyncio.wait_for(info.process.wait(), timeout=10)
            except asyncio.TimeoutError:
                info.process.kill()
                logger.warning(f"Runner {runner_id} timed out on graceful stop, killed")

        if info._log_task:
            info._log_task.cancel()

        logger.info(f"Runner {runner_id} stopped (pid={info.pid})")

    async def get_logs(
        self, runner_id: int, since: Optional[datetime] = None, limit: int = 100
    ) -> list[LogEntry]:
        info = self._processes.get(runner_id)
        if not info:
            return []

        logs = info.log_buffer
        if since:
            logs = [entry for entry in logs if entry.timestamp >= since]
        return logs[-limit:]

    async def get_metrics(self, runner_id: int) -> ResourceMetrics:
        info = self._processes.get(runner_id)
        if not info or info.process.returncode is not None:
            return ResourceMetrics()

        try:
            import psutil
            proc = psutil.Process(info.pid)
            mem = proc.memory_info()
            # Use interval=None (non-blocking) to avoid blocking the event loop
            cpu = proc.cpu_percent(interval=None)
            return ResourceMetrics(
                cpu_percent=cpu,
                memory_mb=mem.rss / (1024 * 1024),
                memory_limit_mb=0,  # no limit for process backend
            )
        except Exception:
            return ResourceMetrics()

    async def is_alive(self, runner_id: int) -> bool:
        info = self._processes.get(runner_id)
        if not info:
            return False
        return info.process.returncode is None

    async def _capture_logs(self, runner_id: int, info: ProcessInfo) -> None:
        """Read stdout line by line and buffer log entries."""
        try:
            while True:
                line = await info.process.stdout.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").rstrip()
                if not text:
                    continue

                # Try to parse structured JSON log
                level = "info"
                message = text
                metadata = None
                try:
                    parsed = json.loads(text)
                    level = parsed.get("level", "info").lower()
                    message = parsed.get("message", text)
                    metadata = parsed.get("metadata")
                except (json.JSONDecodeError, AttributeError):
                    pass

                entry = LogEntry(
                    timestamp=datetime.utcnow(),
                    level=level,
                    message=message,
                    metadata=metadata,
                )
                info.log_buffer.append(entry)  # deque(maxlen=1000) handles eviction
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Log capture error for runner {runner_id}: {e}")

    async def cleanup(self) -> None:
        """Stop all running processes."""
        for runner_id in list(self._processes.keys()):
            await self.stop(runner_id, force=True)
        self._processes.clear()
