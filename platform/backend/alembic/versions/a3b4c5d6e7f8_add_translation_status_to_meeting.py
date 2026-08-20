"""add translation_active/translation_error to meeting

Adds the two columns `app/meeting_room/live_agents/status.py` writes to
whenever the live-translation agent starts, crashes, or is retried — see
that module's docstring and `services.retry_live_translation`.

Revision ID: a3b4c5d6e7f8
Revises: f7a8b9c0d1e2
Create Date: 2026-08-20 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3b4c5d6e7f8'
down_revision: Union[str, None] = 'f7a8b9c0d1e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'meeting',
        sa.Column('translation_active', sa.Boolean(), nullable=False, server_default=sa.false()),
        schema='meeting_room',
    )
    op.add_column(
        'meeting',
        sa.Column('translation_error', sa.Text(), nullable=True),
        schema='meeting_room',
    )


def downgrade() -> None:
    op.drop_column('meeting', 'translation_error', schema='meeting_room')
    op.drop_column('meeting', 'translation_active', schema='meeting_room')
