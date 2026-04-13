# AI Trading Agent

Multi-symbol autonomous trading platform powered by Claude AI agents.
Trades GOLD (XAUUSD), OILCash, BTCUSD, USDJPY via MetaTrader 5.

## Architecture

```
Frontend (Next.js 16, Vercel)
    |
    | HTTPS + WebSocket
    v
Backend (FastAPI, Railway)
    |-- Auth Layer (Passkey WebAuthn + JWT)
    |-- Secrets Vault (AES-256-GCM encrypted)
    |-- Runner Manager (process/Docker sandbox)
    |   |-- Job Queue (Redis + DB)
    |   |-- Heartbeat Monitor
    |   '-- Agent Entrypoint
    |       |-- MCP Tool Server (36 tools)
    |       |-- Guardrails (non-bypassable limits)
    |       '-- Multi-Agent Pipeline
    |           |-- Reflector (Haiku) -- past trade review
    |           |-- Technical Analyst (Haiku) -- indicators
    |           |-- Fundamental Analyst (Haiku) -- sentiment
    |           |-- Risk Analyst (Haiku) -- portfolio risk
    |           '-- Orchestrator (Sonnet) -- final decision
    |-- Strategy Engine (5 strategies + ensemble)
    |-- ML Models (LightGBM per-symbol)
    |-- PostgreSQL + Redis
    '----HTTP----> Windows VPS
                   '-- MT5 Bridge + MetaTrader 5
```

## Tech Stack

| Layer | Tech |
|-------|------|
| Backend | FastAPI 0.115, SQLAlchemy 2.0 (async), asyncpg, Redis, APScheduler |
| Frontend | Next.js 16, React 19, Tailwind 4, Zustand, recharts |
| AI Agent | Anthropic SDK (Claude Sonnet + Haiku), MCP tools, guardrails |
| ML | LightGBM, scikit-learn, pandas |
| Auth | WebAuthn (Passkey) + JWT httpOnly cookie |
| Trading | MetaTrader 5 via HTTP Bridge |
| CI/CD | GitHub Actions (ruff, pytest, tsc, build), Railway auto-deploy |
| DB | PostgreSQL 15, Redis 7 |

## Features

- **AI Agent Trading**: Claude-powered multi-agent system that analyzes markets and executes trades autonomously
- **Passkey Auth**: Passwordless login via WebAuthn (fingerprint/Face ID/YubiKey)
- **Secrets Vault**: AES-256-GCM encrypted storage for API keys and tokens
- **Runner Management**: Docker sandbox runners with live logs, metrics, and job queue
- **Gradual Rollout**: Shadow -> Paper -> Micro-Live -> Live deployment modes
- **Self-Reflection**: Agent reviews past trades to improve future decisions
- **Adaptive Strategy**: Regime detection (trending/ranging/volatile) with automatic strategy selection
- **Session Memory**: Redis-backed context that persists across trading sessions
- **Guardrails**: Hard limits on lot size, daily loss, trade frequency (agent cannot bypass)
- **5 Strategies**: EMA Crossover, RSI Filter, Breakout, Mean Reversion, ML Signal + Ensemble
- **ML Models**: Per-symbol LightGBM with 40+ features, drift detection, auto-retrain
- **Real-time Dashboard**: Trading view, positions, P&L, AI insights, notifications

## Local Development

### 1. Start databases

```bash
docker-compose up -d
```

### 2. Backend

```bash
cd backend
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
pip install -r requirements-dev.txt  # test/lint deps
cp .env.example .env
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

### 3. MT5 Bridge (Windows VPS only)

```bash
cd mt5_bridge
pip install -r requirements.txt
cp .env.example .env  # MT5 credentials
uvicorn main:app --host 0.0.0.0 --port 8001
```

### 4. Frontend

```bash
cd frontend
npm install
cp .env.example .env.local
npm run dev
```

### 5. Run tests

```bash
cd backend
python -m pytest tests/ -v --no-cov  # 413 tests
```

## Environment Variables

See `backend/.env.example` and `mt5_bridge/.env.example`.

Key variables for production:
- `SECRET_KEY` — JWT signing key
- `VAULT_MASTER_KEY` — Secrets vault encryption key
- `WEBAUTHN_RP_ID` / `WEBAUTHN_ORIGIN` — Passkey config
- `CLAUDE_OAUTH_TOKEN` — Claude Max subscription token (stored in Vault)
- `ROLLOUT_MODE` — `shadow` / `paper` / `micro` / `live`
- `AGENT_MODE` — `single` (Phase C) or `multi` (Phase D multi-agent)

## Project Structure

```
backend/
  app/
    api/routes/      # REST endpoints (60+)
    bot/             # Trading engine, scheduler, health monitor
    strategy/        # 5 strategies + ensemble + regime detection
    risk/            # Risk manager, circuit breaker, correlation
    ml/              # LightGBM trainer, features, drift detection
    ai/              # Claude AI client, sentiment, optimization
    runner/          # Docker sandbox runner system
    middleware/      # Auth middleware
    db/              # SQLAlchemy models, migrations
  tests/             # 413 tests (unit + integration)
frontend/
  app/               # Next.js App Router pages
    dashboard/       # Trading dashboard
    runners/         # Runner management + logs + metrics
    secrets/         # Secrets vault UI
    login/           # Passkey login
  components/        # Shared UI components
  lib/               # API client, WebSocket, utilities
mcp_server/
  server.py          # FastMCP server (36 tools)
  guardrails.py      # Trading guardrails (non-bypassable)
  agent_config.py    # Agent loop + tool dispatch
  system_prompt.md   # Agent system prompt
  tools/             # 11 tool modules
  agents/            # 5 specialist agents + orchestrator
mt5_bridge/          # MetaTrader 5 HTTP bridge (Windows VPS)
```
