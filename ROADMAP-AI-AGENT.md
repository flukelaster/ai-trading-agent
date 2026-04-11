# Gold Trading Bot — AI-First Agent Roadmap v2

> Last updated: 2026-04-11
> Goal: เปลี่ยนจาก rule-based + AI enhancement → **Full Autonomous AI Agent** ที่ใช้ Claude Agent SDK
> Auth: Claude Max subscription via OAuth token only (no API key fallback)
> Login: Passkey (WebAuthn) — single-user, passwordless
> Deploy: Railway + Windows VPS (existing infra) + Docker Sandbox Runner

---

## Why This Migration

ระบบปัจจุบันใช้ AI เป็น **optional filter** เท่านั้น — decision flow ยังเป็น deterministic rule chain:

```
Current:  Signal (rule) → Risk Check (rule) → AI Filter (optional) → Execute
Target:   AI Agent (reasons over everything) → Validate (guardrails) → Execute
```

Claude Agent SDK ทำให้สร้าง autonomous agent ที่ **reason** ได้แทนที่จะ follow rules ตายตัว — เช่น agent เห็น NFP data + gold breakout + USD weakness แล้ว **ตัดสินใจเอง** ว่าควร trade แบบไหน ไม่ต้องพึ่ง hardcoded threshold

---

## System Architecture (Updated)

```
┌─────────────────────────────────────────────────────────────────────┐
│  Frontend — Next.js (Vercel)                                       │
│  ┌─────────────┐ ┌──────────────┐ ┌─────────────┐ ┌────────────┐  │
│  │  Dashboard   │ │ Runner Mgmt  │ │ Secrets Vault│ │  Login     │  │
│  │  (existing)  │ │ (new)        │ │ (new)        │ │  Passkey   │  │
│  └──────┬──────┘ └──────┬───────┘ └──────┬──────┘ └─────┬──────┘  │
│         └───────────────┼───────────────┼───────────────┘          │
│                         ▼               ▼                          │
│                   Authenticated API (JWT + WebAuthn)               │
└─────────────────────────┬───────────────────────────────────────────┘
                          │ HTTPS
┌─────────────────────────▼───────────────────────────────────────────┐
│  Backend — FastAPI (Railway)                                        │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  Auth Layer                                                  │   │
│  │  Passkey (WebAuthn) → JWT session → RBAC middleware          │   │
│  └──────────────────────────────────────────────────────────────┘   │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  Secrets Vault (encrypted at rest)                           │   │
│  │  CLAUDE_OAUTH_TOKEN, MT5_BRIDGE_API_KEY, TELEGRAM_TOKEN      │   │
│  │  → AES-256-GCM encrypted in DB                              │   │
│  │  → Injected into Runner containers at boot                   │   │
│  └──────────────────────────────────────────────────────────────┘   │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  Runner Manager                                              │   │
│  │  Register / Start / Stop / Restart / Delete runners          │   │
│  │  Stream logs, monitor heartbeat, manage job queue            │   │
│  └──────────────┬───────────────────────────────────────────────┘   │
│                 │ Docker API                                        │
│  ┌──────────────▼───────────────────────────────────────────────┐   │
│  │  Docker Sandbox Runner(s)                                    │   │
│  │  ┌────────────────────────────────────────────────────────┐  │   │
│  │  │  Claude Agent (Agent SDK)                              │  │   │
│  │  │  OAuth Token (injected from Vault, not in .env)        │  │   │
│  │  │  MCP Tools → market, broker, risk, portfolio, journal  │  │   │
│  │  │  Guardrails Layer (hard limits, non-bypassable)        │  │   │
│  │  └────────────────────────────────────────────────────────┘  │   │
│  └──────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
         │ HTTP                              │ HTTP
         ▼                                   ▼
   ┌──────────┐                       ┌──────────────┐
   │ MT5 Bridge│                       │  PostgreSQL   │
   │ (Win VPS) │                       │  + Redis      │
   └──────────┘                       └──────────────┘
```

---

## Phase 0 — Authentication & Security Foundation

**เป้าหมาย**: ปิดช่องโหว่ security ก่อนเพิ่ม feature ใด ๆ — ระบบ trading ที่ไม่มี auth = อันตราย

**Priority**: 🔴 Critical — ทำก่อน Phase อื่นทั้งหมด
**Timeline**: 2 สัปดาห์

### 0.1 Passkey Authentication (WebAuthn)

**ทำไมเลือก Passkey?**
- ใช้คนเดียว → ไม่ต้อง user management ซับซ้อน
- ไม่มี password → ไม่มี brute force, ไม่มี credential leak
- Phishing-resistant โดย design (bound to origin)
- UX ดี: แตะ fingerprint / Face ID / YubiKey แล้วเข้าเลย

