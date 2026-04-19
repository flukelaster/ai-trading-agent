"""
Unit tests for runner/backend.py — ProcessRunnerBackend.
"""

import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.runner.backend import LogEntry, ProcessInfo, ProcessRunnerBackend


class TestProcessRunnerBackendStart:
    @pytest.mark.asyncio
    async def test_start_returns_pid(self):
        backend = ProcessRunnerBackend()
        mock_process = AsyncMock()
        mock_process.pid = 1234
        mock_process.returncode = None
        mock_process.stdout = AsyncMock()
        mock_process.stdout.readline = AsyncMock(return_value=b"")

        with patch("asyncio.create_subprocess_exec", return_value=mock_process):
            pid_str = await backend.start(1, "agent:latest", {"KEY": "val"})

        assert pid_str == "1234"
        assert 1 in backend._processes
        assert backend._processes[1].pid == 1234

    @pytest.mark.asyncio
    async def test_start_already_running_raises(self):
        backend = ProcessRunnerBackend()
        mock_process = AsyncMock()
        mock_process.pid = 1234
        mock_process.returncode = None  # still running
        mock_process.stdout = AsyncMock()
        mock_process.stdout.readline = AsyncMock(return_value=b"")

        with patch("asyncio.create_subprocess_exec", return_value=mock_process):
            await backend.start(1, "agent:latest", {})

        with pytest.raises(RuntimeError, match="already running"):
            with patch("asyncio.create_subprocess_exec", return_value=mock_process):
                await backend.start(1, "agent:latest", {})

    @pytest.mark.asyncio
    async def test_start_after_process_exited_allows_restart(self):
        backend = ProcessRunnerBackend()
        mock_process1 = AsyncMock()
        mock_process1.pid = 100
        mock_process1.returncode = 0  # exited
        mock_process1.stdout = AsyncMock()
        mock_process1.stdout.readline = AsyncMock(return_value=b"")
        backend._processes[1] = ProcessInfo(process=mock_process1, pid=100, started_at=datetime.utcnow())

        mock_process2 = AsyncMock()
        mock_process2.pid = 200
        mock_process2.returncode = None
        mock_process2.stdout = AsyncMock()
        mock_process2.stdout.readline = AsyncMock(return_value=b"")

        with patch("asyncio.create_subprocess_exec", return_value=mock_process2):
            pid_str = await backend.start(1, "agent:latest", {})

        assert pid_str == "200"

    @pytest.mark.asyncio
    async def test_start_passes_env_to_subprocess(self):
        backend = ProcessRunnerBackend()
        mock_process = AsyncMock()
        mock_process.pid = 1
        mock_process.returncode = None
        mock_process.stdout = AsyncMock()
        mock_process.stdout.readline = AsyncMock(return_value=b"")

        with patch("asyncio.create_subprocess_exec", return_value=mock_process) as mock_exec:
            await backend.start(42, "img:v1", {"SECRET": "abc"})

        call_kwargs = mock_exec.call_args
        env = call_kwargs.kwargs.get("env") or call_kwargs[1].get("env")
        assert env["SECRET"] == "abc"
        assert env["RUNNER_ID"] == "42"
        assert env["RUNNER_IMAGE"] == "img:v1"


class TestProcessRunnerBackendStop:
    @pytest.mark.asyncio
    async def test_stop_graceful(self):
        backend = ProcessRunnerBackend()
        mock_process = AsyncMock()
        mock_process.pid = 10
        mock_process.returncode = None
        mock_process.wait = AsyncMock(return_value=0)
        info = ProcessInfo(process=mock_process, pid=10, started_at=datetime.utcnow())
        info._log_task = AsyncMock()
        backend._processes[1] = info

        await backend.stop(1, force=False)
        mock_process.terminate.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_force_kill(self):
        backend = ProcessRunnerBackend()
        mock_process = AsyncMock()
        mock_process.pid = 10
        mock_process.returncode = None
        info = ProcessInfo(process=mock_process, pid=10, started_at=datetime.utcnow())
        info._log_task = AsyncMock()
        backend._processes[1] = info

        await backend.stop(1, force=True)
        mock_process.kill.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_nonexistent_runner_is_noop(self):
        backend = ProcessRunnerBackend()
        await backend.stop(999)  # should not raise

    @pytest.mark.asyncio
    async def test_stop_already_exited_is_noop(self):
        backend = ProcessRunnerBackend()
        mock_process = AsyncMock()
        mock_process.returncode = 0  # already exited
        mock_process.pid = 5
        info = ProcessInfo(process=mock_process, pid=5, started_at=datetime.utcnow())
        backend._processes[1] = info

        await backend.stop(1)  # should not raise or call terminate


