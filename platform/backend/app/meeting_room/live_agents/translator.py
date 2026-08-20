"""TranslatorManager — the single component shared by both captions.py and
chat_relay.py. Gemini is used only as a plain text translator here (never
audio-to-audio, unlike the old live_translation.py); every caller is
expected to already have deduped its recipients down to one entry per
distinct target language before calling `translate()` — this module
itself doesn't do that dedup (see `participant_attrs.ParticipantRegistry`
for where it happens), it just guarantees one Gemini call per invocation
and never repeats work for a language pair that doesn't need translating.

Two independent prompt strategies, either of which can rescue the other:
the original generic single-pair prompt (PROMPT_TEMPLATE, via
_attempt_generic) used to have no error handling at all around the Gemini
call — an API error (timeout, rate limit, transient 5xx, ...) propagated
straight out of `translate()`, which meant a chat message (or caption
line) for that target language silently never got relayed at all.
`translate()` now catches that (and an empty Gemini response) and retries
via the other strategy — a specialized, per-source-language prompt
(FALLBACK_PROMPTS, via _attempt_specialized) that asks for translations
into BOTH other supported languages at once (matching the product's fixed
en/hi/si triangle) and additionally accounts for "Singlish"/"Hinglish"
input — Sinhala or Hindi typed phonetically in the Latin alphabet, which a
participant's *registered* chat/caption language of "en" wouldn't
otherwise hint at.

Which one goes first is the `mode` argument (default "generic_first").
chat_relay.py passes `settings.live_agents_chat_translation_mode` through,
which currently defaults to "specialized_first" — in-call chat is where
this platform's community actually types romanized Sinhala/Hindi day to
day, so that strategy leads there for now; captions.py doesn't pass
`mode` at all and always gets "generic_first". Only the original text is
ever shown if both attempts fail — an untranslated-but-present message
still beats a blank one.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re

from app.meeting_room.live_agents.translation_backends import LiveTranslationBackend

logger = logging.getLogger("live_agents.translator")

PROMPT_TEMPLATE = (
    "You are a translator. Translate the given text from {source_language} to "
    "{target_language}. Output ONLY the translation, nothing else — no notes, "
    "no alternate phrasings, no explanations, preserve the original script, "
    "do not transliterate."
)

# Fallback-only prompts, keyed by source language — deliberately hardcoded
# to this product's fixed en/hi/si triangle (unlike PROMPT_TEMPLATE above,
# which is language-pair-generic) per explicit product requirement: one
# Gemini call per source language, translating into BOTH of the other two
# languages at once, returned as strict JSON so a single fallback call can
# resolve whichever target language actually failed. Adding a 4th
# selectable language later needs a matching new entry here.
FALLBACK_PROMPTS: dict[str, str] = {
    "en": (
        "You are a translator for a community chat and captions platform. "
        "Translate the given English text into BOTH Sinhala and Hindi. "
        "SPECIAL CASE: the input may actually be Sinhala or Hindi typed "
        "phonetically in the Latin/English alphabet — \"Singlish\" (e.g. "
        "\"kohomada\", \"mokada wenne\", \"oyaata kohomada\") or \"Hinglish\" "
        "(e.g. \"kya haal hai\", \"tum kaise ho\", \"bhai kahan ho\") — even "
        "though it is nominally tagged as English. Recognize this and translate "
        "the intended meaning, not a literal reading of the Latin letters. "
        "Respond with ONLY a single-line, valid JSON object of the exact shape "
        '{{"si": "<Sinhala translation>", "hi": "<Hindi translation>"}} — no '
        "markdown, no code fences, no commentary, no extra keys."
    ),
    "hi": (
        "You are a translator for a community chat and captions platform. "
        "Translate the given Hindi text into BOTH Sinhala and English. The "
        "input may be in Devanagari script, or informally romanized as "
        "\"Hinglish\" — Hindi words spelled out in the Latin/English alphabet, "
        "often mixed with English words (e.g. \"kya haal hai bhai\", \"tum "
        "kaise ho\", \"mujhe nahi pata yaar\"). Translate the intended meaning "
        "accurately, not a literal reading of the Latin letters. Respond with "
        "ONLY a single-line, valid JSON object of the exact shape "
        '{{"si": "<Sinhala translation>", "en": "<English translation>"}} — no '
        "markdown, no code fences, no commentary, no extra keys."
    ),
    "si": (
        "You are a translator for a community chat and captions platform. "
        "Translate the given Sinhala text into BOTH English and Hindi. The "
        "input may be in Sinhala script, or informally romanized as "
        "\"Singlish\" — Sinhala words spelled out in the Latin/English "
        "alphabet (e.g. \"kohomada\", \"oyaata kohomada\", \"mata ehema "
        "karanna bae\"). Translate the intended meaning accurately, not a "
        "literal reading of the Latin letters. Respond with ONLY a "
        "single-line, valid JSON object of the exact shape "
        '{{"en": "<English translation>", "hi": "<Hindi translation>"}} — no '
        "markdown, no code fences, no commentary, no extra keys."
    ),
}

# Cheap keyword heuristics — no ML model, no extra dependency — good enough
# to catch the common case of romanized/informal Sinhala or Hindi-English
# code-mixed chat text. Only ever used to pick which FALLBACK_PROMPTS entry
# to use; never changes a message's persisted/broadcast source_language.
_SINGLISH_MARKERS = frozenset({
    "oyaa", "oyata", "oyaata", "mokada", "kohomada", "kiyala", "puluwan",
    "epaa", "hondai", "monawada", "mata", "eka", "menna", "harida", "aiyye",
    "aney", "machan", "wenawa", "karanna", "yanna", "bari", "neh", "nane",
    "ban", "mokakda", "kohoma", "ow", "naha", "hutta",
})
_HINGLISH_MARKERS = frozenset({
    "kya", "hai", "nahi", "haan", "kaise", "kyun", "tum", "aap", "bhai",
    "yaar", "accha", "theek", "matlab", "kar", "raha", "rahi", "krna",
    "abhi", "kahan", "kuch", "sab", "mera", "tera", "hum", "mujhe", "tumhe",
    "chalo", "acha", "nahin",
})
_WORD_RE = re.compile(r"[a-zA-Z']+")


def detect_informal_style(text: str) -> str | None:
    """Returns "si" or "hi" when `text` looks like romanized Sinhala
    ("Singlish") or Hindi-English code-mixed text ("Hinglish") respectively,
    else None. Requires a couple of marker hits (not just one stray word
    that happens to collide with a marker) before overriding anything, to
    keep this conservative — a false positive here would pick the wrong
    fallback prompt for genuinely English text."""
    words = _WORD_RE.findall(text.lower())
    if not words:
        return None
    word_set = set(words)
    si_hits = len(word_set & _SINGLISH_MARKERS)
    hi_hits = len(word_set & _HINGLISH_MARKERS)
    threshold = max(2, len(words) // 4)
    if si_hits >= threshold and si_hits >= hi_hits:
        return "si"
    if hi_hits >= threshold and hi_hits > si_hits:
        return "hi"
    return None


class TranslatorManager:
    """One instance per meeting (see orchestrator.py) — `translate()` is
    stateless per call (the backend's completion call has no session to
    keep open), so "caching one translator instance per active target
    language" concretely means caching the system-prompt STRING per
    (source, target) pair, not a persistent connection. Bounded by a
    shared `asyncio.Semaphore` so a translation burst across many
    distinct target languages can't overrun the process — see
    `settings.live_agents_max_concurrent_translate_calls`.

    `backend` is the Tools Registry's `meeting_translation` selection
    (see `translation_backends.py`) — this class never talks to Gemini or
    any other LLM API directly, only through `backend.generate()`, so
    which LLM actually answers is entirely the caller's (orchestrator.py's)
    choice."""

    def __init__(self, *, backend: LiveTranslationBackend, semaphore: asyncio.Semaphore):
        self._backend = backend
        self._semaphore = semaphore
        self._prompt_cache: dict[tuple[str, str], str] = {}

    def _prompt_for(self, source_lang: str, target_lang: str) -> str:
        key = (source_lang, target_lang)
        prompt = self._prompt_cache.get(key)
        if prompt is None:
            prompt = PROMPT_TEMPLATE.format(source_language=source_lang, target_language=target_lang)
            self._prompt_cache[key] = prompt
        return prompt

    async def translate(
        self, text: str, source_lang: str, target_lang: str, *, mode: str = "generic_first"
    ) -> str:
        """Same-language short-circuits to the original text with NO
        Gemini call at all — this is what makes "skip translation for a
        recipient whose target language already matches the source"
        actually free, not just cheap.

        `mode` picks which of the two prompt strategies below is tried
        FIRST, the other being the rescue attempt if it fails — see
        `settings.live_agents_chat_translation_mode` (chat_relay.py passes
        that through; captions.py always uses the "generic_first" default):
          "generic_first"      — _attempt_generic, then _attempt_specialized.
          "specialized_first"  — _attempt_specialized, then _attempt_generic.
        Degrades to the original text (never raises) if both attempts
        fail, matching the rest of this module's philosophy."""
        if not text.strip() or source_lang == target_lang:
            return text

        first, second = (
            (self._attempt_specialized, self._attempt_generic)
            if mode == "specialized_first"
            else (self._attempt_generic, self._attempt_specialized)
        )
        result = await first(text, source_lang, target_lang)
        if result is not None:
            return result
        result = await second(text, source_lang, target_lang)
        if result is not None:
            return result
        return text

    async def _attempt_generic(self, text: str, source_lang: str, target_lang: str) -> str | None:
        """The original single-pair prompt (PROMPT_TEMPLATE). Returns None
        (never the original text) on any failure — including a backend
        call failure, which `backend.generate()` itself already catches
        and reports as `None` — so `translate()` can tell "this attempt
        didn't produce anything" apart from "this attempt legitimately
        translated to the same text"."""
        async with self._semaphore:
            translated = await self._backend.generate(
                text=text, system_instruction=self._prompt_for(source_lang, target_lang), json_mode=False
            )
        if translated:
            return translated
        logger.warning(
            "generic translation returned nothing source=%s target=%s — trying the other strategy",
            source_lang, target_lang,
        )
        return None

    async def _attempt_specialized(self, text: str, source_lang: str, target_lang: str) -> str | None:
        """Per-source-language prompt (FALLBACK_PROMPTS) that asks the
        backend for both other languages at once as JSON, after first
        checking whether `text` actually reads as romanized Sinhala/Hindi
        rather than the claimed `source_lang` (see detect_informal_style)
        — a participant's registered language is a UI setting, not proof
        of what script they're actually typing in. Returns None on any
        failure, same contract as `_attempt_generic` above."""
        effective_source = detect_informal_style(text) or source_lang
        prompt = FALLBACK_PROMPTS.get(effective_source)
        if prompt is None:
            return None

        async with self._semaphore:
            raw = await self._backend.generate(text=text, system_instruction=prompt, json_mode=True)
        if raw is None:
            return None
        try:
            data = json.loads(raw)
            translated = str(data.get(target_lang) or "").strip()
            if translated:
                return translated
            logger.warning(
                "specialized translation returned empty source=%s effective_source=%s target=%s — "
                "trying the other strategy",
                source_lang, effective_source, target_lang,
            )
        except (json.JSONDecodeError, AttributeError):
            logger.exception(
                "specialized translation returned malformed JSON source=%s effective_source=%s target=%s",
                source_lang, effective_source, target_lang,
            )
        return None
