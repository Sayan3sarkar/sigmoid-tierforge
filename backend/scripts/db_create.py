"""Create the database named in DATABASE_URL if it doesn't exist yet.

Safe to run more than once.
"""

from asyncio import run

from asyncpg import connect
from sqlalchemy.engine import make_url

from config import cfg


async def main() -> None:
    url = make_url(cfg.db.async_url)
    conn = await connect(
        host=url.host,
        port=url.port or 5432,
        user=url.username,
        password=url.password,
        database="postgres",
    )
    try:
        exists = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", url.database
        )
        if exists:
            print(f"Database '{url.database}' already exists.")
        else:
            await conn.execute(f'CREATE DATABASE "{url.database}"')
            print(f"Created database '{url.database}'.")
    finally:
        await conn.close()


if __name__ == "__main__":
    run(main())
