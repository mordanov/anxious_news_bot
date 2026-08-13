from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime

from sqlalchemy import DateTime, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
        onupdate=lambda: datetime.now().astimezone(),
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

    async def __aenter__(self) -> Database:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()
