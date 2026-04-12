# Gold Trading Bot — Claude Code Guide

## Project Overview

Multi-symbol automated trading bot: FastAPI backend (Railway) + Next.js frontend (Vercel) + MT5 Bridge (Windows VPS). Trades GOLD, OILCash, BTCUSD, USDJPY.

**Current state**: Phase 6-10 complete (testing, resilience, trading features, ML, polish). Now migrating to AI Agent architecture per ROADMAP-AI-AGENT.md.

## Architecture

```
Frontend (Next.js 16) → Backend (FastAPI) → MT5 Bridge (Windows VPS)
                                          → PostgreSQL + Redis (Docker)
                                          → Claude AI (sentiment + optimization)
                                          → LightGBM ML models (per-symbol)
```

## Key Directories

- `backend/app/` — FastAPI backend
  - `bot/engine.py` — main trading engine (refactored: process_candle → sub-methods)
  - `bot/scheduler.py` — APScheduler jobs (candle, sentiment, sync, health, retrain)
  - `bot/health_monitor.py` — MT5 Bridge heartbeat + auto-pause/resume
  - `strategy/` — 5 strategies + ensemble + MTF filter + regime detection
  - `risk/` — risk manager, circuit breaker, correlation filter
  - `ml/` — LightGBM trainer, features (40+), predictor, drift detection, sentiment features
  - `api/routes/` — all REST endpoints (58+)
  - `auth.py` — legacy JWT password auth (being replaced)
  - `auth_webauthn.py` — new Passkey (WebAuthn) auth (Phase 0 in progress)
  - `middleware/auth.py` — global JWT cookie auth middleware (backward compat if no passkey setup)
  - `vault.py` — VaultService (AES-256-GCM encryption, HKDF key derivation)
  - `vault_health.py` — OAuth token health checker (scheduler job)
  - `runner/` — Docker Sandbox Runner system (Phase B)
    - `backend.py` — RunnerBackend ABC + ProcessRunnerBackend
    - `manager.py` — RunnerManager (lifecycle, secrets injection, observability)
    - `job_queue.py` — Redis-backed job queue with DB persistence
    - `heartbeat.py` — RunnerHeartbeatMonitor (APScheduler integration)
  - `api/routes/runners.py` — Runner CRUD + lifecycle + observability (13 endpoints)
  - `api/routes/jobs.py` — Job CRUD + cancel + retry (5 endpoints)
  - `api/ws_runners.py` — WebSocket live log streaming per runner
  - `audit.py` — shared audit logging utility
  - `constants.py` — all magic numbers centralized
  - `config.py` — Settings + SYMBOL_PROFILES + SESSION_PROFILES
  - `metrics.py` — Redis-backed timing/counters
  - `cache.py` — Redis response cache helper
  - `logging_config.py` — structured JSON logging
- `frontend/` — Next.js App Router
  - `app/dashboard/` — main trading dashboard
  - `app/login/` — passkey login (WebAuthn via @simplewebauthn/browser)
  - `app/setup/` — first-time passkey registration wizard
  - `app/notifications/` — event history
  - `components/layout/AppShell.tsx` — auth guard + sidebar layout
  - `lib/api.ts` — axios client with auth interceptor
  - `lib/websocket.ts` — WS client with token auth
- `mt5_bridge/` — FastAPI on Windows VPS (MetaTrader5 SDK)
- `scripts/backup_db.sh` — daily pg_dump
- `backend/tests/` — 142 tests (unit + integration)

## Tech Stack

| Layer | Tech |
|-------|------|
| Backend | FastAPI 0.115, SQLAlchemy 2.0 (async), asyncpg, Redis, APScheduler |
| Frontend | Next.js 16, React 19, Tailwind 4, Zustand, lightweight-charts |
| ML | LightGBM, scikit-learn, pandas |
| AI | Anthropic SDK (Claude Haiku sentiment + optimization) |
| Auth | WebAuthn (py-webauthn) + JWT httpOnly cookie (migrating from password) |
| CI/CD | GitHub Actions (ruff, pytest, tsc, build), Railway auto-deploy |
| DB | PostgreSQL 15, Redis 7 (AOF persistence) |

## Active Migration: AI Agent Architecture (ROADMAP-AI-AGENT.md)

