from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from logging import getLogger
from typing import Annotated, TypeAlias

from fastapi import Depends
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from api.exceptions import AppError
from config import cfg

logger = getLogger(__name__)


class DBSession:
    engine: AsyncEngine | None = None
    session_maker: async_sessionmaker[AsyncSession] | None = None

    @classmethod
    def create(cls) -> None:
        cls.engine = create_async_engine(
            url=cfg.db.async_url, echo=cfg.db.echo_sql, pool_pre_ping=True
        )
        cls.session_maker = async_sessionmaker(cls.engine, expire_on_commit=False)

    @classmethod
    async def session(cls) -> AsyncGenerator[AsyncSession, None]:
        """FastAPI dependency: one session per request."""
        async with cls.context() as session:
            yield session

    @classmethod
    @asynccontextmanager
    async def context(cls) -> AsyncIterator[AsyncSession]:
        """Commits on success and rolls back on error. Usable outside FastAPI."""
        if cls.session_maker is None:
            raise RuntimeError("DBSession is not initialised; call create() first")

        async with cls.session_maker() as session:
            try:
                yield session
                await session.commit()
            except AppError:
                # Expected client error (e.g. a rejected upload): undo, no traceback.
                await session.rollback()
                raise
            except Exception as e:
                logger.warning("Exception on query", exc_info=e)
                await session.rollback()
                raise

    @classmethod
    async def close(cls) -> None:
        if cls.engine:
            await cls.engine.dispose()
            cls.engine = None
            cls.session_maker = None


DbSessionDep: TypeAlias = Annotated[AsyncSession, Depends(DBSession.session)]
