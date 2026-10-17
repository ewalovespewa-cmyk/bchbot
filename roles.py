"""Роли: admin (главный), moderator (назначает админ), user (все остальные)."""
from aiogram.filters import BaseFilter
from aiogram.types import CallbackQuery, Message

import db
from config import ADMIN_IDS

ADMIN, MODERATOR, USER = "admin", "moderator", "user"
ROLE_NAMES = {ADMIN: "админ", MODERATOR: "модератор (OC)", USER: "участник"}


async def get_role(user_id: int) -> str:
    if user_id in ADMIN_IDS:
        return ADMIN
    if await db.is_moderator(user_id):
        return MODERATOR
    return USER


async def is_staff(user_id: int) -> bool:
    return await get_role(user_id) in (ADMIN, MODERATOR)


async def staff_ids() -> list[int]:
    """Все, кому приходят фото на проверку: админы + модераторы."""
    ids = list(ADMIN_IDS)
    for mod_id in await db.moderator_ids():
        if mod_id not in ids:
            ids.append(mod_id)
    return ids


class IsAdmin(BaseFilter):
    async def __call__(self, event: Message | CallbackQuery) -> bool:
        return event.from_user is not None and event.from_user.id in ADMIN_IDS


class IsStaff(BaseFilter):
    """Админ или модератор."""

    async def __call__(self, event: Message | CallbackQuery) -> bool:
        return event.from_user is not None and await is_staff(event.from_user.id)
