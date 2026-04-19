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


def _get_jwt():
    global _jwt_module
    if _jwt_module is None:
        try:
            from jose import jwt

            _jwt_module = jwt
        except ImportError as e:
            raise HTTPException(
                status_code=500,
                detail="python-jose not installed. Run: pip install python-jose[cryptography]",
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
    # Empty SECRET_KEY produces trivially-forgeable JWTs: python-jose accepts
    # an empty HMAC key. Refuse to start when any JWT-issuing path is live.
    if _auth_enabled() and not settings.secret_key:
        raise RuntimeError(
            "SECRET_KEY is empty while auth is enabled — refusing to start. Set SECRET_KEY to a long random value."
        )
    _PLACEHOLDERS = {"change-me-in-production", "changeme", "secret", "please-change"}
    if settings.secret_key.strip().lower() in _PLACEHOLDERS:
        raise RuntimeError("SECRET_KEY is set to a placeholder value — refusing to start. Generate a real secret.")


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
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def mint_internal_token() -> str:
    """Long-lived JWT (90 days) for internal MCP tools → backend API calls.

    Empty string when auth disabled.
    """
    if not _auth_enabled() or not settings.secret_key:
        return ""
    return create_access_token("internal_agent", expire_hours=90 * 24)


def verify_token(token: str) -> str | None:
    """Verify JWT and return username, or None if invalid."""
    jwt = _get_jwt()
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
        return payload.get("sub")
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
    # Strip newlines to blunt log injection via username field.
    safe_user = req.username.replace("\n", " ").replace("\r", " ")[:64]
    ip = request.client.host if request.client else "unknown"

    if req.username != settings.auth_username:
        logger.warning(f"login_failed user={safe_user!r} reason=unknown_user ip={ip}")
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not pwd_context.verify(req.password, settings.auth_password_hash):
        logger.warning(f"login_failed user={safe_user!r} reason=bad_password ip={ip}")
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_access_token(req.username)
    logger.info(f"login_ok user={safe_user!r} ip={ip}")
    return TokenResponse(access_token=token)


@router.get("/ws-token")
async def get_ws_token(request: Request):
    """Issue a short-lived token for WebSocket connections.

    Reads the JWT from the httpOnly 'session' cookie (set by WebAuthn login)
    and returns a short-lived token the frontend can pass as a query param.
    """
    if not _auth_enabled():
        return {"token": "__noauth__"}

    jwt_mod = _get_jwt()
    session_token = request.cookies.get("session")
    if not session_token:
        raise HTTPException(status_code=401, detail="No session cookie")

    username = verify_token(session_token)
    if not username:
        raise HTTPException(status_code=401, detail="Invalid session")

    # Short-lived token (30 seconds) for WS handshake only
    expire = datetime.now(UTC) + timedelta(seconds=30)
    ws_token = jwt_mod.encode(
        {"sub": username, "exp": expire, "purpose": "ws"},
        settings.secret_key,
        algorithm="HS256",
    )
    return {"token": ws_token}


@router.get("/me")
async def get_current_user(username: str = Depends(require_auth)):
    if not _auth_enabled():
        return {"username": "anonymous", "auth_enabled": False}
    return {"username": username, "auth_enabled": True}
