from __future__ import annotations

import os
from collections.abc import AsyncIterator
from uuid import uuid4

import psycopg
import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def _admin_url() -> str:
    return os.getenv(
        "TEST_POSTGRES_ADMIN_URL",
        "postgresql://postgres:postgres@localhost:5432/postgres",
    )


def _psycopg_url(value: str) -> str:
    url = make_url(value)
    if not url.drivername.startswith("postgresql"):
        raise ValueError("TEST_POSTGRES_ADMIN_URL must use PostgreSQL")
    return url.set(drivername="postgresql").render_as_string(hide_password=False)


@pytest.fixture(scope="session")
def postgres_database_url() -> str:
    database_name = f"anxious_news_test_{uuid4().hex}"
    try:
        with psycopg.connect(_psycopg_url(_admin_url()), autocommit=True) as connection:
            connection.execute(f'CREATE DATABASE "{database_name}"')
    except psycopg.Error as exc:
        pytest.skip(f"ephemeral PostgreSQL is unavailable: {exc}")

    admin = make_url(_admin_url()).set(
        drivername="postgresql+psycopg",
        database=database_name,
    )
    database_url = admin.render_as_string(hide_password=False)
    try:
        config = Config("alembic.ini")
        config.set_main_option("sqlalchemy.url", database_url)
        previous_url = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = database_url
        command.upgrade(config, "head")
        yield database_url
    finally:
        if previous_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous_url
        with psycopg.connect(_psycopg_url(_admin_url()), autocommit=True) as connection:
            connection.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (database_name,),
            )
            connection.execute(f'DROP DATABASE IF EXISTS "{database_name}"')


@pytest_asyncio.fixture
async def postgres_engine(
    postgres_database_url: str,
) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(
        postgres_database_url,
        pool_pre_ping=True,
    )
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def database_connection(
    postgres_engine: AsyncEngine,
) -> AsyncIterator[AsyncConnection]:
    async with postgres_engine.connect() as connection:
        transaction = await connection.begin()
        try:
            yield connection
        finally:
            await transaction.rollback()


@pytest_asyncio.fixture
async def database_session(
    database_connection: AsyncConnection,
) -> AsyncIterator[AsyncSession]:
    factory = async_sessionmaker(
        bind=database_connection,
        expire_on_commit=False,
    )
    async with factory() as session:
        yield session
        await session.rollback()
