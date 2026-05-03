"""
JWT Authentication — single-user auth for protecting the dashboard.
When auth_password_hash is empty, auth is disabled (backward compat).
"""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from loguru import logger
from pydantic import BaseModel

from app.config import settings

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Lazy imports to avoid hard dependency when auth is disabled
_jwt_module = None
_pwd_context = None


JWT_ALGORITHM = "HS256"


def _get_jwt():
    """Lazy PyJWT loader. Migrated off python-jose 3.3.0 (CVE-2024-33663/33664
    algorithm confusion). PyJWT is actively maintained and the same `decode`
    call already pins ``algorithms=[JWT_ALGORITHM]`` so unsigned ``alg=none``
    tokens are rejected at the library boundary."""
    global _jwt_module
    if _jwt_module is None:
        try:
            import jwt as _jwt

            _jwt_module = _jwt
        except ImportError as e:
            raise HTTPException(
                status_code=500,
                detail="PyJWT not installed. Run: pip install 'PyJWT[crypto]>=2.10.1'",
            ) from e
    return _jwt_module


def _get_pwd_context():
    global _pwd_context
    if _pwd_context is None:
        try:
            from passlib.context import CryptContext

            _pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
        except ImportError as e:
            raise HTTPException(
                status_code=500,
                detail="passlib not installed. Run: pip install passlib[bcrypt]",
            ) from e
    return _pwd_context


def _auth_enabled() -> bool:
    return bool(settings.auth_password_hash)


def _assert_auth_consistent() -> None:
    """Fail fast on startup if auth config could produce forgeable tokens."""
    if settings.auth_password_hash and not settings.auth_username:
        raise RuntimeError(
            "AUTH_PASSWORD_HASH is set but AUTH_USERNAME is empty — refusing to start. "
            "Either set both, or clear AUTH_PASSWORD_HASH to disable auth."
        )
    if _auth_enabled() and not settings.secret_key:
        raise RuntimeError(
            "SECRET_KEY is empty while auth is enabled — refusing to start. Set SECRET_KEY to a long random value."
        )
    _PLACEHOLDERS = {
        "change-me-in-production",
        "changeme",
        "secret",
        "please-change",
        "password",
        "1234",
        "test",
        "default",
    }
    sk = settings.secret_key.strip()
    if sk.lower() in _PLACEHOLDERS:
        raise RuntimeError("SECRET_KEY is set to a placeholder value — refusing to start. Generate a real secret.")
    # 32 chars ≈ 192 bits when base64-ish, comfortably above the 128-bit
    # collision floor for HMAC-SHA256. Refuse short keys that would let an
    # offline attacker brute-force the JWT signing material.
    if _auth_enabled() and len(sk) < 32:
        raise RuntimeError(
            "SECRET_KEY must be at least 32 characters when auth is enabled. "
            "Generate via: python -c 'import secrets; print(secrets.token_urlsafe(48))'"
        )
    if settings.vault_master_key and len(settings.vault_master_key) < 32:
        raise RuntimeError(
            "VAULT_MASTER_KEY must be at least 32 characters. "
            "Short keys reduce HKDF entropy and let an offline attacker brute-force the derived AES key."
        )
    if "*" in settings.cors_origin_list:
        raise RuntimeError(
            "CORS_ORIGINS must not contain '*' — wildcard origins combined with credentialed cookies "
            "violate the CORS spec and expose the API to any origin. List exact origins instead."
        )


# ─── Models ───────────────────────────────────────────────────────────────────


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ─── Token Management ─────────────────────────────────────────────────────────


def create_access_token(username: str, expire_hours: int | None = None) -> str:
    jwt = _get_jwt()
    hours = expire_hours if expire_hours is not None else settings.jwt_expire_hours
    expire = datetime.now(UTC) + timedelta(hours=hours)
    payload = {"sub": username, "exp": expire}
    return jwt.encode(payload, settings.secret_key, algorithm=JWT_ALGORITHM)


def mint_internal_token() -> str:
    """Short-lived JWT (24h) for internal MCP tools → backend API calls.

    Re-minted on every app restart, so a Railway redeploy invalidates the
    previous token. Avoid 90-day tokens that linger in env vars / process
    memory long after a leak window.

    Empty string when auth disabled.
    """
    if not _auth_enabled() or not settings.secret_key:
        return ""
    return create_access_token("internal_agent", expire_hours=24)


