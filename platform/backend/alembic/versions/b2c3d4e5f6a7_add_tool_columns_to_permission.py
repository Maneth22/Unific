"""add tool columns to permission

Adds the Tools Registry's five own_*/effective_* field pairs to
profiles.permission (reply_generator, comms_agent, meeting_translation,
meeting_stt, meeting_tts) — same narrowing-free own_*/effective_*
inheritance shape as own_reply_role/effective_reply_role. effective_*
server_defaults match this migration chain's tool_global_selection seed
(a1b2c3d4e5f6) exactly, so every existing Permission row is already
correct the moment this lands, no backfill needed.

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-08-18 12:05:00.000000

"""
import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Read live, at migration-run time — NOT hardcoded literals matching
    # app.config.Settings' class defaults, which a real deployment's
    # `.env` may well have overridden (e.g. REPLY_PROVIDER=gemini rather
    # than the class default "stub"). See a1b2c3d4e5f6's _global_seed()
    # for the same reasoning; these server_defaults must agree with that
    # migration's seed so a pre-existing Permission row's effective_* is
    # already correct even before its next recompute_cascade.
    from app.config import settings

    op.add_column('permission', sa.Column('own_reply_generator_tool', sa.String(length=100), nullable=True), schema='profiles')
    op.add_column('permission', sa.Column('own_comms_agent_tool', sa.String(length=100), nullable=True), schema='profiles')
    op.add_column('permission', sa.Column('own_meeting_translation_tool', sa.String(length=100), nullable=True), schema='profiles')
    op.add_column('permission', sa.Column('own_meeting_stt_tools', postgresql.JSONB(astext_type=sa.Text()), nullable=True), schema='profiles')
    op.add_column('permission', sa.Column('own_meeting_tts_tools', postgresql.JSONB(astext_type=sa.Text()), nullable=True), schema='profiles')

    op.add_column('permission', sa.Column(
        'effective_reply_generator_tool', sa.String(length=100), nullable=False, server_default=settings.reply_provider,
    ), schema='profiles')
    op.add_column('permission', sa.Column(
        'effective_comms_agent_tool', sa.String(length=100), nullable=False, server_default=settings.comms_agent_provider,
    ), schema='profiles')
    op.add_column('permission', sa.Column(
        'effective_meeting_translation_tool', sa.String(length=100), nullable=False, server_default='gemini',
    ), schema='profiles')
    op.add_column('permission', sa.Column(
        'effective_meeting_stt_tools', postgresql.JSONB(astext_type=sa.Text()), nullable=False,
        server_default=json.dumps(json.loads(settings.live_agents_stt_provider_map)),
    ), schema='profiles')
    op.add_column('permission', sa.Column(
        'effective_meeting_tts_tools', postgresql.JSONB(astext_type=sa.Text()), nullable=False,
        server_default=json.dumps({
            lang: {"provider": entry["provider"], "voice": entry["voice"]}
            for lang, entry in json.loads(settings.live_agents_tts_provider_map).items()
        }),
    ), schema='profiles')


def downgrade() -> None:
    op.drop_column('permission', 'effective_meeting_tts_tools', schema='profiles')
    op.drop_column('permission', 'effective_meeting_stt_tools', schema='profiles')
    op.drop_column('permission', 'effective_meeting_translation_tool', schema='profiles')
    op.drop_column('permission', 'effective_comms_agent_tool', schema='profiles')
    op.drop_column('permission', 'effective_reply_generator_tool', schema='profiles')

    op.drop_column('permission', 'own_meeting_tts_tools', schema='profiles')
    op.drop_column('permission', 'own_meeting_stt_tools', schema='profiles')
    op.drop_column('permission', 'own_meeting_translation_tool', schema='profiles')
    op.drop_column('permission', 'own_comms_agent_tool', schema='profiles')
    op.drop_column('permission', 'own_reply_generator_tool', schema='profiles')
