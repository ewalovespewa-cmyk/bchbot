"""Роли: admin (главный), moderator (назначает админ), user (все остальные)."""
from aiogram.filters import BaseFilter
from aiogram.types import Message

import db
from config import ADMIN_IDS

ADMIN, MODERATOR, USER = "admin", "moderator", "user"
ROLE_NAMES = {ADMIN: "админ", MODERATOR: "модератор", USER: "участник"}


async def get_role(user_id: int) -> str:
    if user_id in ADMIN_IDS:
        return ADMIN
    if await db.is_moderator(user_id):
        return MODERATOR
    return USER


class IsAdmin(BaseFilter):
    async def __call__(self, message: Message) -> bool:
        return message.from_user is not None and message.from_user.id in ADMIN_IDS


class IsStaff(BaseFilter):
    """Админ или модератор."""

    async def __call__(self, message: Message) -> bool:
        if message.from_user is None:
            return False
        return await get_role(message.from_user.id) in (ADMIN, MODERATOR)