def verify_token(token: str) -> str | None:
    """Verify JWT and return username, or None if invalid."""
    jwt = _get_jwt()
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[JWT_ALGORITHM])
        return payload.get("sub")
    except Exception:
        return None


def decode_token(token: str) -> dict | None:
    """Decode a JWT and return the full payload (or None on failure).

    Used by paths that need claims beyond ``sub`` — e.g. checking ``jti`` for
    session revocation in /ws-token.
    """
    jwt = _get_jwt()
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[JWT_ALGORITHM])
    except Exception:
        return None


# ─── Dependencies ─────────────────────────────────────────────────────────────

_bearer_scheme = HTTPBearer(auto_error=False)


async def require_auth(credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme)):
    """
    FastAPI dependency for protected endpoints.
    No-op when auth_password_hash is empty (auth disabled).
    """
    if not _auth_enabled():
        return  # auth disabled — allow all

    if not credentials or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    username = verify_token(credentials.credentials)
    if not username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return username


# ─── Routes ───────────────────────────────────────────────────────────────────


@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest, request: Request):
    if not _auth_enabled():
        raise HTTPException(status_code=400, detail="Authentication is not configured")

    if not settings.secret_key:
        raise HTTPException(status_code=500, detail="SECRET_KEY not configured — cannot sign tokens")

    pwd_context = _get_pwd_context()
    safe_user = req.username.replace("\n", " ").replace("\r", " ")[:64]
    ip = request.client.host if request.client else "unknown"

    # Always run bcrypt regardless of username match so an unknown username and
    # a wrong password cost the attacker the same observable time. Otherwise a
    # ~100ms gap leaks "username exists" and turns rate-limited brute-force into
    # a tractable two-stage attack.
    user_ok = req.username == settings.auth_username
    pw_ok = pwd_context.verify(req.password, settings.auth_password_hash)
    if not (user_ok and pw_ok):
        reason = "unknown_user" if not user_ok else "bad_password"
        logger.warning(f"login_failed user={safe_user!r} reason={reason} ip={ip}")
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_access_token(req.username)
    logger.info(f"login_ok user={safe_user!r} ip={ip}")
    return TokenResponse(access_token=token)


@router.get("/ws-token")
async def get_ws_token(request: Request):
    """Issue a short-lived token for WebSocket connections.

    Reads the JWT from the httpOnly 'session' cookie (set by WebAuthn login)
    and returns a short-lived token the frontend can pass as a query param.
    Verifies the JTI is still active in the AuthSession table — a logged-out
    or revoked session must not be able to mint new WS tokens just because
    the underlying JWT has not expired yet.
    """
    if not _auth_enabled():
        return {"token": "__noauth__"}

    jwt_mod = _get_jwt()
    session_token = request.cookies.get("session")
    if not session_token:
        raise HTTPException(status_code=401, detail="No session cookie")

    payload = decode_token(session_token)
    if not payload or not payload.get("sub"):
        raise HTTPException(status_code=401, detail="Invalid session")

    jti = payload.get("jti")
    if jti:
        try:
            from sqlalchemy import select

            from app.db.models import AuthSession
            from app.db.session import async_session

            async with async_session() as db:
                result = await db.execute(
                    select(AuthSession.id).where(
                        AuthSession.jwt_jti == jti,
                        AuthSession.revoked_at.is_(None),
                    )
                )
                if result.scalar_one_or_none() is None:
                    raise HTTPException(status_code=401, detail="Session revoked")
        except HTTPException:
            raise
        except Exception as e:
            logger.warning(f"ws-token revocation check failed (deny by default): {e!r}")
            raise HTTPException(status_code=503, detail="session_check_unavailable") from e

    expire = datetime.now(UTC) + timedelta(seconds=30)
    ws_token = jwt_mod.encode(
        {"sub": payload["sub"], "exp": expire, "purpose": "ws"},
        settings.secret_key,
        algorithm=JWT_ALGORITHM,
    )
    return {"token": ws_token}


@router.get("/me")
async def get_current_user(username: str = Depends(require_auth)):
    if not _auth_enabled():
        return {"username": "anonymous", "auth_enabled": False}
    return {"username": username, "auth_enabled": True}
