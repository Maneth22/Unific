"""Creates the room_account + agent_sub_account rows every room needs
before its first spend call. Run once per environment after migrating:

    python -m scripts.seed_rooms
"""
from __future__ import annotations

import asyncio

from app.core.models.common import RoomName
from app.core.services import spend_service
from app.database import AsyncSessionLocal

ROOM_AGENTS = {
    RoomName.accounts: ["administrative_agent"],
    RoomName.profiles: ["profile_manager_agent"],
    RoomName.meeting_room: ["comms_agent"],
}


async def main() -> None:
    async with AsyncSessionLocal() as db:
        for room, agents in ROOM_AGENTS.items():
            await spend_service.ensure_room_account(db, room)
            for agent_name in agents:
                await spend_service.ensure_agent_sub_account(db, room, agent_name)
            print(f"seeded room_account + sub-accounts for {room.value}: {agents}")
        await db.commit()


if __name__ == "__main__":
    asyncio.run(main())
