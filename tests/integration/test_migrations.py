"""Alembic: the migration builds the schema the models describe, and downgrade removes it."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.models.domain_models import Base

ROOT = Path(__file__).resolve().parents[2]


def _alembic(database_url: str, *args: str) -> None:
    env = {**os.environ, "DATABASE_URL": database_url}
    result = subprocess.run(  # noqa: S603 - fixed arguments, no user input
        [sys.executable, "-m", "alembic", *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


async def _table_names(engine) -> set[str]:
    async with engine.connect() as conn:
        return await conn.run_sync(lambda c: set(sa.inspect(c).get_table_names()))


async def test_upgrade_creates_the_model_schema_and_downgrade_removes_it(postgres_url):
    engine = create_async_engine(postgres_url, poolclass=NullPool)
    try:
        async with engine.begin() as conn:  # start from an empty database
            await conn.run_sync(Base.metadata.drop_all)
            await conn.execute(sa.text("DROP TABLE IF EXISTS alembic_version"))

        _alembic(postgres_url, "upgrade", "head")
        assert set(Base.metadata.tables) <= await _table_names(engine)

        with pytest.raises(IntegrityError):  # a CHECK constraint made it into the database
            async with engine.begin() as conn:
                await conn.execute(
                    sa.text(
                        "INSERT INTO users (username, password_hash, balance) VALUES ('x', 'y', -1)"
                    )
                )

        _alembic(postgres_url, "downgrade", "base")
        assert not (set(Base.metadata.tables) & await _table_names(engine))
    finally:
        await engine.dispose()