**Implementation:**

```
Registration Flow (ทำครั้งเดียว):
┌──────────┐     ┌──────────┐     ┌──────────┐
│ Dashboard │ ──▶ │ Backend  │ ──▶ │ Browser  │
│ /setup    │     │ challenge│     │ WebAuthn │
│           │ ◀── │ verify   │ ◀── │ create() │
└──────────┘     └──────────┘     └──────────┘
                       │
                  Store credential
                  (public key + credential ID)
                  in DB

Login Flow (ทุกครั้ง):
┌──────────┐     ┌──────────┐     ┌──────────┐
│ Dashboard │ ──▶ │ Backend  │ ──▶ │ Browser  │
│ /login    │     │ challenge│     │ WebAuthn │
│           │ ◀── │ verify   │ ◀── │ get()    │
└──────────┘     └──────────┘     └──────────┘
                       │
                  Issue JWT
                  (httpOnly, secure, sameSite)
```

**Tech stack:**
- Backend: `py-webauthn` library → FastAPI endpoints
- Frontend: `@simplewebauthn/browser` → React hooks
- Storage: `webauthn_credentials` table (credential_id, public_key, sign_count, created_at)
- Session: JWT in httpOnly cookie — 24h expiry, refresh on activity

**DB Schema:**

```sql
-- Single-owner model — only 1 user ever exists
CREATE TABLE owner (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    display_name VARCHAR(100) NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    is_setup_complete BOOLEAN DEFAULT FALSE
);

CREATE TABLE webauthn_credentials (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id UUID REFERENCES owner(id),
    credential_id BYTEA UNIQUE NOT NULL,
    public_key BYTEA NOT NULL,
    sign_count INTEGER DEFAULT 0,
    device_name VARCHAR(100),       -- "MacBook Pro", "iPhone 15"
    created_at TIMESTAMP DEFAULT NOW(),
    last_used_at TIMESTAMP
);

CREATE TABLE sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id UUID REFERENCES owner(id),
    jwt_jti VARCHAR(64) UNIQUE NOT NULL,    -- JWT ID for revocation
    ip_address INET,
    user_agent TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    expires_at TIMESTAMP NOT NULL,
    revoked_at TIMESTAMP              -- NULL = active
);
```

**Security hardening:**
- First-visit setup wizard: register owner + first passkey
- After setup → `/setup` endpoint disabled permanently
- Multiple passkeys allowed (backup: phone + laptop + YubiKey)
- Session table tracks all active JWTs → can revoke from UI
- Rate limit: 5 failed auth attempts → 15 min lockout
- All auth events logged to `audit_log` table

### 0.2 API Security Layer

ทุก API endpoint (ยกเว้น `/health` และ `/auth/*`) ต้อง authenticated:

```python
# middleware/auth.py
class AuthMiddleware:
    """
    ทุก request ต้องมี JWT ที่ valid
    - Check httpOnly cookie → extract JWT
    - Verify signature + expiry
    - Check JWT ID (jti) not in revoked sessions
    - Attach owner context to request
    """

    EXCLUDED_PATHS = [
        "/health",
        "/auth/challenge",
        "/auth/register",
        "/auth/login",
        "/auth/verify",
    ]
```

**API hardening:**
- CORS: whitelist เฉพาะ frontend domain (ไม่ใช่ `*`)
- Rate limiting: 100 req/min ต่อ session (ปรับได้)
- Request size limit: 1MB max body
- HTTPS only (redirect HTTP → HTTPS)
- Security headers: HSTS, CSP, X-Frame-Options, X-Content-Type-Options

### 0.3 Audit Log

ทุก sensitive action ถูก log:

```sql
CREATE TABLE audit_log (
    id BIGSERIAL PRIMARY KEY,
    timestamp TIMESTAMP DEFAULT NOW(),
    action VARCHAR(50) NOT NULL,      -- 'login', 'logout', 'secret_update', 'runner_start', 'trade_executed'
    actor VARCHAR(50),                -- 'owner', 'agent', 'system'
    resource VARCHAR(100),            -- 'session', 'runner:abc', 'secret:CLAUDE_OAUTH_TOKEN'
    detail JSONB,                     -- action-specific metadata
    ip_address INET,
    success BOOLEAN DEFAULT TRUE
);

-- Index for fast querying
CREATE INDEX idx_audit_timestamp ON audit_log(timestamp DESC);
CREATE INDEX idx_audit_action ON audit_log(action);
```

---

## Phase A — Secrets Vault & Env Management

**เป้าหมาย**: จัดการ CLAUDE_OAUTH_TOKEN และ sensitive config ผ่าน UI อย่างปลอดภัย

