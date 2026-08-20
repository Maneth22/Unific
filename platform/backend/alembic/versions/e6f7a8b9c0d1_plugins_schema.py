"""plugins schema

Adds the `plugins` schema (plugin_catalog, org_entitlement) — UNIFIC v2's
plugin/marketplace entitlement system, replacing the Tools Registry's 3
meeting-room-specific slots (meeting_stt/meeting_tts/meeting_translation)
with a boolean entitlement gate. The Tools Registry's other 4 slots
(whatsapp_send/reply_generator/comms_agent/video_provider) are untouched
— see docs/PHASE_3_NOTES.md.

Seeds `live_translation` (meeting_addon, gated by app.meetings.services)
and `ai_reply_agent_pro` (whatsapp_agent_tier, unused by any code yet —
seeded for a future phase per the rebuild directive).

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
Create Date: 2026-08-20 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'e6f7a8b9c0d1'
down_revision: Union[str, None] = 'd5e6f7a8b9c0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS plugins")
    op.execute("ALTER TYPE public.room_name ADD VALUE IF NOT EXISTS 'plugins'")

    plugin_category = sa.Enum('meeting_addon', 'whatsapp_agent_tier', 'reporting', name='plugin_category')
    entitlement_status = sa.Enum('active', 'suspended', 'cancelled', name='entitlement_status')

    op.create_table(
        'plugin_catalog',
        sa.Column('key', sa.String(length=100), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('category', plugin_category, nullable=False),
        sa.Column('default_limits', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('key', name=op.f('pk_plugin_catalog')),
        schema='plugins',
    )

    op.create_table(
        'org_entitlement',
        sa.Column('org_id', sa.String(), nullable=False),
        sa.Column('plugin_key', sa.String(length=100), nullable=False),
        sa.Column('status', entitlement_status, nullable=False),
        sa.Column('limits_override', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('activated_at', sa.DateTime(), nullable=False),
        sa.Column('activated_by', sa.String(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['orgs.org.id'], name=op.f('fk_org_entitlement_org_id_org'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(
            ['plugin_key'], ['plugins.plugin_catalog.key'], name=op.f('fk_org_entitlement_plugin_key_plugin_catalog'), ondelete='CASCADE'
        ),
        sa.ForeignKeyConstraint(
            ['activated_by'], ['core.staff_user.id'], name=op.f('fk_org_entitlement_activated_by_staff_user'), ondelete='SET NULL'
        ),
        sa.PrimaryKeyConstraint('org_id', 'plugin_key', name=op.f('pk_org_entitlement')),
        schema='plugins',
    )

    now = sa.text("now()")
    op.execute(
        """
        INSERT INTO plugins.plugin_catalog (key, name, description, category, default_limits, is_active, created_at, updated_at)
        VALUES
          ('live_translation', 'Live Meeting Translation',
           'Real-time captions and dubbed audio translation during LiveKit meetings, powered by Google Speech-to-Text/Text-to-Speech and Gemini.',
           'meeting_addon', '{}'::jsonb, true, now(), now()),
          ('ai_reply_agent_pro', 'AI Reply Agent (Pro)',
           'A higher-tier WhatsApp auto-reply agent for orgs that need it. Not wired to any code path yet — seeded for a future phase.',
           'whatsapp_agent_tier', '{}'::jsonb, true, now(), now())
        """
    )


def downgrade() -> None:
    op.drop_table('org_entitlement', schema='plugins')
    op.drop_table('plugin_catalog', schema='plugins')
    op.execute("DROP SCHEMA IF EXISTS plugins")
    sa.Enum(name='entitlement_status').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='plugin_category').drop(op.get_bind(), checkfirst=True)
    # Postgres has no `ALTER TYPE ... DROP VALUE` — the 'plugins' room_name
    # label is left in place on downgrade, same precedent as prior migrations.