### Phase 0 — Passkey Auth + Security (DONE — code complete, pending deploy)
- Backend models done: Owner, WebAuthnCredential, AuthSession, AuditLog
- WebAuthn endpoints done: register, login, logout, sessions, me
- Alembic migration done: `g7h8i9j0k1l2_add_auth_tables.py`
- Global auth middleware done: `app/middleware/auth.py` (JWT cookie, session revocation, backward compat)
- Security headers done: X-Content-Type-Options, X-Frame-Options, X-XSS-Protection, Referrer-Policy
- CORS tightened: specific methods/headers instead of `*`
- Frontend passkey UI done: `/setup` (registration) + `/login` (authentication) with `@simplewebauthn/browser`
- Frontend migrated from localStorage tokens to httpOnly cookie auth (`withCredentials: true`)
- Logout calls backend `/api/auth/logout` to revoke session
- AppShell auth guard updated: handles `/setup` redirect for first-time setup
- **DEPLOY TODO**: `alembic upgrade head` on production DB
- **DEPLOY TODO**: Set `WEBAUTHN_RP_ID` + `WEBAUTHN_ORIGIN` in Railway env
- **DEPLOY TODO**: Ensure `SECRET_KEY` is set to a strong random value

### Phase A — Secrets Vault (DONE — code complete, pending deploy)
- VaultService done: `app/vault.py` — AES-256-GCM + HKDF key derivation from `VAULT_MASTER_KEY`
- Secret model done: `app/db/models.py` — encrypted_value, nonce, category, soft-delete
- Alembic migration done: `h8i9j0k1l2m3_add_secrets_table.py`
- Secrets API done: `app/api/routes/secrets.py` — CRUD + masked read + test connectivity + history (7 endpoints)
- Shared audit utility done: `app/audit.py` — extracted from auth_webauthn.py, used by vault
- OAuth health monitor done: `app/vault_health.py` + scheduler job every 5 min
- Frontend Secrets page done: `/secrets` with edit dialog, test button, history panel
- Sidebar nav updated: "Secrets" entry with KeyRound icon
- Tests: 24 new (7 unit + 17 integration), total 166 pass
- **DEPLOY TODO**: Set `VAULT_MASTER_KEY` in Railway env
- **DEPLOY TODO**: `alembic upgrade head` to create `secrets` table

### Phase B — Docker Sandbox Runner (IN PROGRESS — backend + frontend done, Docker backend + agent entrypoint pending)
- Backend models done: Runner, RunnerJob, RunnerLog, RunnerMetric + RunnerStatus/JobStatus enums
- Alembic migration done: `i9j0k1l2m3n4_add_runner_tables.py`
- RunnerBackend abstraction done: `runner/backend.py` — ProcessRunnerBackend (Railway-compatible), DockerRunnerBackend planned for Week 4
- RunnerManager done: `runner/manager.py` — lifecycle (register/start/stop/kill/restart/remove), secrets injection from Vault, observability
- Job Queue done: `runner/job_queue.py` — Redis-backed with DB persistence, rebuild on restart
- Heartbeat Monitor done: `runner/heartbeat.py` — APScheduler job, 3-miss auto-restart
- Runner API done: `api/routes/runners.py` — 13 endpoints (CRUD + lifecycle + logs + metrics + jobs)
- Job API done: `api/routes/jobs.py` — 5 endpoints (create + list + detail + cancel + retry)
- WebSocket live logs done: `api/ws_runners.py` — Redis pub/sub streaming
- Registered in `main.py` with lifespan init + shutdown
- Config additions in `config.py`: runner_backend, docker_host, heartbeat settings
- Tests: 148 new (22 backend, 30 job_queue, 10 heartbeat, 38 manager, 25 runners API, 16 jobs API, 4 WebSocket, 11 agent_entrypoint), total 314 pass
- Bug fixed: `RunnerLog.metadata` → `RunnerLog.log_metadata` (SQLAlchemy reserved attribute name conflict)
- Frontend Runner Management UI done: `/runners` page with runner cards, status badges, lifecycle buttons, live logs (WebSocket), metrics charts (recharts), recent jobs table, create dialog
- WS auth: `GET /api/auth/ws-token` endpoint returns short-lived token for WebSocket connections
- Sidebar nav: "Runners" entry with Server icon
- Agent entrypoint done: `runner/agent_entrypoint.py` — asyncio job loop, Redis BRPOP, structured JSON logging, health check on :8090, heartbeat, graceful shutdown. Phase B stub executor (Phase C replaces with Claude Agent SDK)
- **TODO**: Docker backend (`runner/docker_backend.py` with `aiodocker`) — deferred until Phase C agent is validated
- **TODO**: Agent Docker image (`Dockerfile.trading-agent`)
- **DEPLOY TODO**: `alembic upgrade head` to create runner tables
- **DEPLOY TODO**: Install `psutil` (added to requirements.txt)

