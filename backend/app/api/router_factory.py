"""Shared router constructor — applies auth uniformly so a new file does not
forget the dependency.

A bare ``APIRouter()`` ships endpoints unauthenticated by default. We have been
bitten by that twice (strategy.py, /health/pool). Routers that should require
auth must use :func:`make_authed_router` so the dependency is attached at the
router level, not opt-in per endpoint.
"""

from fastapi import APIRouter, Depends

from app.auth import require_auth


def make_authed_router(prefix: str, tags: list[str]) -> APIRouter:
    return APIRouter(prefix=prefix, tags=tags, dependencies=[Depends(require_auth)])