**Priority**: 🔴 Critical
**Timeline**: 1.5 สัปดาห์

### A.1 Encrypted Secrets Store

**ทำไมไม่เก็บใน .env?**
- `.env` เป็น plaintext บน disk → ถ้า server ถูก compromise = ได้ทุก key
- เปลี่ยน token ต้อง SSH เข้าไปแก้ + restart → ไม่สะดวก
- ไม่มี audit trail ว่าใครเปลี่ยนเมื่อไหร่

**Architecture:**

```
┌─────────────────────────────────────────────────────┐
│  Secrets Vault (DB-backed)                          │
│                                                     │
│  ┌─────────────────────────────────────────────┐    │
│  │  Master Key (VAULT_MASTER_KEY)              │    │
│  │  → เก็บใน env var ของ Railway เท่านั้น       │    │
│  │  → ไม่เคยผ่าน UI หรือ API                   │    │
│  │  → ใช้ derive encryption key ด้วย HKDF      │    │
│  └──────────────────┬──────────────────────────┘    │
│                     ▼                               │
│  ┌─────────────────────────────────────────────┐    │
│  │  Encrypted Storage (PostgreSQL)             │    │
│  │                                             │    │
│  │  CLAUDE_OAUTH_TOKEN  = AES-256-GCM(value)   │    │
│  │  MT5_BRIDGE_API_KEY  = AES-256-GCM(value)   │    │
│  │  TELEGRAM_BOT_TOKEN  = AES-256-GCM(value)   │    │
│  │  ...                                        │    │
│  └─────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────┘
```

**DB Schema:**

```sql
CREATE TABLE secrets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    key VARCHAR(100) UNIQUE NOT NULL,        -- 'CLAUDE_OAUTH_TOKEN'
    encrypted_value BYTEA NOT NULL,          -- AES-256-GCM ciphertext
    nonce BYTEA NOT NULL,                    -- unique per encryption
    category VARCHAR(50) DEFAULT 'general',  -- 'auth', 'broker', 'notification'
    description TEXT,                        -- human-readable note
    is_required BOOLEAN DEFAULT FALSE,
    last_rotated_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

**API Endpoints:**

```
GET    /api/secrets                → list keys (names only, no values)
GET    /api/secrets/:key          → get decrypted value (masked in response: sk-ant-***fa61)
PUT    /api/secrets/:key          → update value (re-encrypt + audit log)
DELETE /api/secrets/:key          → soft-delete (keep audit trail)
POST   /api/secrets/:key/test     → test connectivity (e.g., validate OAuth token is valid)
GET    /api/secrets/:key/history   → audit log for this secret
```

**Security rules:**
- Values NEVER returned in full via API → ส่งแค่ masked version
- Full value ส่งตรงไปยัง runner container เท่านั้น (injected at boot)
- ทุก read/write ถูก logged ใน audit_log
- VAULT_MASTER_KEY เก็บเฉพาะใน Railway env vars → ไม่มีใน DB, ไม่มีใน code

### A.2 Secrets Management UI

```
┌─────────────────────────────────────────────────────────────┐
│  Secrets Vault                                    [+ Add]   │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  🔐 CLAUDE_OAUTH_TOKEN                         [Required]  │
│  ├─ Value: sk-ant-oat01-****************************fa61    │
│  ├─ Category: auth                                          │
│  ├─ Last rotated: 2 days ago                                │
│  ├─ Status: ✅ Valid (tested 5 min ago)                     │
│  └─ [Edit] [Test Connection] [Rotate] [History]             │
│                                                             │
│  🔐 MT5_BRIDGE_API_KEY                         [Required]  │
│  ├─ Value: brk-****************************3f2a             │
│  ├─ Category: broker                                        │
│  ├─ Last rotated: 14 days ago                               │
│  ├─ Status: ✅ Connected                                    │
│  └─ [Edit] [Test Connection] [History]                      │
│                                                             │
│  🔐 TELEGRAM_BOT_TOKEN                         [Optional]  │
│  ├─ Value: 7182******:AAH****************************Qx     │
│  ├─ Category: notification                                  │
│  ├─ Status: ✅ Active                                       │
│  └─ [Edit] [Test Connection] [History]                      │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### A.3 OAuth Token Health Monitor

เนื่องจากไม่มี API key fallback → OAuth token ต้องมี monitoring เข้มงวด:

