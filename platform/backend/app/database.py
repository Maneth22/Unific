"""Async SQLAlchemy engine/session.

One physical database, four schemas (`core`, `accounts`, `profiles`,
`meeting_room`) — the room boundary is a Postgres schema, not a separate
database, so cross-schema services (the gate, the ledger, the calendar)
can run in a single transaction. Every model sets its schema explicitly
via `__table_args__`; nothing relies on a default search_path.
"""
from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from decimal import Decimal

from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


def _json_default(value):
    """Lets JSONB columns (e.g. core.audit_log.before/after) hold a
    Decimal — common here since permission/ledger fields are Numeric —
    without every call site having to remember to stringify it first."""
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _json_serializer(value) -> str:
    return json.dumps(value, default=_json_default)

# Consistent constraint naming so Alembic autogenerate produces stable,
# diffable migration names across all four schemas.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


SCHEMAS = ("core", "accounts", "profiles", "meeting_room")

engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_pre_ping=True,
    future=True,
    json_serializer=_json_serializer,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
