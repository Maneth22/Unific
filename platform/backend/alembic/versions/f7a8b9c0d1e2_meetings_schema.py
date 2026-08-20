"""meetings schema

Adds the `meetings` schema (meeting, meeting_participant, meeting_invite)
— UNIFIC v2's new meetings pipeline, bound to `orgs.Org`/`orgs.Member`/
`orgs.OrgUser` instead of the old `profiles.Identity` tree. Additive
alongside the untouched `meeting_room` schema — no dual-routing needed,
since each LiveKit meeting has its own dynamically generated `room_name`
with zero physical-resource collision.

Enum type names are `meetings_`-prefixed
(`meetings_meeting_status`/`meetings_meeting_invite_kind`) to avoid a
Postgres-global collision with `meeting_room`'s existing `meeting_status`/
`meeting_invite_kind` types — confirmed both live in `public` and enum
types are database-global, not schema-scoped (same class of check
`d5e6f7a8b9c0`'s migration already did for `conversation_status`).

Revision ID: f7a8b9c0d1e2
Revises: e6f7a8b9c0d1
Create Date: 2026-08-20 16:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'f7a8b9c0d1e2'
down_revision: Union[str, None] = 'e6f7a8b9c0d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS meetings")
    op.execute("ALTER TYPE public.room_name ADD VALUE IF NOT EXISTS 'meetings'")

    meeting_status = sa.Enum('scheduled', 'live', 'completed', 'cancelled', name='meetings_meeting_status')
    meeting_invite_kind = sa.Enum('personal', 'open', name='meetings_meeting_invite_kind')

    op.create_table(
        'meeting',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('org_id', sa.String(), nullable=True),
        sa.Column('scheduled_at', sa.DateTime(), nullable=False),
        sa.Column('translate_live', sa.Boolean(), nullable=False),
        sa.Column('translate_languages', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('status', meeting_status, nullable=False),
        sa.Column('notes', sa.Text(), nullable=False),
        sa.Column('created_by_staff_id', sa.String(), nullable=True),
        sa.Column('created_by_org_user_id', sa.String(), nullable=True),
        sa.Column('room_name', sa.String(length=80), nullable=False),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('ended_at', sa.DateTime(), nullable=True),
        sa.Column('translation_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['orgs.org.id'], name=op.f('fk_meeting_org_id_org'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by_staff_id'], ['core.staff_user.id'], name=op.f('fk_meeting_created_by_staff_id_staff_user'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['created_by_org_user_id'], ['orgs.org_user.id'], name=op.f('fk_meeting_created_by_org_user_id_org_user'), ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_meeting')),
        sa.UniqueConstraint('room_name', name=op.f('uq_meeting_room_name')),
        schema='meetings',
    )
    op.create_index(op.f('ix_meeting_org_id'), 'meeting', ['org_id'], schema='meetings')

    op.create_table(
        'meeting_participant',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('meeting_id', sa.String(), nullable=False),
        sa.Column('member_id', sa.String(), nullable=True),
        sa.Column('org_user_id', sa.String(), nullable=True),
        sa.Column('staff_user_id', sa.String(), nullable=True),
        sa.Column('guest_name', sa.String(length=200), nullable=True),
        sa.Column('joined_at', sa.DateTime(), nullable=True),
        sa.Column('left_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "(CASE WHEN member_id IS NOT NULL THEN 1 ELSE 0 END)"
            " + (CASE WHEN org_user_id IS NOT NULL THEN 1 ELSE 0 END)"
            " + (CASE WHEN staff_user_id IS NOT NULL THEN 1 ELSE 0 END)"
            " + (CASE WHEN guest_name IS NOT NULL THEN 1 ELSE 0 END) = 1",
            name=op.f('ck_meeting_participant_one_actor'),
        ),
        sa.ForeignKeyConstraint(['meeting_id'], ['meetings.meeting.id'], name=op.f('fk_meeting_participant_meeting_id_meeting'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['member_id'], ['orgs.member.id'], name=op.f('fk_meeting_participant_member_id_member'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['org_user_id'], ['orgs.org_user.id'], name=op.f('fk_meeting_participant_org_user_id_org_user'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['staff_user_id'], ['core.staff_user.id'], name=op.f('fk_meeting_participant_staff_user_id_staff_user'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_meeting_participant')),
        schema='meetings',
    )
    op.create_index(op.f('ix_meeting_participant_meeting_id'), 'meeting_participant', ['meeting_id'], schema='meetings')
    op.create_index('uq_meetings_participant_member', 'meeting_participant', ['meeting_id', 'member_id'], unique=True, schema='meetings', postgresql_where=sa.text('member_id IS NOT NULL'))
    op.create_index('uq_meetings_participant_org_user', 'meeting_participant', ['meeting_id', 'org_user_id'], unique=True, schema='meetings', postgresql_where=sa.text('org_user_id IS NOT NULL'))
    op.create_index('uq_meetings_participant_staff', 'meeting_participant', ['meeting_id', 'staff_user_id'], unique=True, schema='meetings', postgresql_where=sa.text('staff_user_id IS NOT NULL'))

    op.create_table(
        'meeting_invite',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('meeting_id', sa.String(), nullable=False),
        sa.Column('kind', meeting_invite_kind, nullable=False),
        sa.Column('participant_id', sa.String(), nullable=True),
        sa.Column('token', sa.String(length=64), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('revoked_at', sa.DateTime(), nullable=True),
        sa.Column('used_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['meeting_id'], ['meetings.meeting.id'], name=op.f('fk_meeting_invite_meeting_id_meeting'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['participant_id'], ['meetings.meeting_participant.id'], name=op.f('fk_meeting_invite_participant_id_meeting_participant'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_meeting_invite')),
        sa.UniqueConstraint('participant_id', name=op.f('uq_meeting_invite_participant_id')),
        sa.UniqueConstraint('token', name=op.f('uq_meeting_invite_token')),
        schema='meetings',
    )
    op.create_index(op.f('ix_meeting_invite_meeting_id'), 'meeting_invite', ['meeting_id'], schema='meetings')
    op.create_index(op.f('ix_meeting_invite_token'), 'meeting_invite', ['token'], schema='meetings')
    op.create_index('uq_meetings_invite_open_per_meeting', 'meeting_invite', ['meeting_id'], unique=True, schema='meetings', postgresql_where=sa.text("kind = 'open'"))


def downgrade() -> None:
    op.drop_table('meeting_invite', schema='meetings')
    op.drop_table('meeting_participant', schema='meetings')
    op.drop_table('meeting', schema='meetings')
    op.execute("DROP SCHEMA IF EXISTS meetings")
    sa.Enum(name='meetings_meeting_invite_kind').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='meetings_meeting_status').drop(op.get_bind(), checkfirst=True)
    # Postgres has no `ALTER TYPE ... DROP VALUE` — the 'meetings' room_name
    # label is left in place on downgrade, same precedent as prior migrations.