```python
class OAuthTokenMonitor:
    """
    ตรวจสอบ Claude OAuth token health อย่างต่อเนื่อง
    ถ้า token หมดอายุ/ถูก revoke → หยุด Agent ทันที + แจ้งเตือน
    """

    CHECK_INTERVAL = 300           # ทุก 5 นาที
    WARNING_BEFORE_EXPIRY = 86400  # แจ้งเตือน 24 ชม. ก่อนหมดอายุ

    async def health_check(self) -> TokenStatus:
        """
        1. ดึง token จาก Vault (decrypted in-memory only)
        2. Call Claude API lightweight endpoint (models list)
        3. ตรวจ response → valid / expired / rate-limited / revoked
        4. ถ้า invalid → trigger alert chain
        """

    async def on_token_failure(self, status: TokenStatus):
        """
        Alert escalation (ไม่มี fallback → ต้องแจ้งทันที):
        1. Dashboard: banner warning สีแดง
        2. Telegram: urgent notification
        3. Agent: graceful pause (ไม่เปิด trade ใหม่, manage existing positions)
        4. Runner: mark as DEGRADED (ไม่รับ job ใหม่)
        """

    async def on_token_near_expiry(self, hours_remaining: int):
        """
        แจ้งเตือนล่วงหน้า:
        - 24h ก่อน: Telegram + Dashboard warning
        - 6h ก่อน: Telegram + Dashboard critical
        - 1h ก่อน: Telegram + Dashboard + pause new trades
        """
```

**Token rotation flow (manual via UI):**

```
1. Owner เข้า Secrets Vault → Click "Rotate" บน CLAUDE_OAUTH_TOKEN
2. UI แสดง dialog: "Paste new token"
3. Backend: encrypt new token → save to DB
4. Backend: signal runner to reload token (hot-reload, ไม่ต้อง restart)
5. Runner: swap token in-memory → ทดสอบ API call
6. ถ้าสำเร็จ → log rotation event
7. ถ้าล้มเหลว → revert to previous token + alert owner
```

---

## Phase B — Docker Sandbox Runner System

**เป้าหมาย**: Full runner management ผ่าน UI — CRUD, logs, jobs, monitoring, Docker control

**Priority**: 🟠 High
**Timeline**: 3–4 สัปดาห์

### B.1 Runner Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Runner Manager (FastAPI service)                       │
│                                                         │
│  ┌───────────────────────────────────────────────────┐  │
│  │  Docker Client (via Docker Engine API)            │  │
│  │  → Create / Start / Stop / Restart / Remove       │  │
│  │  → Attach logs (streaming)                        │  │
│  │  → Inspect resource usage (CPU, RAM, network)     │  │
│  └───────────────────────────────────────────────────┘  │
│                                                         │
│  ┌───────────────────────────────────────────────────┐  │
│  │  Job Queue (Redis-backed)                         │  │
│  │  → Enqueue: candle_close, manual_analysis, etc.   │  │
│  │  → Dispatch to available runner                   │  │
│  │  → Track: pending → running → completed/failed    │  │
│  └───────────────────────────────────────────────────┘  │
│                                                         │
│  ┌───────────────────────────────────────────────────┐  │
│  │  Heartbeat Monitor                                │  │
│  │  → Runners report heartbeat ทุก 30s               │  │
│  │  → Status: online / degraded / offline            │  │
│  │  → Auto-restart ถ้า unhealthy > 3 consecutive     │  │
│  └───────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

**Runner lifecycle:**

```
Register → Pull Image → Create Container → Inject Secrets → Start → Heartbeat Loop
                                                                        │
                              ┌──────────────────────────────────────────┘
                              ▼
                    Receive Job → Execute Agent Task → Report Result → Wait for next Job
                              │
                              ▼ (on failure)
                    Retry (max 2) → Mark Failed → Alert → Auto-restart container
```

**DB Schema:**

```sql
CREATE TABLE runners (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(100) UNIQUE NOT NULL,
    container_id VARCHAR(64),                    -- Docker container ID
    image VARCHAR(200) NOT NULL,                 -- Docker image tag
    status VARCHAR(20) DEFAULT 'stopped',        -- stopped/starting/online/degraded/error
    max_concurrent_jobs INTEGER DEFAULT 3,
    tags JSONB DEFAULT '["docker"]',
    resource_limits JSONB DEFAULT '{"memory": "1G", "cpus": "1.0"}',
    last_heartbeat_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE runner_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    runner_id UUID REFERENCES runners(id),
    job_type VARCHAR(50) NOT NULL,              -- 'candle_analysis', 'manual_trade', 'weekly_review'
    status VARCHAR(20) DEFAULT 'pending',       -- pending/running/completed/failed/cancelled
    input JSONB,                                -- job parameters
    output JSONB,                               -- agent result + reasoning
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    duration_ms INTEGER,
    error TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE runner_logs (
    id BIGSERIAL PRIMARY KEY,
    runner_id UUID REFERENCES runners(id),
    timestamp TIMESTAMP DEFAULT NOW(),
    level VARCHAR(10),                          -- info/warn/error/debug
    message TEXT,
    metadata JSONB
);

CREATE TABLE runner_metrics (
    id BIGSERIAL PRIMARY KEY,
    runner_id UUID REFERENCES runners(id),
    timestamp TIMESTAMP DEFAULT NOW(),
    cpu_percent FLOAT,
    memory_mb FLOAT,
    memory_limit_mb FLOAT,
    network_rx_bytes BIGINT,
    network_tx_bytes BIGINT
);
```

