"""tool catalog and global selection

Adds the Tools Registry's two core tables: `core.tool_catalog_entry` (what
implementations are known/enabled per pluggable slot) and
`core.tool_global_selection` (the staff-editable system-wide choice per
slot — the only selection for whatsapp_send/video_provider, and the new
admin-editable root-of-cascade default for the five slots that cascade
through profiles.permission).

Both tables are seeded in this same migration with rows matching today's
real `.env`/Settings defaults exactly, so a fresh `alembic upgrade head`
changes no runtime behavior at all — see docs/ARCHITECTURE.md's Tools
Registry section.

Revision ID: a1b2c3d4e5f6
Revises: c3264277df18
Create Date: 2026-08-18 12:00:00.000000

"""
import json
from datetime import datetime
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'c3264277df18'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SLOTS = (
    'whatsapp_send', 'reply_generator', 'comms_agent', 'video_provider',
    'meeting_stt', 'meeting_tts', 'meeting_translation',
)

# (slot, tool_key, display_name, description, package_name)
_CATALOG_SEED = [
    ('whatsapp_send', 'cloud_api', 'WhatsApp Cloud API',
     "Meta's official WhatsApp Business Cloud API - real message sending/receiving.", None),
    ('whatsapp_send', 'mock', 'Mock (developer testing)',
     'Simulates WhatsApp send/receive locally, including occasional simulated failures - no real messages sent.', None),

    ('reply_generator', 'gemini', 'Gemini',
     'Google Gemini drafts the WhatsApp auto-reply text.', 'google-genai'),
    ('reply_generator', 'stub', 'Template stub',
     'Deterministic template-based reply restricted to approved context snippets - no LLM call.', None),

    ('comms_agent', 'gemini', 'Gemini',
     'Google Gemini handles clarify-inbound, tone analysis, outbound translation, and report generation.', 'google-genai'),
    ('comms_agent', 'mock', 'Mock (developer testing)',
     'Deterministic canned responses for every comms-agent action - no LLM call.', None),

    ('video_provider', 'livekit', 'LiveKit',
     'Real LiveKit video/audio rooms and access tokens.', 'livekit-api'),
    ('video_provider', 'mock', 'Mock (developer testing)',
     'Mints fake tokens, no real video room - for local development.', None),

    # Google-only (Deepgram/Azure/OpenAI/ElevenLabs catalog rows removed —
    # deliberate product decision, see docs/adr and
    # app.core.services.tools_registry._MEETING_STT_KEYS/etc.).
    ('meeting_stt', 'google', 'Google Cloud Speech',
     'Google Cloud Speech-to-Text (Chirp 3).', 'livekit-plugins-google'),

    ('meeting_tts', 'google', 'Google Cloud TTS',
     'Google Cloud Text-to-Speech.', 'livekit-plugins-google'),

    ('meeting_translation', 'gemini', 'Gemini',
     'Google Gemini translates live captions, dubbed audio, and in-call chat.', 'google-genai'),
]

def _global_seed() -> list[tuple[str, str, str, str | None]]:
    """(slot, language, tool_key, voice) — read from `app.config.settings`
    at MIGRATION-RUN time, not hardcoded as literals here. This matters:
    the `Settings` class's own field defaults ("mock"/"stub"/etc.) are
    NOT necessarily what a given deployment's real `.env` has configured
    (e.g. a deploy with `WHATSAPP_PROVIDER=cloud_api`/`VIDEO_PROVIDER=
    livekit` already live) — seeding the class defaults instead of this
    environment's actual current values would silently downgrade a
    working deployment to mock/stub providers on migration, exactly the
    "no behavior change on deploy" guarantee this migration exists to
    provide. meeting_translation has no prior setting of its own, so it's
    the one field seeded to a literal ("gemini", the only backend that
    ever existed for it before this feature)."""
    from app.config import settings

    stt_map: dict[str, str] = json.loads(settings.live_agents_stt_provider_map)
    tts_map: dict[str, dict] = json.loads(settings.live_agents_tts_provider_map)
    return [
        ('whatsapp_send', '*', settings.whatsapp_provider, None),
        ('reply_generator', '*', settings.reply_provider, None),
        ('comms_agent', '*', settings.comms_agent_provider, None),
        ('video_provider', '*', settings.video_provider, None),
        ('meeting_translation', '*', 'gemini', None),
        *[('meeting_stt', lang, provider, None) for lang, provider in stt_map.items()],
        *[('meeting_tts', lang, entry['provider'], entry['voice']) for lang, entry in tts_map.items()],
    ]


def upgrade() -> None:
    tool_slot_enum = sa.Enum(*_SLOTS, name='tool_slot')

    op.create_table(
        'tool_catalog_entry',
        sa.Column('slot', tool_slot_enum, nullable=False),
        sa.Column('tool_key', sa.String(length=100), nullable=False),
        sa.Column('display_name', sa.String(length=200), nullable=False),
        sa.Column('description', sa.Text(), nullable=False, server_default=''),
        sa.Column('package_name', sa.String(length=200), nullable=True),
        sa.Column('is_enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('slot', 'tool_key'),
        schema='core',
    )

    op.create_table(
        'tool_global_selection',
        sa.Column('slot', tool_slot_enum, nullable=False),
        sa.Column('language', sa.String(length=20), nullable=False, server_default='*'),
        sa.Column('tool_key', sa.String(length=100), nullable=False),
        sa.Column('voice', sa.String(length=200), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('updated_by_staff_id', sa.String(), nullable=True),
        sa.ForeignKeyConstraint(['updated_by_staff_id'], ['core.staff_user.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('slot', 'language'),
        schema='core',
    )

    now = datetime.utcnow()  # naive UTC, matching every DateTime column in this app
    catalog_table = sa.table(
        'tool_catalog_entry',
        sa.column('slot', tool_slot_enum), sa.column('tool_key', sa.String),
        sa.column('display_name', sa.String), sa.column('description', sa.Text),
        sa.column('package_name', sa.String), sa.column('is_enabled', sa.Boolean),
        sa.column('created_at', sa.DateTime), sa.column('updated_at', sa.DateTime),
        schema='core',
    )
    op.bulk_insert(
        catalog_table,
        [
            {
                'slot': slot, 'tool_key': tool_key, 'display_name': display_name,
                'description': description, 'package_name': package_name, 'is_enabled': True,
                'created_at': now, 'updated_at': now,
            }
            for slot, tool_key, display_name, description, package_name in _CATALOG_SEED
        ],
    )

    global_table = sa.table(
        'tool_global_selection',
        sa.column('slot', tool_slot_enum), sa.column('language', sa.String), sa.column('tool_key', sa.String),
        sa.column('voice', sa.String), sa.column('updated_at', sa.DateTime),
        schema='core',
    )
    op.bulk_insert(
        global_table,
        [
            {'slot': slot, 'language': language, 'tool_key': tool_key, 'voice': voice, 'updated_at': now}
            for slot, language, tool_key, voice in _global_seed()
        ],
    )


def downgrade() -> None:
    op.drop_table('tool_global_selection', schema='core')
    op.drop_table('tool_catalog_entry', schema='core')
    sa.Enum(name='tool_slot').drop(op.get_bind(), checkfirst=True)
