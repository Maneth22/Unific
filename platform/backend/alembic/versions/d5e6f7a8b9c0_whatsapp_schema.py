"""whatsapp schema

Adds the `whatsapp` schema (conversation, message, phone_link) — UNIFIC
v2's NEW WhatsApp pipeline, bound to `orgs.Member` instead of the old
`profiles.Identity` tree (see docs/adr/0003 and docs/PHASE_2_NOTES.md).
The webhook stays one physical endpoint that dual-routes: a phone number
found in `whatsapp.phone_link` goes to this new pipeline, everything else
falls through to the untouched old `meeting_room` pipeline.

Also adds `core.llm_usage_record.member_id` (+ CHECK) — the additive
widening ("Finding D") that lets the shared Gemini provider
implementations record usage against either principal, since
`identity_id`'s existing FK to `profiles.identity.id` would otherwise
raise on a `member.id` value.

`conversation_status`/`message_direction`/`reply_mode` are the SAME
Postgres enum types `meeting_room.conversation`/`message` already use
(confirmed via direct query: all three live in `public`, database-global
not schema-scoped) — referenced here with `create_type=False`, not
redeclared.

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-08-20 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'd5e6f7a8b9c0'
down_revision: Union[str, None] = 'c4d5e6f7a8b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS whatsapp")
    op.execute("ALTER TYPE public.room_name ADD VALUE IF NOT EXISTS 'whatsapp'")

    # room_name/message_direction/etc. already exist (created by earlier
    # migrations) — the generic sa.Enum(create_type=False) kwarg is
    # silently dropped (not a real attribute on that class), so this must
    # use the postgresql-dialect ENUM class, which actually honors it
    # (same pattern af8a0858664e_add_webhook_log_table.py already uses).
    conversation_status = postgresql.ENUM('active', 'archived', name='conversation_status', create_type=False)
    message_direction = postgresql.ENUM('inbound', 'outbound', name='message_direction', create_type=False)
    reply_mode = postgresql.ENUM('auto', 'manual', 'adaptive', name='reply_mode', create_type=False)

    op.create_table(
        'conversation',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('member_id', sa.String(), nullable=False),
        sa.Column('org_id', sa.String(), nullable=False),
        sa.Column('status', conversation_status, nullable=False),
        sa.Column('target_language', sa.String(length=50), nullable=False),
        sa.Column('tone', sa.String(length=50), nullable=False),
        sa.Column('character_name', sa.String(length=100), nullable=False),
        sa.Column('character_role', sa.String(length=200), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['member_id'], ['orgs.member.id'], name=op.f('fk_conversation_member_id_member'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['org_id'], ['orgs.org.id'], name=op.f('fk_conversation_org_id_org'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_conversation')),
        sa.UniqueConstraint('member_id', name=op.f('uq_conversation_member_id')),
        schema='whatsapp',
    )
    op.create_index(op.f('ix_conversation_member_id'), 'conversation', ['member_id'], schema='whatsapp')
    op.create_index(op.f('ix_conversation_org_id'), 'conversation', ['org_id'], schema='whatsapp')

    op.create_table(
        'message',
        sa.Column('id', sa.Integer(), nullable=False, autoincrement=True),
        sa.Column('conversation_id', sa.String(), nullable=False),
        sa.Column('direction', message_direction, nullable=False),
        sa.Column('mode', reply_mode, nullable=True),
        sa.Column('original_text', sa.Text(), nullable=False),
        sa.Column('detected_language', sa.String(length=20), nullable=False),
        sa.Column('translated_text', sa.Text(), nullable=False),
        sa.Column('final_text', sa.Text(), nullable=False),
        sa.Column('tone_analysis', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('key_points', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('sent_by_org_user_id', sa.String(), nullable=True),
        sa.Column('provider_message_id', sa.String(length=255), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ['conversation_id'], ['whatsapp.conversation.id'], name=op.f('fk_message_conversation_id_conversation'), ondelete='CASCADE'
        ),
        sa.ForeignKeyConstraint(
            ['sent_by_org_user_id'], ['orgs.org_user.id'], name=op.f('fk_message_sent_by_org_user_id_org_user'), ondelete='SET NULL'
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_message')),
        schema='whatsapp',
    )
    op.create_index(op.f('ix_message_conversation_id'), 'message', ['conversation_id'], schema='whatsapp')
    op.create_index(op.f('ix_message_created_at'), 'message', ['created_at'], schema='whatsapp')
    op.create_index(
        'uq_whatsapp_message_provider_message_id', 'message', ['provider_message_id'],
        unique=True, schema='whatsapp', postgresql_where=sa.text("provider_message_id != ''"),
    )

    op.create_table(
        'phone_link',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('phone_number', sa.String(length=32), nullable=False),
        sa.Column('member_id', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['member_id'], ['orgs.member.id'], name=op.f('fk_phone_link_member_id_member'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_phone_link')),
        sa.UniqueConstraint('phone_number', name=op.f('uq_phone_link_phone_number')),
        schema='whatsapp',
    )
    op.create_index(op.f('ix_phone_link_phone_number'), 'phone_link', ['phone_number'], schema='whatsapp')
    op.create_index(op.f('ix_phone_link_member_id'), 'phone_link', ['member_id'], schema='whatsapp')

    op.add_column('llm_usage_record', sa.Column('member_id', sa.String(), nullable=True), schema='core')
    op.create_foreign_key(
        op.f('fk_llm_usage_record_member_id_member'), 'llm_usage_record', 'member',
        ['member_id'], ['id'], source_schema='core', referent_schema='orgs', ondelete='SET NULL',
    )
    op.create_index(op.f('ix_llm_usage_record_member_id'), 'llm_usage_record', ['member_id'], schema='core')
    op.create_check_constraint(
        'ck_llm_usage_record_single_principal', 'llm_usage_record',
        'identity_id IS NULL OR member_id IS NULL', schema='core',
    )


def downgrade() -> None:
    op.drop_constraint('ck_llm_usage_record_single_principal', 'llm_usage_record', schema='core', type_='check')
    op.drop_index(op.f('ix_llm_usage_record_member_id'), table_name='llm_usage_record', schema='core')
    op.drop_constraint(op.f('fk_llm_usage_record_member_id_member'), 'llm_usage_record', schema='core', type_='foreignkey')
    op.drop_column('llm_usage_record', 'member_id', schema='core')

    op.drop_table('phone_link', schema='whatsapp')
    op.drop_index('uq_whatsapp_message_provider_message_id', table_name='message', schema='whatsapp')
    op.drop_table('message', schema='whatsapp')
    op.drop_table('conversation', schema='whatsapp')

    op.execute("DROP SCHEMA IF EXISTS whatsapp")

    # Postgres has no `ALTER TYPE ... DROP VALUE` — the 'whatsapp'
    # room_name label is left in place on downgrade, same as 'orgs' in
    # the previous migration. Harmless once the schema itself is gone.
