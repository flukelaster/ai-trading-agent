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
  - `api/routes/` — all REST endpoints (40+)
  - `auth.py` — legacy JWT password auth (being replaced)
  - `auth_webauthn.py` — new Passkey (WebAuthn) auth (Phase 0 in progress)
  - `constants.py` — all magic numbers centralized
  - `config.py` — Settings + SYMBOL_PROFILES + SESSION_PROFILES
  - `metrics.py` — Redis-backed timing/counters
  - `cache.py` — Redis response cache helper
  - `logging_config.py` — structured JSON logging
- `frontend/` — Next.js App Router
  - `app/dashboard/` — main trading dashboard
  - `app/login/` — current password login (will become passkey)
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

### Phase 0 — Passkey Auth + Security (IN PROGRESS)
- Backend models done: Owner, WebAuthnCredential, AuthSession, AuditLog
- WebAuthn endpoints done: register, login, logout, sessions, me
- **TODO**: Frontend passkey UI (/setup + /login pages)
- **TODO**: Auth middleware (replace per-route Depends with global middleware)
- **TODO**: Set WEBAUTHN_RP_ID + WEBAUTHN_ORIGIN in Railway env

### Phase A — Secrets Vault (PLANNED)
- Encrypted secrets store (AES-256-GCM) in DB
- Vault UI for managing CLAUDE_OAUTH_TOKEN, MT5_BRIDGE_API_KEY, etc.
- OAuth token health monitor

### Phase B — Docker Sandbox Runner (PLANNED)
- Runner Manager: Docker API client
- Job Queue: Redis-backed
- Runner Management UI
- Biggest phase — 3-4 weeks

### Phase C — Claude Agent Core (PLANNED)
- MCP Tool Server (market, indicators, broker, risk, journal)
- Guardrails (hard limits at tool level)
- System prompt + agent config

### Phase D — Multi-Agent (PLANNED)
- Orchestrator (Sonnet) + Technical/Fundamental/Risk Analysts (Haiku)

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

- **Auth**: `require_auth` dependency on all POST/PUT/DELETE routes. Auth disabled when `AUTH_PASSWORD_HASH` empty (tests set it empty in conftest.py)
- **DB session**: Shared session can get dirty — always `rollback()` before new operations in long-lived services
- **SYMBOL_PROFILES**: Per-symbol config in config.py (timeframe, pip_value, SL/TP mults, ML defaults)
- **Constants**: All magic numbers in `constants.py` — never hardcode
- **Tests**: 142 tests, SQLite in-memory for DB, fakeredis, mock MT5 connector. Auth disabled via `os.environ["AUTH_PASSWORD_HASH"] = ""` in conftest.py
- **Coverage**: CI threshold 25% (overall ~29%, critical paths ~89%)

## Known Issues

- MT5 Bridge frequently shows "stale tick" warnings (market closed or VPS connectivity)
- Health monitor stays in degraded state when MT5 Bridge is offline (by design)
- Shared db_session can cause `InFailedSQLTransactionError` — mitigated with rollback() calls

## User Preferences (from memory)

- **ตรวจละเอียด**: After every edit, grep to verify ALL occurrences were updated. Don't trust replace_all blindly.
- **Check both frontend AND backend** when a feature spans both sides.
- **ภาษา**: User communicates in Thai, code/commits in English.
