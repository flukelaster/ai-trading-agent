# AI Trading Agent — Claude Code Guide

## Project Overview

Multi-symbol automated trading bot: FastAPI backend (Railway) + Next.js frontend (Vercel) + MT5 Bridge (Windows VPS). Trades GOLD, OILCash, BTCUSD, USDJPY.

**Current state**: Phase 6-10 complete (testing, resilience, trading features, ML, polish). AI Agent architecture (Phases 0-F) complete per ROADMAP-AI-AGENT.md. Now in production hardening and feature polish.

## Architecture

```
Frontend (Next.js 16) → Backend (FastAPI) → MT5 Bridge (Windows VPS)
                                          → PostgreSQL + Redis (Docker)
                                          → Claude AI (sentiment + optimization)
                                          → LightGBM ML models (per-symbol)
                                          → MCP Agent (Claude Code SDK)
                                          → Telegram notifications
```

## Key Directories

- `backend/app/` — FastAPI backend
  - `bot/engine.py` — main trading engine (refactored: process_candle → sub-methods)
  - `bot/scheduler.py` — APScheduler jobs (candle, sentiment, sync, health, retrain)
  - `bot/health_monitor.py` — MT5 Bridge heartbeat + auto-pause/resume
  - `strategy/` — 5 strategies + ensemble + MTF filter + regime detection
  - `risk/` — risk manager, circuit breaker, correlation filter
  - `ml/` — LightGBM trainer, features (40+), predictor, drift detection, sentiment features
  - `backtest/` — engine, optimizer, walk_forward, monte_carlo, overfitting (composite score)
  - `data/` — collector, macro data, macro events
  - `news/` — news fetcher + sources
  - `notifications/` — Telegram alerts
  - `memory/` — session memory service + consolidator
  - `ai/` — Claude AI client (SDK first, Anthropic API fallback), context builder, prompts, strategy optimizer
  - `api/routes/` — 83 REST endpoints across 20 route files
  - `auth.py` — legacy JWT password auth (active)
  - `auth_webauthn.py` — Passkey (WebAuthn) auth (code exists, disabled)
  - `middleware/auth.py` — global JWT cookie auth middleware (backward compat)
  - `vault.py` — VaultService (AES-256-GCM encryption, HKDF key derivation)
  - `vault_health.py` — OAuth token health checker (scheduler job)
  - `runner/` — Docker Sandbox Runner system
    - `backend.py` — RunnerBackend ABC + ProcessRunnerBackend
    - `manager.py` — RunnerManager (lifecycle, secrets injection, observability)
    - `job_queue.py` — Redis-backed job queue with DB persistence
    - `heartbeat.py` — RunnerHeartbeatMonitor (APScheduler integration)
    - `agent_entrypoint.py` — asyncio job loop, Redis BRPOP, health check, heartbeat
  - `api/routes/runners.py` — Runner CRUD + lifecycle + observability (13 endpoints)
  - `api/routes/jobs.py` — Job CRUD + cancel + retry (5 endpoints)
  - `api/routes/activity.py` — AI activity log
  - `api/routes/agent_prompts.py` — agent prompt CRUD
  - `api/routes/rollout.py` — rollout mode + deploy readiness
  - `api/routes/integration.py` — service connectivity diagnostics
  - `api/routes/memory.py` — session memory management
  - `api/ws_runners.py` — WebSocket live log streaming per runner
  - `audit.py` — shared audit logging utility
  - `constants.py` — all magic numbers centralized
  - `config.py` — Settings + SYMBOL_PROFILES + SESSION_PROFILES
  - `metrics.py` — Redis-backed timing/counters
  - `cache.py` — Redis response cache helper
  - `logging_config.py` — structured JSON logging
- `backend/mcp_server/` — MCP Agent system (Claude Code SDK)
  - `agents/` — orchestrator, technical/fundamental/risk analysts, reflector, prompt_registry
  - `tools/` — 14 tool modules (broker, market_data, indicators, risk, portfolio, sentiment, history, journal, learning, session, strategy_gen, memory, overfitting, strategy_switch)
  - `guardrails.py` — non-bypassable trading limits at broker tool level
  - `strategy_switch_guard.py` — AI auto-strategy-switch safety (cooldown 1h, max 3/day, feature flag)
  - `sdk_client.py` — Claude Code SDK client
  - `server.py` — MCP server entry
  - `agent_config.py` — agent entry point
