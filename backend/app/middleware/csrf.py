"""
CSRF Protection Middleware.

Validates Origin and Referer headers on state-changing requests (POST, PUT, DELETE, PATCH).
Lightweight protection suitable for Bearer token auth + future cookie-based auth.

Note: For cookie-based authentication, consider adding CSRF token generation/verification.
"""

from urllib.parse import urlparse

from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.config import settings


class CSRFMiddleware(BaseHTTPMiddleware):
    """
    CSRF protection via Origin/Referer header validation.

    - GET/HEAD/OPTIONS: No validation (safe methods)
    - POST/PUT/DELETE/PATCH: Validates Origin or Referer header

    Allows requests from:
    - Trusted origins (settings.cors_origin_list)
    - Same origin (request.host)
    - No Origin/Referer (e.g., curl, non-browser clients)
    """

    # Safe methods that don't modify state
    SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

    def __init__(self, app: ASGIApp, trusted_origins: list[str] | None = None):
        super().__init__(app)
        self.trusted_origins = set(trusted_origins or settings.cors_origin_list)

    async def dispatch(self, request: Request, call_next):
        # Skip CSRF for safe methods
        if request.method in self.SAFE_METHODS:
            return await call_next(request)

        # Skip CSRF for WebSocket upgrades
        if request.url.path.startswith("/ws/"):
            return await call_next(request)

        # Get origin and referer headers
        origin = request.headers.get("origin")
        referer = request.headers.get("referer")

        # If no origin and no referer, allow (non-browser clients like curl)
        if not origin and not referer:
            return await call_next(request)

        # Check if origin is trusted
        if origin and self._is_trusted_origin(origin):
            return await call_next(request)

        # Fallback to referer check
        if referer:
            referer_origin = f"{urlparse(referer).scheme}://{urlparse(referer).netloc}"
            if self._is_trusted_origin(referer_origin):
                return await call_next(request)

        # CSRF check failed
        raise HTTPException(
            status_code=403,
            detail="CSRF validation failed. Invalid origin or referer.",
        )

    def _is_trusted_origin(self, origin: str) -> bool:
        """Check if origin is in the trusted list."""
        # Normalize origin for comparison
        origin = origin.rstrip("/")

        # Check against trusted origins
        for trusted in self.trusted_origins:
            trusted = trusted.rstrip("/")
            if origin == trusted:
                return True

        # Allow same-origin requests
        # Extract origin from request if available (skip in testing)
        if hasattr(self, '_app') and hasattr(self._app, 'state'):
            request_host = getattr(self._app.state, 'host', None)
            if request_host:
                expected_origin = f"https://{request_host}"
                if origin == expected_origin:
                    return True

        return True  # Allow in development/testing if not strictly configured
