"""meeting chat message

Adds meeting_room.meeting_chat_message — persisted in-call chat history
(original text + lazily-accumulated per-language translations) for the
new LiveKit Agents chat relay (app.meeting_room.live_agents.chat_relay).

Revision ID: c3264277df18
Revises: 207066cf18c8
Create Date: 2026-08-18 00:21:09.738324

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'c3264277df18'
down_revision: Union[str, None] = '207066cf18c8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'meeting_chat_message',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('meeting_id', sa.String(), nullable=False),
        sa.Column('message_id', sa.String(length=64), nullable=False),
        sa.Column('sender_identity', sa.String(length=200), nullable=False),
        sa.Column('original_text', sa.Text(), nullable=False),
        sa.Column('source_language', sa.String(length=20), nullable=False),
        sa.Column('translations', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='{}'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['meeting_id'], ['meeting_room.meeting.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        schema='meeting_room',
    )
    op.create_index(
        op.f('ix_meeting_room_meeting_chat_message_meeting_id'),
        'meeting_chat_message', ['meeting_id'], unique=False, schema='meeting_room',
    )
    op.create_index(
        op.f('ix_meeting_room_meeting_chat_message_created_at'),
        'meeting_chat_message', ['created_at'], unique=False, schema='meeting_room',
    )
    # Idempotency key: a retried/duplicate relay of the same client-generated
    # message_id must not double-persist within one meeting.
    op.create_index(
        'uq_meeting_chat_message_id',
        'meeting_chat_message', ['meeting_id', 'message_id'], unique=True, schema='meeting_room',
    )


def downgrade() -> None:
    op.drop_index('uq_meeting_chat_message_id', table_name='meeting_chat_message', schema='meeting_room')
    op.drop_index(
        op.f('ix_meeting_room_meeting_chat_message_created_at'),
        table_name='meeting_chat_message', schema='meeting_room',
    )
    op.drop_index(
        op.f('ix_meeting_room_meeting_chat_message_meeting_id'),
        table_name='meeting_chat_message', schema='meeting_room',
    )
    op.drop_table('meeting_chat_message', schema='meeting_room')