- `frontend/` — Next.js App Router (12 pages)
  - `app/dashboard/` — main trading dashboard
  - `app/backtest/` — backtest, optimizer, walk-forward analysis
  - `app/history/` — trade history/journal
  - `app/insights/` — sentiment analysis + optimization reports
  - `app/ml/` — ML model performance monitoring
  - `app/macro/` — macro economic data + correlations
  - `app/activity/` — unified AI activity log
  - `app/agent-prompts/` — customize AI agent system prompts
  - `app/integration/` — service connectivity status + config
  - `app/notifications/` — event history
  - `app/login/` — passkey login (WebAuthn via @simplewebauthn/browser)
  - `app/setup/` — first-time passkey registration wizard
  - `components/layout/` — AppShell (auth guard + sidebar), Sidebar, PageHeader, PageInstructions
  - `components/ui/` — 21 UI primitives (badge, button, card, dialog, etc.)
  - `components/ai/` — NewsCard, OptimizationReport, SentimentBadge
  - `components/chart/` — PriceChart (lightweight-charts)
  - `lib/api.ts` — axios client with auth interceptor
  - `lib/websocket.ts` — WS client with token auth
- `mt5_bridge/` — FastAPI on Windows VPS (MetaTrader5 SDK)
- `scripts/backup_db.sh` — daily pg_dump
- `backend/tests/` — 444 tests across 27 test files (unit + integration)
- `Dockerfile.trading-agent` — Python 3.11-slim agent image

## Tech Stack

| Layer | Tech |
|-------|------|
| Backend | FastAPI 0.115, SQLAlchemy 2.0 (async), asyncpg, Redis, APScheduler |
| Frontend | Next.js 16, React 19, Tailwind 4, Zustand, lightweight-charts, recharts |
| ML | LightGBM, scikit-learn, pandas |
| AI | Claude Code SDK (Max subscription) + Anthropic SDK fallback |
| Auth | JWT Bearer token (username/password) — WebAuthn code exists but disabled |
| CI/CD | GitHub Actions (ruff, pytest, tsc, build), Railway auto-deploy |
| DB | PostgreSQL 15, Redis 7 (AOF persistence), 14 Alembic migrations |
| Notifications | Telegram bot alerts |

## AI Agent Architecture (Phases 0-F — all code complete)

### Phase 0 — Passkey Auth + Security (code complete, pending deploy)
- Backend: Owner, WebAuthnCredential, AuthSession, AuditLog models
- WebAuthn endpoints: register, login, logout, sessions, me
- Global auth middleware + security headers + CORS tightened
- Frontend: `/setup` (registration) + `/login` (authentication)
- **Disabled**: cross-origin cookie issues on Railway (`.up.railway.app` is public suffix)

### Phase A — Secrets Vault (code complete, pending deploy)
- VaultService: AES-256-GCM + HKDF key derivation from `VAULT_MASTER_KEY`
- Secrets API: CRUD + masked read + test connectivity + history
- OAuth health monitor: scheduler job every 5 min
- Frontend: `/secrets` page (removed from sidebar, accessible via integration page)

### Phase B — Docker Sandbox Runner (backend + frontend done)
- RunnerManager: lifecycle, secrets injection from Vault, observability
- Job Queue: Redis-backed with DB persistence, rebuild on restart
- Heartbeat Monitor: APScheduler job, 3-miss auto-restart
- Runner API (13 endpoints) + Job API (5 endpoints) + WebSocket live logs
- Agent entrypoint: asyncio job loop, Redis BRPOP, health check on :8090

### Phase C — Claude Agent Core (code complete)
- Claude Code SDK: `claude-code-sdk` (Max subscription, no API key needed)
- MCP Tools (12 modules): broker, market_data, indicators, risk, portfolio, sentiment, history, journal, learning, session, strategy_gen, memory
- Guardrails: non-bypassable limits at broker tool level
- `backend/app/ai/client.py`: `complete_async()` tries SDK first, falls back to Anthropic API

