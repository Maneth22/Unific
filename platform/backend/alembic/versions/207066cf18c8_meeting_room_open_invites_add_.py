"""meeting room open invites add participant

Adds the schema support for three Meeting Room features:
- persisted Meeting.meeting_kind (was previously only a transient
  schedule_meeting() parameter, never stored)
- a "kind" (personal | open) on MeetingInvite, with participant_id now
  nullable so a meeting-wide open/shareable invite isn't tied to one
  fixed MeetingParticipant, plus a partial unique index capping each
  meeting to at most one open invite
- MeetingParticipant.guest_name, for the guest rows an open-invite
  redemption creates, and a widened `one_actor` CHECK constraint
  covering that third case

Revision ID: 207066cf18c8
Revises: 68206eef95e5
Create Date: 2026-08-17 22:27:38.085376

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '207066cf18c8'
down_revision: Union[str, None] = '68206eef95e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

MEETING_INVITE_KIND = postgresql.ENUM('personal', 'open', name='meeting_invite_kind')


def upgrade() -> None:
    # meeting_kind: server_default matches schedule_meeting()'s own
    # existing default ("community"), so every pre-existing row (all
    # scheduled before this column existed, necessarily via a picker that
    # today always resolves to "community" or "client_org"/"staff" — none
    # of which are distinguishable after the fact) gets the safest,
    # least-restrictive value: "community" carries no add-participant
    # restriction, unlike "client_org".
    op.add_column(
        'meeting',
        sa.Column('meeting_kind', sa.String(20), nullable=False, server_default='community'),
        schema='meeting_room',
    )

    # MeetingInvite.kind + nullable participant_id + the "at most one open
    # invite per meeting" partial unique index. server_default='personal'
    # gives every pre-existing invite row its correct, unchanged meaning.
    MEETING_INVITE_KIND.create(op.get_bind(), checkfirst=True)
    op.add_column(
        'meeting_invite',
        sa.Column(
            'kind',
            postgresql.ENUM('personal', 'open', name='meeting_invite_kind', create_type=False),
            nullable=False,
            server_default='personal',
        ),
        schema='meeting_room',
    )
    op.alter_column('meeting_invite', 'participant_id', nullable=True, schema='meeting_room')
    op.create_index(
        'uq_meeting_invite_open_per_meeting',
        'meeting_invite',
        ['meeting_id'],
        unique=True,
        schema='meeting_room',
        postgresql_where=sa.text("kind = 'open'"),
    )

    # MeetingParticipant.guest_name + widen one_actor from "exactly one of
    # identity_id/staff_user_id" to "exactly one of
    # identity_id/staff_user_id/guest_name". No existing row has
    # guest_name set, so every existing row still satisfies the new check
    # exactly as it satisfied the old one.
    op.add_column(
        'meeting_participant',
        sa.Column('guest_name', sa.String(200), nullable=True),
        schema='meeting_room',
    )
    # Actual constraint name on disk is naming-convention-prefixed (see
    # app/database.py's NAMING_CONVENTION: "ck": "ck_%(table_name)s_%(constraint_name)s").
    # op.drop_constraint() takes the literal on-disk name (no convention
    # applied), so the existing constraint must be dropped by its full
    # name — but op.create_check_constraint() DOES run the given name
    # through that same convention itself, so passing the already-prefixed
    # name there would double-prefix it. Bare 'one_actor' is correct here.
    op.drop_constraint('ck_meeting_participant_one_actor', 'meeting_participant', schema='meeting_room')
    op.create_check_constraint(
        'one_actor',
        'meeting_participant',
        "(CASE WHEN identity_id IS NOT NULL THEN 1 ELSE 0 END)"
        " + (CASE WHEN staff_user_id IS NOT NULL THEN 1 ELSE 0 END)"
        " + (CASE WHEN guest_name IS NOT NULL THEN 1 ELSE 0 END) = 1",
        schema='meeting_room',
    )


def downgrade() -> None:
    # NOTE: this downgrade will fail with a constraint violation if any
    # guest_name-only MeetingParticipant rows exist (the old two-column
    # one_actor check has no way to accept them) — same
    # downgrade-after-data-exists limitation as every other migration in
    # this repo; not something this revision special-cases.
    op.drop_constraint('ck_meeting_participant_one_actor', 'meeting_participant', schema='meeting_room')
    op.create_check_constraint(
        'one_actor',
        'meeting_participant',
        "(identity_id IS NOT NULL) != (staff_user_id IS NOT NULL)",
        schema='meeting_room',
    )
    op.drop_column('meeting_participant', 'guest_name', schema='meeting_room')

    op.drop_index('uq_meeting_invite_open_per_meeting', table_name='meeting_invite', schema='meeting_room')
    op.alter_column('meeting_invite', 'participant_id', nullable=False, schema='meeting_room')
    op.drop_column('meeting_invite', 'kind', schema='meeting_room')
    MEETING_INVITE_KIND.drop(op.get_bind(), checkfirst=True)

    op.drop_column('meeting', 'meeting_kind', schema='meeting_room')
