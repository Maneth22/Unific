"""orgs schema and agent_run_log

Adds the `orgs` schema (org, group, org_user, member,
org_registration_request, group_invite, code_sequence) — UNIFIC v2's flat
Org -> Group -> Member replacement for the old `accounts`+`profiles`
identity tree + cascading permission model (see docs/adr/0003). Also adds
`core.agent_run_log` (table only — no call sites write to it yet, see
docs/PHASE_1_NOTES.md).

This migration is purely additive: it does not touch, repoint, or drop
any existing `core`/`accounts`/`profiles`/`meeting_room`/`tasking` table
or FK. The new `orgs` schema and its auth system run alongside the
untouched legacy `accounts`/`profiles` system until later phases rebuild
WhatsApp/Meeting Room against it.

Revision ID: c4d5e6f7a8b9
Revises: b2c3d4e5f6a7
Create Date: 2026-08-20 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4d5e6f7a8b9'
down_revision: Union[str, None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS orgs")

    # New enum labels on two existing public-schema enum types — confirmed
    # live (both room_name and actor_type live in `public`, not `core`).
    # ADD VALUE cannot run inside the same transaction that uses the new
    # label, which is fine here since nothing in this migration inserts a
    # row using 'orgs'/'org_user' yet.
    op.execute("ALTER TYPE public.room_name ADD VALUE IF NOT EXISTS 'orgs'")
    op.execute("ALTER TYPE public.actor_type ADD VALUE IF NOT EXISTS 'org_user'")

    org_registration_status = sa.Enum('pending', 'approved', 'rejected', name='org_registration_status')
    org_user_role = sa.Enum('owner', 'staff', name='org_user_role')
    agent_run_status = sa.Enum('success', 'error', 'timeout', name='agent_run_status')

    op.create_table(
        'code_sequence',
        sa.Column('prefix', sa.String(length=16), nullable=False),
        sa.Column('next_value', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('prefix', name=op.f('pk_code_sequence')),
        schema='orgs',
    )

    op.create_table(
        'org',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('group_code', sa.String(length=32), nullable=False),
        sa.Column('entity_type', sa.String(length=255), nullable=False),
        sa.Column('role_description', sa.Text(), nullable=False),
        sa.Column('abn_acnc_number', sa.String(length=64), nullable=True),
        sa.Column('balance', sa.Numeric(18, 6), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_org')),
        sa.UniqueConstraint('group_code', name=op.f('uq_org_group_code')),
        schema='orgs',
    )

    op.create_table(
        'group',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('org_id', sa.String(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('group_code', sa.String(length=32), nullable=False),
        sa.Column('name_hindi', sa.String(length=255), nullable=False),
        sa.Column('registration_number', sa.String(length=100), nullable=False),
        sa.Column('date_of_registration', sa.Date(), nullable=True),
        sa.Column('application_signed', sa.Boolean(), nullable=False),
        sa.Column('registered_office', sa.Text(), nullable=False),
        sa.Column('area_of_operation', sa.Text(), nullable=False),
        sa.Column('governing_act', sa.String(length=255), nullable=False),
        sa.Column('registering_authority', sa.String(length=255), nullable=False),
        sa.Column('objective', sa.Text(), nullable=False),
        sa.Column('cooperative_type', sa.String(length=255), nullable=False),
        sa.Column('bank_account', sa.String(length=100), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['orgs.org.id'], name=op.f('fk_group_org_id_org'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_group')),
        sa.UniqueConstraint('group_code', name=op.f('uq_group_group_code')),
        schema='orgs',
    )
    op.create_index(op.f('ix_group_org_id'), 'group', ['org_id'], schema='orgs')

    op.create_table(
        'org_user',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('org_id', sa.String(), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('password_hash', sa.String(length=255), nullable=False),
        sa.Column('full_name', sa.String(length=255), nullable=False),
        sa.Column('role', org_user_role, nullable=False),
        sa.Column('created_by_staff_id', sa.String(), nullable=True),
        sa.Column('created_by_org_user_id', sa.String(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['orgs.org.id'], name=op.f('fk_org_user_org_id_org'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(
            ['created_by_staff_id'], ['core.staff_user.id'], name=op.f('fk_org_user_created_by_staff_id_staff_user'), ondelete='SET NULL'
        ),
        sa.ForeignKeyConstraint(
            ['created_by_org_user_id'], ['orgs.org_user.id'], name=op.f('fk_org_user_created_by_org_user_id_org_user'), ondelete='SET NULL'
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_org_user')),
        sa.UniqueConstraint('email', name=op.f('uq_org_user_email')),
        schema='orgs',
    )
    op.create_index(op.f('ix_org_user_org_id'), 'org_user', ['org_id'], schema='orgs')
    op.create_index(op.f('ix_org_user_email'), 'org_user', ['email'], schema='orgs')

    op.create_table(
        'member',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('org_id', sa.String(), nullable=False),
        sa.Column('group_id', sa.String(), nullable=True),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['orgs.org.id'], name=op.f('fk_member_org_id_org'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['group_id'], ['orgs.group.id'], name=op.f('fk_member_group_id_group'), ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_member')),
        schema='orgs',
    )
    op.create_index(op.f('ix_member_org_id'), 'member', ['org_id'], schema='orgs')
    op.create_index(op.f('ix_member_group_id'), 'member', ['group_id'], schema='orgs')

    op.create_table(
        'org_registration_request',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('org_name', sa.String(length=255), nullable=False),
        sa.Column('contact_name', sa.String(length=255), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('password_hash', sa.String(length=255), nullable=False),
        sa.Column('status', org_registration_status, nullable=False),
        sa.Column('rejection_reason', sa.Text(), nullable=False),
        sa.Column('reviewed_by', sa.String(), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(), nullable=True),
        sa.Column('created_org_id', sa.String(), nullable=True),
        sa.Column('created_org_user_id', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ['reviewed_by'], ['core.staff_user.id'], name=op.f('fk_org_registration_request_reviewed_by_staff_user'), ondelete='SET NULL'
        ),
        sa.ForeignKeyConstraint(
            ['created_org_id'], ['orgs.org.id'], name=op.f('fk_org_registration_request_created_org_id_org'), ondelete='SET NULL'
        ),
        sa.ForeignKeyConstraint(
            ['created_org_user_id'], ['orgs.org_user.id'],
            name=op.f('fk_org_registration_request_created_org_user_id_org_user'), ondelete='SET NULL',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_org_registration_request')),
        schema='orgs',
    )
    op.create_index(op.f('ix_org_registration_request_email'), 'org_registration_request', ['email'], schema='orgs')

    op.create_table(
        'group_invite',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('org_id', sa.String(), nullable=False),
        sa.Column('group_id', sa.String(), nullable=True),
        sa.Column('token', sa.String(length=64), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_by_org_user_id', sa.String(), nullable=True),
        sa.Column('created_by_staff_id', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['orgs.org.id'], name=op.f('fk_group_invite_org_id_org'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['group_id'], ['orgs.group.id'], name=op.f('fk_group_invite_group_id_group'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(
            ['created_by_org_user_id'], ['orgs.org_user.id'], name=op.f('fk_group_invite_created_by_org_user_id_org_user'), ondelete='SET NULL'
        ),
        sa.ForeignKeyConstraint(
            ['created_by_staff_id'], ['core.staff_user.id'], name=op.f('fk_group_invite_created_by_staff_id_staff_user'), ondelete='SET NULL'
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_group_invite')),
        sa.UniqueConstraint('token', name=op.f('uq_group_invite_token')),
        schema='orgs',
    )
    op.create_index(op.f('ix_group_invite_org_id'), 'group_invite', ['org_id'], schema='orgs')
    op.create_index(op.f('ix_group_invite_token'), 'group_invite', ['token'], schema='orgs')
    op.create_index(
        'uq_group_invite_active_org_group', 'group_invite', ['org_id', 'group_id'],
        unique=True, schema='orgs', postgresql_where=sa.text('is_active'),
    )

    op.create_table(
        'agent_run_log',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('org_id', sa.String(), nullable=True),
        sa.Column('plugin_key', sa.String(length=100), nullable=False),
        sa.Column('action', sa.String(length=100), nullable=False),
        sa.Column('provider', sa.String(length=100), nullable=False),
        sa.Column('model', sa.String(length=100), nullable=False),
        sa.Column('prompt_template_id', sa.String(length=100), nullable=True),
        sa.Column('prompt_hash', sa.String(length=64), nullable=True),
        sa.Column('input_summary', sa.Text(), nullable=False),
        sa.Column('output_summary', sa.Text(), nullable=False),
        sa.Column('prompt_tokens', sa.Integer(), nullable=True),
        sa.Column('completion_tokens', sa.Integer(), nullable=True),
        sa.Column('estimated_cost', sa.Numeric(18, 6), nullable=True),
        sa.Column('latency_ms', sa.Integer(), nullable=True),
        sa.Column('status', agent_run_status, nullable=False),
        sa.Column('error_message', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['orgs.org.id'], name=op.f('fk_agent_run_log_org_id_org'), ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_agent_run_log')),
        schema='core',
    )
    op.create_index(op.f('ix_agent_run_log_org_id'), 'agent_run_log', ['org_id'], schema='core')
    op.create_index(op.f('ix_agent_run_log_created_at'), 'agent_run_log', ['created_at'], schema='core')
    op.create_index('ix_agent_run_log_org_created', 'agent_run_log', ['org_id', 'created_at'], schema='core')
    op.create_index('ix_agent_run_log_status_created', 'agent_run_log', ['status', 'created_at'], schema='core')

    op.add_column('refresh_token', sa.Column('org_user_id', sa.String(), nullable=True), schema='core')
    op.create_foreign_key(
        op.f('fk_refresh_token_org_user_id_org_user'), 'refresh_token', 'org_user',
        ['org_user_id'], ['id'], source_schema='core', referent_schema='orgs', ondelete='CASCADE',
    )
    op.create_index(op.f('ix_refresh_token_org_user_id'), 'refresh_token', ['org_user_id'], schema='core')


def downgrade() -> None:
    op.drop_index(op.f('ix_refresh_token_org_user_id'), table_name='refresh_token', schema='core')
    op.drop_constraint(op.f('fk_refresh_token_org_user_id_org_user'), 'refresh_token', schema='core', type_='foreignkey')
    op.drop_column('refresh_token', 'org_user_id', schema='core')

    op.drop_table('agent_run_log', schema='core')

    op.drop_index('uq_group_invite_active_org_group', table_name='group_invite', schema='orgs')
    op.drop_table('group_invite', schema='orgs')
    op.drop_table('org_registration_request', schema='orgs')
    op.drop_table('member', schema='orgs')
    op.drop_table('org_user', schema='orgs')
    op.drop_table('group', schema='orgs')
    op.drop_table('org', schema='orgs')
    op.drop_table('code_sequence', schema='orgs')

    op.execute("DROP SCHEMA IF EXISTS orgs")

    sa.Enum(name='agent_run_status').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='org_user_role').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='org_registration_status').drop(op.get_bind(), checkfirst=True)

    # Postgres has no `ALTER TYPE ... DROP VALUE` — the 'orgs' room_name
    # label and 'org_user' actor_type label are left in place on
    # downgrade. Harmless: nothing reads/writes them once the orgs schema
    # itself is gone.