### Phase D — Multi-Agent Architecture (code complete)
- Orchestrator (Sonnet) + Technical/Fundamental/Risk Analysts (Haiku) + Reflector (Haiku)
- Only orchestrator has execution tools — specialists are read-only
- Activated via `AGENT_MODE=multi` env var (default: `single`)
- Prompt registry: customizable per-agent system prompts via `/agent-prompts` page

### Phase E — Advanced Capabilities (code complete)
- Self-reflection & learning loop: analyze_recent_trades, detect_regime
- Session memory: Redis-backed daily context (24h TTL) + cross-session learnings (7d TTL)
- Adaptive strategy selection: STRATEGY_PROFILES with regime suitability mapping
- Reflector agent runs as Phase 0 before analysis

### Phase F — Production Hardening (code complete)
- Rollout modes: `shadow` → `paper` → `micro` → `live`
- Broker enforcement: shadow/paper intercepted, micro caps at 0.01 lot
- Deploy readiness checks: DB, Redis, Vault, WebAuthn, OAuth, rollout mode
- Frontend: rollout mode banner + readiness panel on `/runners` page

## Development Commands

```bash
# Backend
cd backend
.venv/Scripts/python.exe -m pytest tests/ -v --no-cov    # run tests (403 tests)
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

- **Auth**: Using Bearer token auth (username/password). `AuthMiddleware` (WebAuthn) disabled in `main.py`. `require_auth` dependency checks `Authorization: Bearer <token>` header. Frontend stores token in localStorage. Tests bypass auth via `AUTH_PASSWORD_HASH=""` in conftest.py.
- **DB session**: Shared session can get dirty — always `rollback()` before new operations in long-lived services
- **SYMBOL_PROFILES**: Per-symbol config in config.py (timeframe, pip_value, SL/TP mults, ML defaults)
- **Constants**: All magic numbers in `constants.py` — never hardcode
- **Tests**: 444 tests across 27 files. SQLite in-memory for DB, fakeredis, mock MT5 connector. Auth disabled via `os.environ["AUTH_PASSWORD_HASH"] = ""` in conftest.py. SDK mocks use `type` attribute instead of `isinstance`.
- **Runner**: `RunnerManager` init in `main.py` lifespan. Uses `ProcessRunnerBackend` by default (Railway-compatible). Heartbeat monitor runs as APScheduler job. Job queue uses dual Redis+DB storage. Runner logs streamed via Redis pub/sub to WebSocket.
- **Coverage**: CI threshold 25% (overall ~29%, critical paths ~89%)
- **Telegram**: Notifications for trade signals, AI analysis, system alerts. Thai language alerts.

## Known Issues

- MT5 Bridge frequently shows "stale tick" warnings (market closed or VPS connectivity)
- Health monitor stays in degraded state when MT5 Bridge is offline (by design)
- Shared db_session can cause `InFailedSQLTransactionError` — mitigated with rollback() calls
- DB datetime columns: must use `datetime.utcnow()` (naive), NOT `datetime.now(timezone.utc)` (offset-aware) — asyncpg rejects offset-aware for `TIMESTAMP WITHOUT TIME ZONE`
- Claude Code SDK: `rate_limit_event` parse error on heavy usage — handled gracefully in `base.py`
- WebAuthn passkey auth: disabled due to cross-origin cookie issues on Railway (`.up.railway.app` is public suffix)
- Deploy: Railway uses Dockerfile CMD, NOT Procfile — always edit `backend/Dockerfile` line 33 for startup changes
- Deploy: Alembic migration can hang on table lock during zero-downtime deploy (old instance holds locks) — mitigated with `timeout 30` in CMD + `lock_timeout = 5s` in alembic/env.py and lifespan
- Alembic: Never reuse revision IDs — each migration file must have a unique revision and correct down_revision chain

## User Preferences (from memory)

- **ตรวจละเอียด**: After every edit, grep to verify ALL occurrences were updated. Don't trust replace_all blindly.
- **Check both frontend AND backend** when a feature spans both sides.
- **ภาษา**: User communicates in Thai, code/commits in English.