### B.2 Runner Management API

```
# Runner CRUD
POST   /api/runners                → register new runner
GET    /api/runners                → list all runners + status
GET    /api/runners/:id            → runner detail + current jobs
PUT    /api/runners/:id            → update config (image, limits, tags)
DELETE /api/runners/:id            → stop + remove container + deregister

# Runner Control
POST   /api/runners/:id/start      → pull image + create container + inject secrets + start
POST   /api/runners/:id/stop       → graceful stop (finish current job → stop)
POST   /api/runners/:id/restart    → stop + start
POST   /api/runners/:id/kill       → force kill (emergency)

# Runner Observability
GET    /api/runners/:id/logs       → paginated logs (query: level, since, until)
WS     /ws/runners/:id/logs        → live log stream (WebSocket)
GET    /api/runners/:id/metrics    → resource usage history
GET    /api/runners/:id/jobs       → job history for this runner

# Job Management
POST   /api/jobs                   → create job (manual trigger)
GET    /api/jobs                   → list all jobs (filter: status, runner, type)
GET    /api/jobs/:id               → job detail + agent output
POST   /api/jobs/:id/cancel        → cancel pending/running job
POST   /api/jobs/:id/retry         → re-enqueue failed job
```

### B.3 Runner Management UI

```
┌─────────────────────────────────────────────────────────────────────┐
│  🖥 Runners                                         [+ New Runner]  │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │  trading-agent-gold                                          │  │
│  │  ┌────────┐  Container: a4f9c2e1  │  Image: agent:latest    │  │
│  │  │🟢Online│  Uptime: 3d 14h       │  CPU: 12%  RAM: 340MB  │  │
│  │  └────────┘  Last heartbeat: 12s  │  Jobs: 1/3             │  │
│  │                                                              │  │
│  │  [▶ Start] [⏹ Stop] [🔄 Restart] [💀 Kill] [🗑 Delete]     │  │
│  │  [📋 Logs] [📊 Metrics] [⚙ Config]                         │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │  trading-agent-oil  (optional — second symbol)               │  │
│  │  ┌────────┐  Container: —         │  Image: agent:latest    │  │
│  │  │⚫Stopped│                       │                         │  │
│  │  └────────┘                                                  │  │
│  │  [▶ Start] [🗑 Delete] [⚙ Config]                           │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                                                                     │
├─────────────────────────────────────────────────────────────────────┤
│  Recent Jobs                                          [View All →] │
├─────────────────────────────────────────────────────────────────────┤
│  ✅ candle_analysis  │ GOLD M15  │ 2 min ago   │ 1.2s  │ No trade │
│  ✅ candle_analysis  │ GOLD M15  │ 17 min ago  │ 3.4s  │ BUY 0.05 │
│  ✅ candle_analysis  │ GOLD M15  │ 32 min ago  │ 1.8s  │ No trade │
│  ❌ candle_analysis  │ GOLD M15  │ 47 min ago  │ —     │ Token err│
│  ✅ manual_analysis  │ GOLD H1   │ 1h ago      │ 5.1s  │ Report   │
└─────────────────────────────────────────────────────────────────────┘
```

**Live Logs Panel (fullscreen modal):**

```
┌─────────────────────────────────────────────────────────────────────┐
│  📋 Logs — trading-agent-gold          [Filter ▼] [⏸ Pause] [✕]  │
├─────────────────────────────────────────────────────────────────────┤
│  14:30:01 INFO   Candle close received: GOLD M15                   │
│  14:30:01 INFO   [Agent] Fetching OHLCV data...                    │
│  14:30:02 INFO   [Agent] Calculating indicators: EMA, RSI, ATR     │
│  14:30:02 INFO   [Agent] Current sentiment: bullish (0.72)         │
│  14:30:03 INFO   [Agent] Reasoning: "Gold testing 2450 resistance  │
│                   with bullish momentum. RSI 62 — not overbought.  │
│                   News sentiment supports long. However, NFP in    │
│                   3 hours — reducing size by 50%."                 │
│  14:30:03 INFO   [Agent] Decision: BUY 0.03 lot @ 2448.50         │
│  14:30:03 INFO   [Guardrail] ✅ Passed all checks                  │
│  14:30:03 INFO   [Broker] Order placed: ticket #12847              │
│  14:30:04 INFO   [Journal] Decision logged with full reasoning     │
│  14:30:04 INFO   Job completed in 3.4s                             │
│                                                                     │
│  14:15:01 INFO   Candle close received: GOLD M15                   │
│  14:15:01 INFO   [Agent] Fetching OHLCV data...                    │
│  14:15:02 WARN   [Agent] Spread elevated: 3.2 pips (avg: 1.8)     │
│  14:15:02 INFO   [Agent] Decision: HOLD — spread too wide          │
│  14:15:02 INFO   Job completed in 1.2s                             │
└─────────────────────────────────────────────────────────────────────┘
```