class TestProcessRunnerBackendIsAlive:
    @pytest.mark.asyncio
    async def test_alive_when_running(self):
        backend = ProcessRunnerBackend()
        mock_process = AsyncMock()
        mock_process.returncode = None
        mock_process.pid = 10
        backend._processes[1] = ProcessInfo(process=mock_process, pid=10, started_at=datetime.utcnow())
        assert await backend.is_alive(1) is True

    @pytest.mark.asyncio
    async def test_not_alive_when_exited(self):
        backend = ProcessRunnerBackend()
        mock_process = AsyncMock()
        mock_process.returncode = 1
        mock_process.pid = 10
        backend._processes[1] = ProcessInfo(process=mock_process, pid=10, started_at=datetime.utcnow())
        assert await backend.is_alive(1) is False

    @pytest.mark.asyncio
    async def test_not_alive_when_unknown(self):
        backend = ProcessRunnerBackend()
        assert await backend.is_alive(999) is False


class TestProcessRunnerBackendGetLogs:
    @pytest.mark.asyncio
    async def test_get_logs_empty(self):
        backend = ProcessRunnerBackend()
        logs = await backend.get_logs(999)
        assert logs == []

    @pytest.mark.asyncio
    async def test_get_logs_with_buffer(self):
        backend = ProcessRunnerBackend()
        mock_process = AsyncMock()
        mock_process.pid = 1
        info = ProcessInfo(process=mock_process, pid=1, started_at=datetime.utcnow())
        now = datetime.utcnow()
        info.log_buffer = [
            LogEntry(timestamp=now - timedelta(minutes=5), level="info", message="old"),
            LogEntry(timestamp=now - timedelta(minutes=1), level="info", message="new"),
        ]
        backend._processes[1] = info

        logs = await backend.get_logs(1)
        assert len(logs) == 2

    @pytest.mark.asyncio
    async def test_get_logs_since_filter(self):
        backend = ProcessRunnerBackend()
        mock_process = AsyncMock()
        mock_process.pid = 1
        info = ProcessInfo(process=mock_process, pid=1, started_at=datetime.utcnow())
        now = datetime.utcnow()
        info.log_buffer = [
            LogEntry(timestamp=now - timedelta(minutes=10), level="info", message="old"),
            LogEntry(timestamp=now - timedelta(minutes=1), level="info", message="recent"),
        ]
        backend._processes[1] = info

        logs = await backend.get_logs(1, since=now - timedelta(minutes=2))
        assert len(logs) == 1
        assert logs[0].message == "recent"

    @pytest.mark.asyncio
    async def test_get_logs_limit(self):
        backend = ProcessRunnerBackend()
        mock_process = AsyncMock()
        mock_process.pid = 1
        info = ProcessInfo(process=mock_process, pid=1, started_at=datetime.utcnow())
        now = datetime.utcnow()
        info.log_buffer = [
            LogEntry(timestamp=now - timedelta(seconds=i), level="info", message=f"log {i}") for i in range(10)
        ]
        backend._processes[1] = info

        logs = await backend.get_logs(1, limit=3)
        assert len(logs) == 3


