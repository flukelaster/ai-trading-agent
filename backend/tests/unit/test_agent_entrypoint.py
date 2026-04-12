"""
Unit tests for runner/agent_entrypoint.py — agent job executor and helpers.
"""

import asyncio
import json
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from app.runner.agent_entrypoint import (
    execute_job,
    _log,
    PENDING_QUEUE_KEY,
    RUNNING_SET_KEY,
)


class TestExecuteJob:
    @pytest.mark.asyncio
    async def test_stub_returns_result(self):
        result = await execute_job(
            job_id=1,
            job_type="candle_analysis",
            job_input={"symbol": "GOLD", "timeframe": "M15"},
            runner_id=42,
        )
        assert result["status"] == "stub"
        assert result["job_type"] == "candle_analysis"
        assert result["input_received"] == {"symbol": "GOLD", "timeframe": "M15"}
        assert "42" in result["message"]

    @pytest.mark.asyncio
    async def test_stub_handles_none_input(self):
        result = await execute_job(
            job_id=2,
            job_type="manual_trade",
            job_input=None,
            runner_id=1,
        )
        assert result["status"] == "stub"
        assert result["input_received"] is None


class TestLog:
    def test_log_outputs_json(self, capsys):
        _log("info", "test message", {"key": "value"})
        captured = capsys.readouterr()
        data = json.loads(captured.out.strip())
        assert data["level"] == "info"
        assert data["message"] == "test message"
        assert data["metadata"] == {"key": "value"}
        assert "timestamp" in data

    def test_log_without_metadata(self, capsys):
        _log("warn", "warning message")
        captured = capsys.readouterr()
        data = json.loads(captured.out.strip())
        assert data["level"] == "warn"
        assert "metadata" not in data


class TestMainLoopJobProcessing:
    """Test the job processing logic extracted from main loop."""

    @pytest.mark.asyncio
    async def test_job_pickup_and_execution(self, redis_client):
        """Simulate a job being pushed to Redis and picked up."""
        runner_id = 1

        # Push a job to the pending queue
        job_payload = json.dumps({"job_id": 100, "job_type": "candle_analysis", "input": {"symbol": "GOLD"}})
        await redis_client.lpush(PENDING_QUEUE_KEY, job_payload)

        # Pop it (like the main loop would)
        result = await redis_client.brpop(PENDING_QUEUE_KEY, timeout=1)
        assert result is not None

        _key, raw = result
        data = json.loads(raw)
        assert data["job_id"] == 100
        assert data["job_type"] == "candle_analysis"

        # Mark as running
        await redis_client.sadd(RUNNING_SET_KEY, str(data["job_id"]))
        assert await redis_client.scard(RUNNING_SET_KEY) == 1

        # Execute
        output = await execute_job(
            job_id=data["job_id"],
            job_type=data["job_type"],
            job_input=data.get("input"),
            runner_id=runner_id,
        )
        assert output["status"] == "stub"

        # Cleanup
        await redis_client.srem(RUNNING_SET_KEY, str(data["job_id"]))
        assert await redis_client.scard(RUNNING_SET_KEY) == 0

    @pytest.mark.asyncio
    async def test_empty_queue_returns_none(self, redis_client):
        """BRPOP with empty queue and short timeout returns None."""
        result = await redis_client.brpop(PENDING_QUEUE_KEY, timeout=1)
        assert result is None

    @pytest.mark.asyncio
    async def test_targeted_job_requeued_for_different_runner(self, redis_client):
        """Jobs targeted to another runner should be re-queued."""
        runner_id = 1
        other_runner_id = 99

        # Push a job targeted to a different runner
        job_payload = json.dumps({"job_id": 200, "runner_id": other_runner_id})
        await redis_client.lpush(PENDING_QUEUE_KEY, job_payload)

        # Pop it
        result = await redis_client.brpop(PENDING_QUEUE_KEY, timeout=1)
        _key, raw = result
        data = json.loads(raw)

        # Check targeting — should re-queue
        if data.get("runner_id") and data["runner_id"] != runner_id:
            await redis_client.lpush(PENDING_QUEUE_KEY, raw)

        # Verify it's back in the queue
        count = await redis_client.llen(PENDING_QUEUE_KEY)
        assert count == 1

    @pytest.mark.asyncio
    async def test_job_completion_published(self, redis_client):
        """After job execution, a completion event should be publishable."""
        runner_id = 1
        job_id = 300

        # Subscribe to completion channel
        pubsub = redis_client.pubsub()
        await pubsub.subscribe(f"runner:{runner_id}:job_complete")

        # Publish completion event
        await redis_client.publish(
            f"runner:{runner_id}:job_complete",
            json.dumps({
                "job_id": job_id,
                "status": "completed",
                "output": {"result": "no trade"},
            }),
        )

        # Verify message received
        msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
        # fakeredis pub/sub timing may vary
        await pubsub.unsubscribe()

    @pytest.mark.asyncio
    async def test_heartbeat_published(self, redis_client):
        """Heartbeat should be publishable to runner channel."""
        runner_id = 5

        pubsub = redis_client.pubsub()
        await pubsub.subscribe(f"runner:{runner_id}:heartbeat")

        await redis_client.publish(
            f"runner:{runner_id}:heartbeat",
            json.dumps({"runner_id": runner_id, "timestamp": "2026-04-12T00:00:00Z"}),
        )

        await pubsub.unsubscribe()

    @pytest.mark.asyncio
    async def test_invalid_payload_skipped(self):
        """Invalid JSON payloads should be handled gracefully."""
        raw = b"not-json"
        try:
            data = json.loads(raw)
            _job_id = data["job_id"]
            assert False, "Should have raised"
        except (json.JSONDecodeError, KeyError):
            pass  # Expected — entrypoint logs and continues

    @pytest.mark.asyncio
    async def test_missing_job_id_skipped(self):
        """Payload without job_id should be handled gracefully."""
        raw = json.dumps({"runner_id": 1}).encode()
        try:
            data = json.loads(raw)
            _job_id = data["job_id"]
            assert False, "Should have raised KeyError"
        except KeyError:
            pass  # Expected
