from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings


def _build_engine_kwargs() -> dict:
    """
    Build engine kwargs. When routing through PgBouncer in transaction mode,
    asyncpg prepared statement caching must be disabled (cache is per-connection
    and cannot be shared across pooled connections in transaction mode).
    """
    kwargs: dict = {
        "echo": False,
        "pool_size": settings.db_pool_size,
        "max_overflow": settings.db_max_overflow,
        "pool_timeout": settings.db_pool_timeout,
        "pool_recycle": settings.db_pool_recycle,
        "pool_pre_ping": True,
    }
    if settings.db_pgbouncer_mode:
        # Disable asyncpg statement cache; SQLAlchemy picks this up via connect_args
        kwargs["connect_args"] = {
            "statement_cache_size": 0,
            "prepared_statement_cache_size": 0,
        }
    return kwargs


engine = create_async_engine(settings.database_url, **_build_engine_kwargs())
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db():
    async with async_session() as session:
        yield session


@asynccontextmanager
async def transaction(*, auto_commit: bool = True) -> AsyncIterator[AsyncSession]:
    """Open an isolated session, commit on success, roll back on error.

    Replaces the repeated ``async with async_session() as session: ... commit/rollback``
    boilerplate. ``auto_commit=False`` lets the caller stage work and commit
    explicitly while still getting rollback-on-exception.
    """
    async with async_session() as session:
        try:
            yield session
            if auto_commit:
                await session.commit()
        except Exception:
            await safe_rollback(session, "transaction")
            raise


async def safe_rollback(session: AsyncSession, context: str) -> None:
    """Best-effort rollback that surfaces failures instead of swallowing them.

    Used at fallback paths where a primary operation already failed; if the
    rollback itself raises, observability matters more than re-raising over the
    original error.
    """
    try:
        await session.rollback()
    except Exception as rb_err:
        logger.error(f"rollback_failed context={context!r}: {rb_err!r}")


async def get_secret_or_none(session: AsyncSession, key: str):
    """Lookup an active Secret row by key. Returns None when missing.

    Centralizes the ``WHERE key=? AND is_deleted=false`` filter so callers can
    not accidentally match a soft-deleted row (the bug that pushed a stale
    webhook key into the validator).
    """
    from sqlalchemy import select

    from app.db.models import Secret

    result = await session.execute(
        select(Secret).where(Secret.key == key, Secret.is_deleted.is_(False))
    )
    return result.scalar_one_or_none()


def defer_model_binary():
    """Defer the LargeBinary ``MLModelLog.model_binary`` blob.

    Used by metadata-only reads (status, drift, list) so a 10–50 MB model
    payload is not loaded just to read accuracy / created_at fields.
    """
    from sqlalchemy.orm import defer

    from app.db.models import MLModelLog

    return defer(MLModelLog.model_binary)