class TestProcessRunnerBackendGetMetrics:
    @pytest.mark.asyncio
    async def test_metrics_when_no_process(self):
        backend = ProcessRunnerBackend()
        metrics = await backend.get_metrics(999)
        assert metrics.cpu_percent == 0.0
        assert metrics.memory_mb == 0.0

    @pytest.mark.asyncio
    async def test_metrics_with_psutil(self):
        backend = ProcessRunnerBackend()
        mock_process = AsyncMock()
        mock_process.pid = 10
        mock_process.returncode = None
        backend._processes[1] = ProcessInfo(process=mock_process, pid=10, started_at=datetime.utcnow())

        mock_psutil_proc = MagicMock()
        mock_psutil_proc.cpu_percent.return_value = 25.5
        mock_mem = MagicMock()
        mock_mem.rss = 300 * 1024 * 1024  # 300 MB
        mock_psutil_proc.memory_info.return_value = mock_mem

        with patch("psutil.Process", return_value=mock_psutil_proc):
            metrics = await backend.get_metrics(1)

        assert metrics.cpu_percent == 25.5
        assert abs(metrics.memory_mb - 300.0) < 0.1

    @pytest.mark.asyncio
    async def test_metrics_psutil_error_returns_default(self):
        backend = ProcessRunnerBackend()
        mock_process = AsyncMock()
        mock_process.pid = 10
        mock_process.returncode = None
        backend._processes[1] = ProcessInfo(process=mock_process, pid=10, started_at=datetime.utcnow())

        with patch("psutil.Process", side_effect=Exception("no such process")):
            metrics = await backend.get_metrics(1)

        assert metrics.cpu_percent == 0.0


class TestProcessRunnerBackendCleanup:
    @pytest.mark.asyncio
    async def test_cleanup_stops_all(self):
        backend = ProcessRunnerBackend()
        for i in range(3):
            mock_process = AsyncMock()
            mock_process.pid = i
            mock_process.returncode = None
            info = ProcessInfo(process=mock_process, pid=i, started_at=datetime.utcnow())
            info._log_task = AsyncMock()
            backend._processes[i] = info

        await backend.cleanup()
        assert len(backend._processes) == 0


class TestCaptureLogsIntegration:
    @pytest.mark.asyncio
    async def test_capture_plain_text_log(self):
        backend = ProcessRunnerBackend()
        mock_process = AsyncMock()
        mock_process.pid = 1
        info = ProcessInfo(process=mock_process, pid=1, started_at=datetime.utcnow())

        lines = [b"Hello world\n", b""]  # empty signals EOF
        mock_process.stdout.readline = AsyncMock(side_effect=lines)

        await backend._capture_logs(1, info)
        assert len(info.log_buffer) == 1
        assert info.log_buffer[0].message == "Hello world"
        assert info.log_buffer[0].level == "info"

    @pytest.mark.asyncio
    async def test_capture_json_structured_log(self):
        backend = ProcessRunnerBackend()
        mock_process = AsyncMock()
        mock_process.pid = 1
        info = ProcessInfo(process=mock_process, pid=1, started_at=datetime.utcnow())

        json_line = json.dumps({"level": "WARN", "message": "High spread", "metadata": {"spread": 3.2}})
        lines = [f"{json_line}\n".encode(), b""]
        mock_process.stdout.readline = AsyncMock(side_effect=lines)

        await backend._capture_logs(1, info)
        assert len(info.log_buffer) == 1
        assert info.log_buffer[0].level == "warn"
        assert info.log_buffer[0].message == "High spread"
        assert info.log_buffer[0].metadata == {"spread": 3.2}

    @pytest.mark.asyncio
    async def test_capture_logs_buffer_rotation(self):
        backend = ProcessRunnerBackend()
        mock_process = AsyncMock()
        mock_process.pid = 1
        info = ProcessInfo(process=mock_process, pid=1, started_at=datetime.utcnow())

        # Generate 1050 lines + EOF
        lines = [f"line {i}\n".encode() for i in range(1050)] + [b""]
        mock_process.stdout.readline = AsyncMock(side_effect=lines)

        await backend._capture_logs(1, info)
        # Buffer should be capped at MAX_BUFFER=1000
        assert len(info.log_buffer) == 1000
        # Should keep the most recent entries
        assert info.log_buffer[-1].message == "line 1049"