### Phase C — Claude Agent Core (IN PROGRESS — MCP tools + guardrails done, agent config pending)
- MCP Tool Server done: `mcp_server/` — FastMCP with 24 tools across 8 modules
  - `tools/market_data.py` — get_tick, get_ohlcv, get_spread (wraps MT5BridgeConnector)
  - `tools/indicators.py` — EMA, RSI, ATR, full_analysis (wraps strategy/indicators.py)
  - `tools/risk.py` — validate_trade, calculate_lot, calculate_sl_tp (wraps risk/manager.py)
  - `tools/broker.py` — place_order, modify_position, close_position, get_positions (GUARDRAIL-GATED)
  - `tools/portfolio.py` — get_account, get_exposure, check_correlation
  - `tools/sentiment.py` — get_latest_sentiment, history (queries backend API)
  - `tools/history.py` — get_trade_history, get_daily_pnl, get_performance (queries backend API)
  - `tools/journal.py` — log_decision, log_reasoning (audit trail)
  - `server.py` — FastMCP server entry, registers all 24 tools
- Guardrails done: `mcp_server/guardrails.py` — non-bypassable limits at broker tool level
  - MAX_LOT=1.0, MAX_CONCURRENT=5, MAX_DAILY_LOSS=3%, MAX_TRADES_PER_HOUR=5
  - Consecutive loss halt, min time between trades, spread check
  - Agent call daily cap (200), Redis-backed state tracking
- Agent config done: `mcp_server/agent_config.py` — agentic loop (Messages API + tool_use), 24 tool definitions + dispatch, MAX_AGENT_TURNS=50, AGENT_TIMEOUT=300s
- System prompt done: `mcp_server/system_prompt.md` — trading philosophy, decision framework, OAuth handling
- Agent entrypoint updated: `runner/agent_entrypoint.py` — auto-detects Claude token, runs full agent loop if available, falls back to stub
- Dockerfile done: `Dockerfile.trading-agent` — Python 3.11-slim, non-root user, health check :8090, secrets injected at runtime
- `requirements.txt` updated: anthropic>=0.94.0 (was 0.42.0)
- Tests: 26 new (guardrails + risk tools), total 340 pass

### Phase D — Multi-Agent Architecture (DONE — code complete)
- Orchestrator (Sonnet) + Technical Analyst (Haiku) + Fundamental Analyst (Haiku) + Risk Analyst (Haiku)
- `mcp_server/agents/base.py` — shared agent loop, tool filtering, model constants
- `mcp_server/agents/technical_analyst.py` — market_data + indicators tools, trend/momentum/volatility analysis
- `mcp_server/agents/fundamental_analyst.py` — sentiment + history tools, bias assessment
- `mcp_server/agents/risk_analyst.py` — risk + portfolio tools, position sizing, correlation check
- `mcp_server/agents/orchestrator.py` — runs specialists in parallel, synthesizes reports, makes final decision, executes trades
- Only orchestrator has execution tools (place_order, modify/close_position) — specialists are read-only
- Activated via `AGENT_MODE=multi` env var (default: `single` for Phase C mode)
- Tests: 23 new (tool subsets, model selection, agent loop, synthesis, integration, error handling), total 395 pass

### Phase E — Advanced Capabilities (DONE — code complete)
- **Self-reflection & learning loop**: `mcp_server/tools/learning.py` — analyze_recent_trades (win/loss patterns, strategy stats), detect_regime (trending/ranging/volatile/transitional), optimization history
- **Session memory management**: `mcp_server/tools/session.py` — Redis-backed daily context (24h TTL) + cross-session learnings (7d TTL, capped at 50). save_context/get_context per symbol, save_learning/get_learnings with categories
- **Adaptive strategy selection**: `mcp_server/tools/strategy_gen.py` — STRATEGY_PROFILES with regime suitability mapping, recommend_strategy by regime, generate_strategy_config with validated parameter ranges
- **Template-based strategy generation**: generate_strategy_config (safe parameter injection with range validation), generate_ensemble_config (weighted voting with sum validation)
- **Reflector agent**: `mcp_server/agents/reflector.py` — Haiku specialist that runs as Phase 0 before analysis. Reviews past trades, detects regime, recalls learnings, recommends strategy
- **Orchestrator updated**: Phase 0 (Reflection) runs before Phase 1 (Specialists). Reflection report included in synthesis message
- **Tools expanded**: 36 total tools (24 Phase C + 12 Phase E: 3 learning + 4 session + 4 strategy + 1 detect_regime)
- Tests: 32 new (strategy gen, session memory, regime detection, reflector, orchestrator+reflection), total 413 pass