**Resource Metrics Panel:**

```
┌─────────────────────────────────────────────────────────────────────┐
│  📊 Metrics — trading-agent-gold                    [1h ▼] [✕]    │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  CPU Usage (%)          Memory (MB)          Network (KB/s)        │
│  ┌──────────────┐      ┌──────────────┐      ┌──────────────┐     │
│  │     ╱╲       │      │  ▁▂▃▄▅▃▂▁   │      │   ╱╲  ╱╲     │     │
│  │  ▁▂▅  ▃▁▂   │      │              │      │  ╱  ╲╱  ╲▁   │     │
│  │              │      │              │      │              │     │
│  │  Avg: 8%     │      │  340/1024 MB │      │  In: 2.1     │     │
│  │  Peak: 45%   │      │  33% used    │      │  Out: 0.8    │     │
│  └──────────────┘      └──────────────┘      └──────────────┘     │
│                                                                     │
│  Agent Calls Today: 87/200        Token Status: ✅ Valid            │
│  Jobs Completed: 82               Jobs Failed: 2                   │
│  Avg Latency: 2.1s                Uptime: 99.7%                   │
└─────────────────────────────────────────────────────────────────────┘
```

### B.4 Runner Docker Image

```dockerfile
# Dockerfile.trading-agent
FROM python:3.11-slim

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl && rm -rf /var/lib/apt/lists/*

# Agent SDK + dependencies
RUN pip install --no-cache-dir \
    anthropic \
    claude-agent-sdk \
    mcp \
    httpx \
    pandas \
    numpy \
    lightgbm \
    scikit-learn \
    redis \
    sqlalchemy[asyncio] \
    asyncpg \
    loguru

# Application code
COPY mcp_server/ /app/mcp_server/
COPY agent/ /app/agent/
COPY strategy/ /app/strategy/
COPY risk/ /app/risk/

WORKDIR /app

# Health check endpoint
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8090/health || exit 1

# Secrets injected at runtime via Runner Manager (not baked into image)
# CLAUDE_OAUTH_TOKEN → injected from Vault
# MT5_BRIDGE_URL → injected from Vault

EXPOSE 8090
CMD ["python", "agent/entrypoint.py"]
```

**Security: Secret injection flow:**

```
Runner Manager                         Docker Container
┌──────────────┐                       ┌──────────────────┐
│ 1. Read from │                       │                  │
│    Vault     │──── decrypt ────▶     │                  │
│ 2. Pass via  │                       │ 3. Receive as    │
│    Docker    │── env injection ──▶   │    env vars      │
│    API       │   (not docker-compose)│    (in-memory)   │
│              │                       │ 4. Never written │
│              │                       │    to disk       │
└──────────────┘                       └──────────────────┘

❌ ไม่ใช้ docker-compose env_file (plaintext on disk)
❌ ไม่ใช้ Docker secrets mount (requires Swarm)
✅ ใช้ Docker API: container.create(environment={...})
✅ Secrets อยู่ใน memory ของ container เท่านั้น
```

---

## Phase C — Claude Agent Core

**เป้าหมาย**: Agent ที่ reason ได้ + MCP tools ครบ + guardrails

**Priority**: 🟠 High
**Timeline**: 3 สัปดาห์

### C.1 MCP Tool Server

(เหมือน Phase A เดิม — ย้ายมาเป็น Phase C เพราะต้องทำ security ก่อน)

```
mcp_server/
├── server.py                 # MCP server entry point (stdio transport)
├── tools/
│   ├── market_data.py        # get_tick, get_ohlcv, get_spread
│   ├── indicators.py         # calculate_ema, calculate_rsi, calculate_atr, full_analysis
│   ├── sentiment.py          # get_latest_sentiment, analyze_news_now
│   ├── risk.py               # validate_trade, calculate_lot, calculate_sl_tp
│   ├── broker.py             # place_order, modify_position, close_position, get_positions
│   ├── portfolio.py          # get_exposure, get_account, check_correlation
│   ├── history.py            # get_trade_history, get_daily_pnl, get_performance_stats
│   └── journal.py            # log_decision, log_reasoning (audit trail)
└── guardrails.py             # Hard limits enforced at tool level
```

