"""Гейт доступа: к играм пускаем только тех, кто активировал бота регистрации.

Подключается одной строкой в main.py и ничего не меняет в самих играх: существующие
хендлеры просто не получают апдейты от посторонних. Админы и модераторы проходят всегда.

Для бинго (на проекте) есть фильтр IsCheckedIn: хендлеры бинго помечаются им, и карточка
открывается только тем, кто отметился на входе сегодня.
"""
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.filters import BaseFilter
from aiogram.types import CallbackQuery, Message, TelegramObject

from integration import access, config
from roles import is_staff

log = logging.getLogger(__name__)

ALWAYS_ALLOWED_COMMANDS = {"/myid"}
GROUP_NOTICE_EVERY = 6 * 3600  # в общем чате напоминаем одному человеку не чаще раза в 6 часов
_group_noticed: dict[int, float] = {}
_album_noticed: set[str] = set()


def not_activated_text() -> str:
    return (
        "Игры Business Cup — для участников проекта.\n\n"
        f"Сначала активируй бота участника по ссылке из письма: @{config.BC_REG_BOT_USERNAME}\n"
        "После этого возвращайся сюда 🙌"
    )


UNAVAILABLE_TEXT = "Не получилось проверить доступ — попробуй через минуту 🙏"
NEED_CHECKIN_TEXT = (
    "🎲 Бинго откроется, когда ты отметишься на входе.\n"
    f"Отсканируй QR на экране у входа — бот @{config.BC_REG_BOT_USERNAME} отметит тебя, и карточка станет доступна."
)


class AccessGate(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = getattr(event, "from_user", None)
        if user is None or user.is_bot or await is_staff(user.id):
            return await handler(event, data)
        if isinstance(event, Message) and (event.text or "").split("@")[0].split(" ")[0] in ALWAYS_ALLOWED_COMMANDS:
            return await handler(event, data)

        activated = await access.is_activated(user.id)
        if activated:
            return await handler(event, data)

        text = UNAVAILABLE_TEXT if activated is None else not_activated_text()
        if isinstance(event, CallbackQuery):
            await event.answer(text, show_alert=True)
        elif isinstance(event, Message):
            if event.chat.type == "private":
                # альбом приходит пачкой сообщений — отвечаем только на первое
                album = getattr(event, "media_group_id", None)
                if album is None or album not in _album_noticed:
                    if album:
                        _album_noticed.add(album)
                    await event.answer(text)
            elif event.photo or event.document:
                # В общем чате не спамим: подсказываем человеку изредка, его фото не уходят на проверку.
                now = time.time()
                if now - _group_noticed.get(user.id, 0) > GROUP_NOTICE_EVERY:
                    _group_noticed[user.id] = now
                    await event.reply(text)
        return None


class IsCheckedIn(BaseFilter):
    """Фильтр для хендлеров бинго: пропускает только отметившихся сегодня (и персонал).
    Остальным отвечает подсказкой и не пускает дальше."""

    async def __call__(self, event: Message | CallbackQuery) -> bool:
        user = event.from_user
        if not config.ENABLED or user is None or await is_staff(user.id):
            return True
        if await access.is_checked_in(user.id):
            return True
        if isinstance(event, CallbackQuery):
            await event.answer(NEED_CHECKIN_TEXT, show_alert=True)
        else:
            await event.answer(NEED_CHECKIN_TEXT)
        return False
