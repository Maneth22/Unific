"""create schemas and extensions

Revision ID: cb27bf973d3c
Revises: 
Create Date: 2026-07-10 00:37:18.246788

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'cb27bf973d3c'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # One schema per room boundary — core (Task 0 infrastructure, shared),
    # accounts (Task 1), profiles (Task 2), meeting_room (Task 3). Future
    # rooms (Task 4-8) each get their own schema the same way.
    op.execute("CREATE SCHEMA IF NOT EXISTS core")
    op.execute("CREATE SCHEMA IF NOT EXISTS accounts")
    op.execute("CREATE SCHEMA IF NOT EXISTS profiles")
    op.execute("CREATE SCHEMA IF NOT EXISTS meeting_room")
    # ltree powers O(log n) ancestor/descendant scope checks on the
    # Task 2 identity tree (Phase C) via a GiST index.
    op.execute("CREATE EXTENSION IF NOT EXISTS ltree")


def downgrade() -> None:
    op.execute("DROP SCHEMA IF EXISTS meeting_room CASCADE")
    op.execute("DROP SCHEMA IF EXISTS profiles CASCADE")
    op.execute("DROP SCHEMA IF EXISTS accounts CASCADE")
    op.execute("DROP SCHEMA IF EXISTS core CASCADE")
    op.execute("DROP EXTENSION IF EXISTS ltree")
