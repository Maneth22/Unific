"""meeting_room_add_member_summary_report_type

Revision ID: 454f67956d5c
Revises: 6d3da23a22a8
Create Date: 2026-07-13 21:21:51.914322

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '454f67956d5c'
down_revision: Union[str, None] = '6d3da23a22a8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Kept as its own migration/transaction: Postgres disallows using a
    # newly added enum value in the same transaction it was added in, so
    # this is isolated from anything that might insert a member_summary
    # row later.
    op.execute("ALTER TYPE report_type ADD VALUE 'member_summary'")


def downgrade() -> None:
    # Postgres has no DROP VALUE for enums — recreate the type without
    # member_summary and remap the column. Any existing member_summary
    # rows are impossible after this (there's no fourth value to fall
    # back to), so this will fail loudly on `session_report.report_type`
    # if any such row exists, which is the correct behavior rather than
    # silently corrupting data.
    op.execute("ALTER TYPE report_type RENAME TO report_type_old")
    op.execute("CREATE TYPE report_type AS ENUM ('session_summary', 'satisfaction_analysis')")
    op.execute(
        "ALTER TABLE meeting_room.session_report "
        "ALTER COLUMN report_type TYPE report_type "
        "USING report_type::text::report_type"
    )
    op.execute("DROP TYPE report_type_old")
