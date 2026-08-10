"""Manual CLI runner for a single-language, single-room translation agent —
useful for debugging outside the meeting lifecycle. In normal operation the
same `TranslationAgent` class is driven automatically per meeting by
`app.meeting_room.live_translation.start_for_meeting`/`stop_for_meeting`,
called from `app.meeting_room.services` on meeting go-live/end.

    python -m scripts.translation_agent --room meeting-123 --target-lang si
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import signal

from app.config import settings
from app.meeting_room.live_translation import TranslationAgent


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--room", required=True, help="LiveKit room name to join, e.g. meeting-123")
    parser.add_argument(
        "--target-lang",
        required=True,
        help=f"Target language code, one of: {', '.join(settings.live_translation_allowed_language_list)}",
    )
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    if args.target_lang not in settings.live_translation_allowed_language_list:
        parser.error(
            f"--target-lang must be one of {settings.live_translation_allowed_language_list}, got {args.target_lang!r}"
        )
    if not settings.livekit_url or not settings.livekit_api_key or not settings.livekit_api_secret:
        parser.error("LIVEKIT_URL, LIVEKIT_API_KEY and LIVEKIT_API_SECRET must be set in .env")
    if not settings.gemini_api_key:
        parser.error("GEMINI_API_KEY must be set in .env")

    logging.basicConfig(level=args.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    async def _run() -> None:
        # TranslationAgent must be constructed *inside* the running loop
        # (i.e. inside this coroutine, not before asyncio.run() starts it):
        # rtc.Room() binds its internal event-loop reference at construction
        # time via `asyncio.get_event_loop()`. Building it earlier, in
        # synchronous main() before asyncio.run() exists, binds it to a
        # throwaway loop that's never actually driven — the room's internal
        # event-listen task then gets scheduled on that dead loop and never
        # runs, so connect() still succeeds (it awaits a separately-bound
        # queue) but every subsequent room event (track_subscribed,
        # participant_connected, etc.) silently never fires. That was the
        # cause of the agent connecting fine but never translating anything.
        agent = TranslationAgent(room_name=args.room, target_lang=args.target_lang)

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, agent.request_stop)
            except NotImplementedError:
                # add_signal_handler isn't supported on Windows' event loops
                # (dev environment here is Windows) — signal.signal() is the
                # cross-platform fallback that still lets a Ctrl+C reach the
                # handler and set the stop event for a graceful shutdown,
                # instead of asyncio's default of raising KeyboardInterrupt
                # straight through run().
                signal.signal(sig, lambda *_: agent.request_stop())

        await agent.run()

    asyncio.run(_run())


if __name__ == "__main__":
    main()
