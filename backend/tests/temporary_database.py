from asyncio import run
from os import environ
from pathlib import Path
from typing import Any
from uuid import uuid4

from alembic.command import upgrade
from alembic.config import Config as AlembicConfig
from asyncpg import connect
from sqlalchemy.engine import URL, make_url

ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"


class TemporaryDatabase:
    """A uniquely named Postgres database for one test run, dropped afterwards.

    `use_for_tests()` must run before `config` is imported, so it can point
    DATABASE_URL at the new name; `create()` and `drop()` run in a fixture.
    """

    def __init__(self, base_database_url: str) -> None:
        base = make_url(f"postgresql+asyncpg://{base_database_url}")
        self.url: URL = base.set(database=f"tierforge_test_{uuid4().hex[:8]}")

    @classmethod
    def use_for_tests(cls) -> "TemporaryDatabase":
        database = cls(environ["DATABASE_URL"])
        rendered = database.url.render_as_string(hide_password=False)
        environ["DATABASE_URL"] = rendered.split("://", 1)[1]
        return database

    @property
    def name(self) -> str:
        return self.url.database

    def create(self) -> None:
        run(self._execute(f'CREATE DATABASE "{self.name}"'))

    def drop(self) -> None:
        run(self._execute(f'DROP DATABASE IF EXISTS "{self.name}" WITH (FORCE)'))

    @staticmethod
    def alembic_config() -> AlembicConfig:
        """The project's Alembic config, leaving the test suite's logging alone."""
        alembic_config = AlembicConfig(str(ALEMBIC_INI))
        alembic_config.attributes["configure_logger"] = False
        return alembic_config

    def migrate(self) -> None:
        """Apply every Alembic migration, exactly as `poe db_upgrade` does."""
        upgrade(self.alembic_config(), "head")

    def fetch_value(self, query: str, *args: Any) -> Any:
        """Run a read query against this database (for assertions in tests)."""
        return run(self._fetch_value(query, *args))

    async def _connect(self, database: str):
        return await connect(
            host=self.url.host,
            port=self.url.port or 5432,
            user=self.url.username,
            password=self.url.password,
            database=database,
        )

    async def _execute(self, statement: str) -> None:
        conn = await self._connect("postgres")
        try:
            await conn.execute(statement)
        finally:
            await conn.close()

    async def _fetch_value(self, query: str, *args: Any) -> Any:
        conn = await self._connect(self.name)
        try:
            return await conn.fetchval(query, *args)
        finally:
            await conn.close()
