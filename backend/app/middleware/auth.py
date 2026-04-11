"""
Global authentication middleware — enforces JWT cookie auth on all routes.

Backward compatible: if WebAuthn setup is not complete (no Owner with
is_setup_complete=True), all requests pass through unauthenticated.
This preserves existing behavior for deployments that haven't set up passkeys yet.
"""

from datetime import UTC, datetime

from loguru import logger
from sqlalchemy import select
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.config import settings
from app.db.models import AuthSession, Owner
from app.db.session import async_session

# Paths that never require authentication
EXCLUDED_PREFIXES = (
    "/health",
    "/api/auth/",
    "/docs",
    "/openapi.json",
    "/redoc",
)


def _verify_jwt(token: str) -> dict | None:
    """Verify JWT and return payload."""
    from jose import jwt
    try:
        return jwt.decode(token, settings.secret_key, algorithms=["HS256"])
    except Exception:
        return None


class AuthMiddleware(BaseHTTPMiddleware):
    """
    ASGI middleware that checks JWT session cookie on every request.

    - Excluded paths (health, auth, docs) pass through.
    - If WebAuthn setup not complete → pass through (backward compat).
    - Otherwise, requires valid non-revoked JWT in 'session' cookie.
    """

    # Cache setup status to avoid DB query on every request.
    # Reset when None (first request) or on 401 (owner may have just completed setup).
    _setup_complete: bool | None = None

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Allow excluded paths
        if any(path.startswith(prefix) for prefix in EXCLUDED_PREFIXES):
            return await call_next(request)

        # Allow WebSocket upgrades (they handle auth separately)
        if request.headers.get("upgrade", "").lower() == "websocket":
            return await call_next(request)

        # Check if WebAuthn setup is complete
        if not await self._is_setup_complete():
            return await call_next(request)

        # Extract JWT from cookie
        token = request.cookies.get("session")
        if not token:
            return JSONResponse(
                status_code=401,
                content={"detail": "Not authenticated"},
            )

        # Verify JWT
        payload = _verify_jwt(token)
        if not payload:
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or expired session"},
            )

        # Check session not revoked
        jti = payload.get("jti")
        if jti:
            async with async_session() as db:
                result = await db.execute(
                    select(AuthSession).where(
                        AuthSession.jwt_jti == jti,
                        AuthSession.revoked_at.is_(None),
                        AuthSession.expires_at > datetime.now(UTC),
                    )
                )
                session = result.scalar_one_or_none()
                if not session:
                    return JSONResponse(
                        status_code=401,
                        content={"detail": "Session revoked or expired"},
                    )

        # Attach owner info to request state
        request.state.owner_id = int(payload.get("sub", 0))

        return await call_next(request)

    async def _is_setup_complete(self) -> bool:
        """Check if WebAuthn setup is complete, with caching."""
        if AuthMiddleware._setup_complete is not None:
            return AuthMiddleware._setup_complete

        try:
            async with async_session() as db:
                result = await db.execute(select(Owner).limit(1))
                owner = result.scalar_one_or_none()
                AuthMiddleware._setup_complete = bool(
                    owner and owner.is_setup_complete
                )
        except Exception as e:
            logger.warning(f"Auth middleware: DB check failed ({e}), allowing request")
            return False

        return AuthMiddleware._setup_complete

    @classmethod
    def reset_cache(cls):
        """Reset the setup status cache (call after passkey registration)."""
        cls._setup_complete = None
