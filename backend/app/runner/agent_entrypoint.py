"""
Agent entrypoint — the process spawned by ProcessRunnerBackend.

Reads jobs from Redis, executes them, and reports results.
Outputs structured JSON logs to stdout (captured by ProcessRunnerBackend._capture_logs).

Phase B: stub executor (logs job info, returns placeholder result).
Phase C: will be replaced with Claude Agent SDK + MCP tools.

Usage: python -m app.runner.agent_entrypoint
Env vars injected by ProcessRunnerBackend:
  RUNNER_ID  — numeric ID of this runner
  RUNNER_IMAGE — image name (informational)
  + all decrypted secrets from Vault
"""

import asyncio
import json
import os
import signal
import sys
from datetime import datetime, timezone
from typing import Optional

import redis.asyncio as redis_lib


# ─── Structured logging (JSON to stdout, captured by ProcessRunnerBackend) ───

def _log(level: str, message: str, metadata: Optional[dict] = None) -> None:
    entry = {
        "level": level,
        "message": message,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if metadata:
        entry["metadata"] = metadata
    print(json.dumps(entry), flush=True)


# ─── Constants ───────────────────────────────────────────────────────────────

try:
    from app.runner.job_queue import PENDING_QUEUE_KEY, RUNNING_SET_KEY
except ImportError:
    PENDING_QUEUE_KEY = "runner:jobs:pending"
    RUNNING_SET_KEY = "runner:jobs:running"
HEARTBEAT_INTERVAL = 30  # seconds
POLL_TIMEOUT = 5  # seconds for BRPOP


# ─── Job Executor ────────────────────────────────────────────────────────────

_AGENT_AVAILABLE = False
_MULTI_AGENT_AVAILABLE = False
try:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
    from mcp_server.agent_config import run_agent, run_multi_agent
    from mcp_server.tools.broker import init_broker
    _AGENT_AVAILABLE = True
    _MULTI_AGENT_AVAILABLE = True
except ImportError:
    pass


async def execute_job(
    job_id: int,
    job_type: str,
    job_input: Optional[dict],
    runner_id: int,
    redis_client: Optional[object] = None,
) -> dict:
    """Execute an agent job.

    If the Claude Agent (mcp_server) is available and CLAUDE_OAUTH_TOKEN is set,
    runs the full agentic loop. Otherwise falls back to stub executor.
    """
    _log("info", f"[Agent] Executing job {job_id}: type={job_type}", {
        "job_id": job_id,
        "job_type": job_type,
        "input": job_input,
    })

    oauth_token = os.environ.get("CLAUDE_OAUTH_TOKEN")

    if _AGENT_AVAILABLE and oauth_token:
        # Initialize broker with Redis for guardrails
        if redis_client:
            init_broker(redis_client)

        # Choose single-agent or multi-agent mode
        use_multi = os.environ.get("AGENT_MODE", "single") == "multi"

        if use_multi and _MULTI_AGENT_AVAILABLE:
            _log("info", "[Agent] Running multi-agent pipeline (orchestrator + specialists)")
            try:
                result = await run_multi_agent(
                    job_type=job_type,
                    job_input=job_input,
                    oauth_token=oauth_token,
                )
                _log("info", f"[Agent] Job {job_id} completed via multi-agent", {
                    "orchestrator_turns": result.get("orchestrator_turns"),
                    "total_tool_calls": result.get("total_tool_calls"),
                    "total_duration_s": result.get("total_duration_s"),
                })
                return result
            except Exception as e:
                _log("error", f"[Agent] Multi-agent error: {e}, falling back to single agent")

        # Single-agent mode (default)
        _log("info", "[Agent] Running single-agent Claude loop")
        try:
            result = await run_agent(
                job_type=job_type,
                job_input=job_input,
                oauth_token=oauth_token,
            )
            _log("info", f"[Agent] Job {job_id} completed via Claude agent", {
                "turns": result.get("turns"),
                "duration_s": result.get("duration_s"),
                "tool_calls_count": len(result.get("tool_calls", [])),
            })
            return result
        except Exception as e:
            _log("error", f"[Agent] Claude agent error: {e}, falling back to stub")
            return {
                "status": "error",
                "error": str(e),
                "decision": "HOLD — agent error",
                "job_type": job_type,
            }
    else:
        # Stub executor (no token or agent not available)
        reason = "no CLAUDE_OAUTH_TOKEN" if not oauth_token else "agent module not available"
        _log("info", f"[Agent] Using stub executor ({reason})")
        await asyncio.sleep(0.1)

        result = {
            "status": "stub",
            "message": f"Job {job_id} processed by runner {runner_id} (stub — {reason})",
            "job_type": job_type,
            "input_received": job_input,
        }
        _log("info", f"[Agent] Job {job_id} completed (stub)", {"result": result})
        return result


# ─── Health Check Server ────────────────────────────────────────────────────

async def _handle_health(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    """Minimal HTTP health check on port 8090."""
    await reader.read(4096)  # consume request
    body = json.dumps({"status": "ok"})
    response = (
        f"HTTP/1.1 200 OK\r\n"
        f"Content-Type: application/json\r\n"
        f"Content-Length: {len(body)}\r\n"
        f"\r\n"
        f"{body}"
    )
    writer.write(response.encode())
    await writer.drain()
    writer.close()


async def start_health_server() -> Optional[asyncio.Server]:
    """Start a minimal TCP health server on port 8090."""
    try:
        server = await asyncio.start_server(_handle_health, "0.0.0.0", 8090)
        _log("info", "Health check server started on :8090")
        return server
    except OSError as e:
        _log("warn", f"Could not start health server: {e}")
        return None


# ─── Main Loop ──────────────────────────────────────────────────────────────

async def main() -> None:
    runner_id = int(os.environ.get("RUNNER_ID", "0"))
    runner_image = os.environ.get("RUNNER_IMAGE", "unknown")
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

    if runner_id == 0:
        _log("error", "RUNNER_ID not set, exiting")
        sys.exit(1)

    _log("info", f"Agent entrypoint starting: runner_id={runner_id}, image={runner_image}")

    # Connect to Redis
    redis_client = redis_lib.from_url(redis_url)
    try:
        await redis_client.ping()
        _log("info", "Connected to Redis")
    except Exception as e:
        _log("error", f"Failed to connect to Redis: {e}")
        sys.exit(1)

    # Start health server
    health_server = await start_health_server()

    # Shutdown signal handling
    shutdown_event = asyncio.Event()

    def _signal_handler():
        _log("info", "Shutdown signal received")
        shutdown_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            # Windows doesn't support add_signal_handler
            pass

    _log("info", "Entering job processing loop")
    last_heartbeat = asyncio.get_event_loop().time()

    try:
        while not shutdown_event.is_set():
            # Send heartbeat periodically
            now = asyncio.get_event_loop().time()
            if now - last_heartbeat >= HEARTBEAT_INTERVAL:
                try:
                    await redis_client.publish(
                        f"runner:{runner_id}:heartbeat",
                        json.dumps({"runner_id": runner_id, "timestamp": datetime.now(timezone.utc).isoformat()}),
                    )
                    last_heartbeat = now
                except Exception:
                    pass

            # Poll for jobs (BRPOP with timeout to stay responsive to shutdown)
            try:
                result = await redis_client.brpop(PENDING_QUEUE_KEY, timeout=POLL_TIMEOUT)
            except Exception as e:
                _log("error", f"Redis BRPOP error: {e}")
                await asyncio.sleep(1)
                continue

            if result is None:
                # No job available, loop back
                continue

            # Parse job payload
            _key, raw = result
            try:
                data = json.loads(raw)
                job_id = data["job_id"]
                preferred_runner_id = data.get("runner_id")
            except (json.JSONDecodeError, KeyError) as e:
                _log("error", f"Invalid job payload: {e}", {"raw": raw.decode() if isinstance(raw, bytes) else str(raw)})
                continue

            # Check if this job is targeted to a different runner
            if preferred_runner_id and preferred_runner_id != runner_id:
                # Re-queue for the correct runner
                await redis_client.lpush(PENDING_QUEUE_KEY, raw)
                continue

            _log("info", f"Picked up job {job_id}")

            # Mark as running
            await redis_client.sadd(RUNNING_SET_KEY, str(job_id))

            # Execute the job
            try:
                output = await execute_job(
                    job_id=job_id,
                    job_type=data.get("job_type", "unknown"),
                    job_input=data.get("input"),
                    runner_id=runner_id,
                    redis_client=redis_client,
                )

                # Publish completion event (manager listens for this to update DB)
                await redis_client.publish(
                    f"runner:{runner_id}:job_complete",
                    json.dumps({
                        "job_id": job_id,
                        "status": "completed",
                        "output": output,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }),
                )
            except Exception as e:
                _log("error", f"Job {job_id} failed: {e}")
                await redis_client.publish(
                    f"runner:{runner_id}:job_complete",
                    json.dumps({
                        "job_id": job_id,
                        "status": "failed",
                        "error": str(e),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }),
                )
            finally:
                # Remove from running set
                await redis_client.srem(RUNNING_SET_KEY, str(job_id))

    finally:
        _log("info", "Shutting down agent entrypoint")
        if health_server:
            health_server.close()
            await health_server.wait_closed()
        await redis_client.aclose()


# ─── Module entry point ─────────────────────────────────────────────────────

if __name__ == "__main__":
    asyncio.run(main())
