from __future__ import annotations

from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


class Database:
    def __init__(
        self,
        database_url: str,
        *,
        echo: bool = False,
        pool_pre_ping: bool = True,
    ) -> None:
        self._engine = create_async_engine(
            database_url,
            echo=echo,
            pool_pre_ping=pool_pre_ping,
        )
        self._sessions = async_sessionmaker(
            self._engine,
            expire_on_commit=False,
            autoflush=False,
        )
        self._closed = False

    @property
    def engine(self) -> AsyncEngine:
        return self._engine

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        if self._closed:
            raise RuntimeError("database is closed")
        async with self._sessions() as session:
            try:
                async with session.begin():
                    yield session
            except BaseException:
                await session.rollback()
                raise

    async def close(self) -> None:
        if not self._closed:
            self._closed = True
            await self._engine.dispose()

    async def __aenter__(self) -> "Database":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()