### Phase F — Production Hardening (DONE — code complete)
- Rollout mode system: `shadow` → `paper` → `micro` → `live` (gradual deployment)
  - Shadow: agent runs, decisions logged only — no trades executed
  - Paper: simulated execution with fake tickets — no real money
  - Micro: real execution capped at 0.01 lot — minimal risk
  - Live: full autonomous trading at target risk levels
- Broker enforcement: `broker.place_order()` checks rollout mode BEFORE execution
  - Shadow/Paper intercepted at broker level (never reaches MT5 Bridge)
  - Micro caps lot at `MICRO_MAX_LOT=0.01` before forwarding to MT5
- Config: `settings.rollout_mode` + `ROLLOUT_MODE` env var + Redis persistence
- API: `GET/PUT /api/rollout/mode` — get/set with audit logging, confirmation for "live"
- Deploy readiness: `GET /api/rollout/readiness` — checks DB, Redis, Vault key, WebAuthn, Secret key, OAuth token, rollout mode
- Frontend: Rollout mode banner + dropdown + readiness check panel on `/runners` page
- Tests: 18 new (guardrail modes, broker shadow/paper/micro/live, API endpoints, readiness), total 413 pass

## Development Commands

```bash
# Backend
cd backend
.venv/Scripts/python.exe -m pytest tests/ -v --no-cov    # run tests
.venv/Scripts/python.exe -m ruff check .                   # lint
.venv/Scripts/python.exe -m ruff format .                  # format

# Frontend
cd frontend
npx tsc --noEmit          # type check
npm run build             # production build
npm run dev               # dev server

# Railway
railway vars list -s backend --kv    # list env vars
railway logs                          # view logs
railway vars set -s backend "KEY=value"  # set env var
```

## Important Patterns

- **Auth**: Global `AuthMiddleware` in `main.py` enforces JWT cookie auth. If no passkey registered (`is_setup_complete=False`), middleware passes all requests through (backward compat). Old `require_auth` dependency still exists for legacy password auth. Tests bypass auth via `AUTH_PASSWORD_HASH=""` in conftest.py and don't include the middleware.
- **DB session**: Shared session can get dirty — always `rollback()` before new operations in long-lived services
- **SYMBOL_PROFILES**: Per-symbol config in config.py (timeframe, pip_value, SL/TP mults, ML defaults)
- **Constants**: All magic numbers in `constants.py` — never hardcode
- **Tests**: 413 tests, SQLite in-memory for DB, fakeredis, mock MT5 connector. Auth disabled via `os.environ["AUTH_PASSWORD_HASH"] = ""` in conftest.py. Runner: 148, Guardrails+MCP: 26, Multi-agent: 23, Phase E: 32, Phase F: 18. Total coverage of Phase B-F.
- **Runner**: `RunnerManager` init in `main.py` lifespan. Uses `ProcessRunnerBackend` by default (Railway-compatible). Heartbeat monitor runs as APScheduler job. Job queue uses dual Redis+DB storage. Runner logs streamed via Redis pub/sub to WebSocket.
- **Coverage**: CI threshold 25% (overall ~29%, critical paths ~89%)

## Known Issues

- MT5 Bridge frequently shows "stale tick" warnings (market closed or VPS connectivity)
- Health monitor stays in degraded state when MT5 Bridge is offline (by design)
- Shared db_session can cause `InFailedSQLTransactionError` — mitigated with rollback() calls

## User Preferences (from memory)

- **ตรวจละเอียด**: After every edit, grep to verify ALL occurrences were updated. Don't trust replace_all blindly.
- **Check both frontend AND backend** when a feature spans both sides.
- **ภาษา**: User communicates in Thai, code/commits in English.