**Tool categories & security levels:**

| Category | Tools | Security | Rate Limit |
|----------|-------|----------|------------|
| Read-only | market_data, indicators, portfolio, history | Open | 60/min |
| Analytical | sentiment, risk.validate, risk.calculate | Open | 30/min |
| **Execution** | broker.place_order, broker.modify, broker.close | **Guardrail-gated** | 10/min |
| Logging | journal.log_decision | Open | 120/min |

### C.2 Guardrails (Non-Negotiable)

```python
class TradingGuardrails:
    """
    Agent CANNOT bypass — enforced at MCP broker tool level.
    ทุก broker.place_order() ต้องผ่านที่นี่ก่อน.
    """

    # Position limits
    MAX_LOT_PER_TRADE = 1.0
    MAX_CONCURRENT_PER_SYMBOL = 3
    MAX_CONCURRENT_TOTAL = 5

    # Loss limits
    MAX_DAILY_LOSS_PCT = 0.03
    MAX_WEEKLY_LOSS_PCT = 0.07
    CONSECUTIVE_LOSS_HALT = 5

    # Execution limits
    MAX_TRADES_PER_HOUR = 5
    MIN_TIME_BETWEEN_TRADES = 300    # seconds
    MAX_SPREAD_MULTIPLIER = 3.0

    # Agent limits
    MAX_AGENT_TURNS = 50             # prevent infinite reasoning loops
    AGENT_TIMEOUT = 300              # 5 min max per decision cycle
    MAX_DAILY_AGENT_CALLS = 200      # protect OAuth quota

    # OAuth-specific (no fallback)
    ON_TOKEN_FAILURE = "pause"       # pause agent, don't try alternatives
```

### C.3 System Prompt & Agent Config

(เหมือน version ก่อน แต่ปรับ — ไม่มี fallback)

**เพิ่มใน system prompt:**

```markdown
## CRITICAL: OAuth Token
You are running on a Claude Max subscription via OAuth token.
There is NO API key fallback. If you encounter authentication errors:
1. Log the error via journal.log_decision()
2. Do NOT retry the failed call
3. The system will automatically pause you and alert the owner
4. Focus on managing existing positions safely (no new trades)
```

---

## Phase D — Multi-Agent Architecture

(เหมือน Phase C เดิม)

**Orchestrator** (Sonnet 4.6) → **Technical Analyst** (Haiku) + **Fundamental Analyst** (Haiku) + **Risk Manager** (Haiku)

ทุก agent ใช้ OAuth token เดียวกัน (injected จาก Vault)

---

## Phase E — Advanced Capabilities

(เหมือน Phase D เดิม)

- Self-reflection & learning loop
- Adaptive strategy selection
- Session memory management
- Code generation & strategy creation

---

## Phase F — Production Hardening

### F.1 Reliability (OAuth-Only Strategy)

เนื่องจากไม่มี fallback → reliability ของ token เป็น single point of success:

```
Token Health Pipeline:
┌────────────────────────────────────────────────────────┐
│                                                        │
│  ┌──────────┐     ┌──────────┐     ┌──────────────┐  │
│  │ Health    │ ──▶ │ Token    │ ──▶ │ Alert Chain  │  │
│  │ Check     │     │ Valid?   │     │              │  │
│  │ (ทุก 5 min)│     │          │     │ Dashboard ⚠️ │  │
│  └──────────┘     │  YES → ✅ │     │ Telegram 📱  │  │
│                    │  NO  → ❌ │     │ Agent Pause ⏸│  │
│                    └──────────┘     └──────────────┘  │
│                                                        │
│  Token Near-Expiry Alerts:                             │
│  • 72h before → Dashboard info banner                  │
│  • 24h before → Telegram warning                       │
│  • 6h before  → Telegram critical + Dashboard red      │
│  • 1h before  → Auto-pause new trades                  │
│  • Expired    → Full pause + close-only mode           │
│                                                        │
│  Recovery:                                             │
│  1. Owner receives alert                               │
│  2. Owner generates new token (claude setup-token)     │
│  3. Owner pastes into Secrets Vault UI                 │
│  4. Runner hot-reloads token (no restart needed)       │
│  5. Agent resumes trading                              │
└────────────────────────────────────────────────────────┘
```

### F.2 Gradual Rollout

```
Week 1-2:  Shadow Mode      → Agent runs, decisions logged only
Week 3-4:  Paper Trading     → Agent executes on paper account
Week 5-6:  Micro-Live        → 0.01 lot, real money, minimal risk
Week 7-8:  Scaled Live       → Target risk level, full autonomous
```

