"""Dev-only comms agent — deterministic, no external call, never records
usage. Lets the whole bidirectional comms-room flow (clarify, tone,
translate, reports) run end-to-end with no Gemini key.
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models.common import RoomName
from app.core.providers.base import CommsAgent, InboundClarification, OutboundTranslation


class MockCommsAgent(CommsAgent):
    async def clarify_inbound(
        self, db: AsyncSession, text: str, *, identity_id: str | None, room: RoomName, agent_name: str
    ) -> InboundClarification:
        return InboundClarification(detected_language="English", detected_code="en", clarification=text)

    async def analyze_tone(
        self,
        db: AsyncSession,
        text: str,
        *,
        detected_language: str,
        identity_id: str | None,
        room: RoomName,
        agent_name: str,
    ) -> dict:
        return {
            "language_proficiency": "fluent",
            "emotional_tone": "neutral",
            "politeness_level": "polite",
            "communication_style": "questioning",
            "brief_insight": "Mock analysis — no LLM configured.",
        }

    async def translate_outbound(
        self,
        db: AsyncSession,
        text: str,
        *,
        chat_history: str,
        target_language: str,
        tone: str,
        character: str,
        identity_id: str | None,
        room: RoomName,
        agent_name: str,
    ) -> OutboundTranslation:
        language = (target_language or "auto").lower()
        translated = text if language in ("auto", "en", "english") else f"[{language}] {text}"
        return OutboundTranslation(translated_text=translated, key_points=[], english_preview=text)

    async def generate_session_report(
        self, db: AsyncSession, transcript: str, *, identity_id: str | None, room: RoomName, agent_name: str
    ) -> dict:
        return {
            "summary": "Mock session report — no LLM configured.",
            "community_needs": "Unknown",
            "client_offers": "Unknown",
            "gaps": "Unknown",
            "sentiment": "neutral",
            "comfort_level": "medium",
            "requirements_met": "partial",
            "communication_style": "Unknown",
            "language_proficiency": "Unknown",
            "overall_demeanor": "Unknown",
        }

    async def generate_satisfaction_analysis(
        self, db: AsyncSession, transcript: str, *, identity_id: str | None, room: RoomName, agent_name: str
    ) -> dict:
        return {
            "satisfaction_level": "medium",
            "satisfaction_score": 5,
            "sentiment_trend": "stable",
            "summary": "Mock satisfaction analysis — no LLM configured.",
            "positives": [],
            "concerns": [],
            "unmet_needs": [],
            "recommendations": [],
        }

    async def generate_member_summary(
        self, db: AsyncSession, transcript: str, *, identity_id: str | None, room: RoomName, agent_name: str
    ) -> dict:
        return {
            "profile_summary": "Mock member summary — no LLM configured.",
            "key_topics": [],
            "needs_expressed": [],
            "sentiment_overall": "neutral",
            "communication_notes": "Unknown",
        }
