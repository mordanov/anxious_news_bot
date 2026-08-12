from __future__ import annotations

import os

import psycopg
from psycopg import sql


def required_environment(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def main() -> None:
    database_name = required_environment("APP_DATABASE_NAME")
    connection_options = {
        "host": required_environment("POSTGRES_HOST"),
        "port": int(required_environment("POSTGRES_PORT")),
        "user": required_environment("POSTGRES_USER"),
        "password": required_environment("POSTGRES_PASSWORD"),
        "dbname": required_environment("POSTGRES_ADMIN_DATABASE"),
        "autocommit": True,
    }

    with psycopg.connect(**connection_options) as connection:
        exists = connection.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s",
            (database_name,),
        ).fetchone()
        if exists:
            print(f"Database {database_name!r} already exists")
            return

        connection.execute(
            sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name))
        )
        print(f"Created database {database_name!r}")


if __name__ == "__main__":
    main()