---

## Security Checklist (All Phases)

### Authentication & Authorization

- [x] Passkey (WebAuthn) — passwordless login
- [ ] JWT sessions — httpOnly, secure, sameSite=strict
- [ ] Session revocation from UI
- [ ] Rate limiting on auth endpoints (5 attempts → 15 min lockout)
- [ ] Setup wizard locked after initial registration
- [ ] CORS whitelist (no wildcards)

### Secrets Management

- [ ] AES-256-GCM encryption at rest
- [ ] Master key in Railway env only (never in code/DB)
- [ ] Secrets masked in API responses
- [ ] Secrets injected into containers via Docker API (not env files)
- [ ] Audit log for all secret access/modifications
- [ ] Token rotation flow without downtime

### Network Security

- [ ] HTTPS enforced everywhere (HSTS)
- [ ] MT5 Bridge: API key + IP whitelist
- [ ] Docker containers: no host network access
- [ ] Docker: no privileged mode, no host socket mount
- [ ] Database: connection via private network (Railway internal)
- [ ] Redis: password-protected + private network only

### Agent Security

- [ ] Guardrails at MCP tool level (not prompt-only)
- [ ] Max turns + timeout to prevent infinite loops
- [ ] Daily agent call cap to protect OAuth quota
- [ ] All agent decisions logged with reasoning
- [ ] Kill switch: Telegram command + Dashboard button
- [ ] Container resource limits (CPU, memory)

### Data Protection

- [ ] Audit log for all sensitive operations
- [ ] Database: encrypted connections (SSL)
- [ ] No sensitive data in Docker image layers
- [ ] Log redaction: mask tokens/keys in log output
- [ ] Automated daily database backup

### Infrastructure

- [ ] Docker images scanned for vulnerabilities
- [ ] Dependencies pinned to specific versions
- [ ] Container auto-restart on crash (unless kill-switched)
- [ ] Health check probes on all services

---

## Updated Timeline

```
Week 1-2      Week 3-4      Week 5-7      Week 8-9      Week 10-12
───────────   ───────────   ───────────   ───────────   ───────────
Phase 0       Phase A       Phase B       Phase C       Phase D+E
Auth/Login    Secrets       Runner UI     Agent Core    Multi-Agent
Passkey       Vault         Docker Mgmt   MCP Tools     Advanced
Security      OAuth Mon.    Job Queue     Guardrails    Self-Learn
Audit Log     Token UI      Live Logs     System Prompt

                                          Phase F ──────────────────
                                          Shadow → Paper → Micro → Live
```

| Phase | Duration | Effort | Dependency |
|-------|----------|--------|------------|
| **0 — Auth & Security** | 2 weeks | Medium | None — start here |
| **A — Secrets Vault** | 1.5 weeks | Medium | Phase 0 (needs auth) |
| **B — Runner Management** | 3-4 weeks | High | Phase A (needs secrets) |
| **C — Agent Core** | 3 weeks | High | Phase B (needs runner) |
| **D — Multi-Agent** | 3-4 weeks | High | Phase C |
| **E — Advanced** | 4-6 weeks | High | Phase C |
| **F — Production** | 2-3 weeks | Medium | Phase C + B |

**Total estimated: ~16-20 สัปดาห์ (4-5 เดือน)**

---

## Cost Projection (Updated)

| Item | Monthly Cost | Notes |
|------|-------------|-------|
| Claude Max subscription | $100 | **เพียงช่องทางเดียว** — ไม่มี API backup |
| Railway (Backend + Docker) | ~$20-30 | FastAPI + Runner containers + DB + Redis |
| Windows VPS (MT5 Bridge) | ~$24 | Unchanged |
| Domain + SSL | ~$0-5 | Vercel provides free SSL |
| **Total** | **~$145-160** | |

---

## Key Decisions Log (Updated)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Authentication | Passkey (WebAuthn) | Single-user, no password to leak, phishing-resistant |
| OAuth fallback | **None** — OAuth only | ลดความซับซ้อน, invest ใน token monitoring แทน |
| Secrets storage | DB + AES-256-GCM | จัดการผ่าน UI ได้, encrypted at rest, audit trail |
| Runner management | Full UI (CRUD + logs + metrics) | ต้อง manage Docker containers จาก Dashboard |
| Env injection | Docker API runtime injection | ไม่เขียน secrets ลง disk หรือ image layer |
| Agent model | Sonnet 4.6 + Haiku 4.5 | Balance reasoning + cost ภายใน subscription |
| Guardrails | MCP tool layer | Agent bypass ไม่ได้ — enforced infrastructure-side |
