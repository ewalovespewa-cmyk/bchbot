"""Экспедиция — игра на весь проект: чем больше общаешься в чатах, тем выше в лидерборде.

Баллы:
- любое сообщение (текст, стикер, фото, гиф…) — EXP_MESSAGE_POINTS (1)
- голосовое или кружок — EXP_VOICE_POINTS (3)
- день, когда в ФотоХанте засчитали хотя бы одно фото — EXP_PHOTOHUNT_DAY_POINTS (5),
  начисляется в handlers/photohunt.py
- ручные корректировки OC — /addpoints

Считаются сообщения только в подключённых чатах (/track в чате), только от участников
(не OC, не ботов) и только пока Экспедиция идёт (/expstart, /expstop).
Если включена интеграция с ботом регистрации, подсчёт стоит ПОСЛЕ её фильтра доступа,
поэтому баллы получают только активировавшие бота регистрации.
"""
import html
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from aiogram import BaseMiddleware, F, Router
from aiogram.enums import ContentType
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, TelegramObject

import db
from config import (
    EXP_COOLDOWN_SECONDS,
    EXP_MESSAGE_POINTS,
    EXP_PRIZE_PLACES,
    EXP_TOP_SIZE,
    EXP_VOICE_POINTS,
    LOCAL_TZ,
)
from roles import IsAdmin, IsStaff, is_staff, staff_ids

router = Router()
log = logging.getLogger(__name__)

GROUPS = {"group", "supergroup"}
VOICE_TYPES = {ContentType.VOICE, ContentType.VIDEO_NOTE}
COUNTED_TYPES = VOICE_TYPES | {
    ContentType.TEXT, ContentType.STICKER, ContentType.PHOTO, ContentType.VIDEO,
    ContentType.ANIMATION, ContentType.DOCUMENT, ContentType.AUDIO, ContentType.POLL,
    ContentType.DICE, ContentType.LOCATION, ContentType.VENUE, ContentType.CONTACT,
    ContentType.STORY,
}
MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}


def esc(text: str | None) -> str:
    return html.escape(text or "")


# ---------------------------------------------------------------- кэш настроек

class _State:
    chats: set[int] | None = None
    active: bool | None = None
    known_users: set[int] = set()
    last_counted: dict[int, float] = {}


async def tracked_chats() -> set[int]:
    if _State.chats is None:
        _State.chats = await db.exp_chat_ids()
    return _State.chats


async def is_active() -> bool:
    if _State.active is None:
        _State.active = (await db.get_setting("exp_active")) != "0"  # по умолчанию идёт
    return _State.active


def reset_cache() -> None:
    _State.chats = None
    _State.active = None


# ---------------------------------------------------------------- подсчёт сообщений

def message_points(message: Message) -> tuple[int, bool] | None:
    """(баллы, это_голосовое) или None, если сообщение не считается."""
    if message.content_type not in COUNTED_TYPES:
        return None  # служебные: вступил, вышел, закрепил и т. п.
    if (message.text or "").startswith("/"):
        return None  # команды боту
    if message.content_type in VOICE_TYPES:
        return EXP_VOICE_POINTS, True
    return EXP_MESSAGE_POINTS, False


async def count_message(message: Message) -> bool:
    """Начисляет баллы за сообщение, если оно подходит. True — посчитали."""
    user = message.from_user
    if message.chat.type not in GROUPS or user is None or user.is_bot:
        return False
    if message.sender_chat is not None or message.is_automatic_forward:
        return False  # от имени канала/группы или автопересылка из канала
    if message.chat.id not in await tracked_chats() or not await is_active():
        return False
    scored = message_points(message)
    if scored is None or await is_staff(user.id):
        return False

    now = time.monotonic()
    if EXP_COOLDOWN_SECONDS and now - _State.last_counted.get(user.id, -1e9) < EXP_COOLDOWN_SECONDS:
        return False  # антиспам: слишком часто
    _State.last_counted[user.id] = now

    if user.id not in _State.known_users:
        await db.save_user(user.id, user.username, user.full_name)
        _State.known_users.add(user.id)
    points, is_voice = scored
    day = message.date.astimezone(LOCAL_TZ).date().isoformat()
    await db.add_exp_message(user.id, day, is_voice, points)
    return True


class ExpeditionCounter(BaseMiddleware):
    """Считает каждое сообщение в чатах Экспедиции и пропускает его дальше —
    к ФотоХанту и остальным хендлерам. Ошибка подсчёта никогда не ломает бота."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if isinstance(event, Message):
            try:
                await count_message(event)
            except Exception:
                log.exception("Экспедиция: не смог посчитать сообщение")
        return await handler(event, data)


# ---------------------------------------------------------------- лидерборд

async def ranking() -> list[tuple[int, int, str, int]]:
    """[(место, user_id, имя, баллы)] без OC."""
    staff = set(await staff_ids())
    rows = [r for r in await db.all_scores() if r[0] not in staff]
    return [
        (place, user_id, full_name or f"Участник {user_id}", total)
        for place, (user_id, full_name, _username, total) in enumerate(rows, 1)
    ]


def format_board(rows, me: int | None = None) -> str:
    stamp = datetime.now(LOCAL_TZ).strftime("%d.%m %H:%M")
    if not rows:
        return "🧭 <b>Экспедиция</b>\n\nПока никто не набрал баллов — пишите в чат, чтобы открыть рейтинг!"
    lines = ["🧭 <b>Экспедиция — лидерборд</b>", ""]
    for place, user_id, name, total in rows[:EXP_TOP_SIZE]:
        if place == EXP_PRIZE_PLACES + 1:
            lines += ["", "🎗 <i>Утешительные призы:</i>"]
        mark = MEDALS.get(place, f"{place}.")
        gift = " 🎁" if place <= EXP_PRIZE_PLACES else ""
        name = f"<b>{esc(name)}</b>" if user_id == me else esc(name)
        lines.append(f"{mark} {name} — {total}{gift}")
    if me is not None:
        mine = next((r for r in rows if r[1] == me), None)
        lines.append("")
        if mine is None:
            lines.append("Тебя пока нет в рейтинге — напиши что-нибудь в чат 🙂")
        elif mine[0] > EXP_TOP_SIZE:
            gap = rows[EXP_TOP_SIZE - 1][3] - mine[3] + 1
            lines.append(f"Ты на <b>{mine[0]}</b> месте ({mine[3]} балл.). До топ-{EXP_TOP_SIZE}: {gap} балл.")
    lines += ["", f"<i>🎁 — призы для топ-{EXP_PRIZE_PLACES}, места {EXP_PRIZE_PLACES + 1}–{EXP_TOP_SIZE} — утешительные. Обновлено {stamp}</i>"]
    return "\n".join(lines)


@router.message(Command("top"), F.chat.type == "private")
async def cmd_top_private(message: Message) -> None:
    rows = await ranking()
    me = None if await is_staff(message.from_user.id) else message.from_user.id
    await message.answer(format_board(rows, me))


@router.message(Command("top"), F.chat.type.in_(GROUPS), IsStaff())
async def cmd_top_group(message: Message) -> None:
    """OC публикует свежий лидерборд прямо в чат."""
    await message.answer(format_board(await ranking()))


@router.message(Command("points"), F.chat.type == "private")
async def cmd_points(message: Message) -> None:
    user_id = message.from_user.id
    b = await db.points_breakdown(user_id)
    total = await db.get_points(user_id)
    place = next((r[0] for r in await ranking() if r[1] == user_id), None)
    lines = [
        f"🧭 <b>Твоя Экспедиция: {total} балл.</b>",
        f"Место в рейтинге: <b>{place}</b>" if place else "В рейтинге тебя пока нет",
        "",
        f"💬 Сообщения: {b['messages']}",
        f"🎙 Голосовые и кружки: {b['voices']}",
        f"📸 Дней в ФотоХанте: {b['photohunt_days']} (+{b['photohunt_points']})",
    ]
    if b["adjust_points"]:
        lines.append(f"🛠 Корректировка OC: {b['adjust_points']:+d}")
    await message.answer("\n".join(lines))


# ---------------------------------------------------------------- управление (OC)

@router.message(Command("track"), F.chat.type.in_(GROUPS), IsAdmin())
async def cmd_track(message: Message) -> None:
    added = await db.add_exp_chat(message.chat.id, message.chat.title)
    reset_cache()
    if added:
        await message.reply("🧭 Экспедиция началась в этом чате! Каждое сообщение приносит баллы — /top в личке у бота.")
    else:
        await message.reply("Этот чат уже участвует в Экспедиции.")


@router.message(Command("untrack"), F.chat.type.in_(GROUPS), IsAdmin())
async def cmd_untrack(message: Message) -> None:
    removed = await db.remove_exp_chat(message.chat.id)
    reset_cache()
    await message.reply("Сообщения в этом чате больше не считаются." if removed else "Этот чат и так не подключён.")


@router.message(Command(commands=["track", "untrack"]), F.chat.type == "private", IsAdmin())
async def cmd_track_private(message: Message) -> None:
    await message.answer("Эту команду нужно отправить <b>в самом чате</b>, который подключаешь к Экспедиции.")


@router.message(Command("chats"), F.chat.type == "private", IsStaff())
async def cmd_chats(message: Message) -> None:
    chats = await db.list_exp_chats()
    state = "🟢 идёт" if await is_active() else "⏸ на паузе"
    if not chats:
        await message.answer(f"Экспедиция: {state}\nЧатов пока нет. Подключить: /track в нужном чате.")
        return
    lines = [f"• {esc(title) or 'без названия'} (<code>{chat_id}</code>)" for chat_id, title in chats]
    await message.answer(f"Экспедиция: {state}\n\n<b>Чаты:</b>\n" + "\n".join(lines))


async def _set_active(message: Message, active: bool) -> None:
    await db.set_setting("exp_active", "1" if active else "0")
    reset_cache()
    await message.answer(
        "🟢 Экспедиция идёт — сообщения считаются." if active
        else "⏸ Экспедиция на паузе — сообщения не считаются, баллы и рейтинг сохранены."
    )


@router.message(Command("expstart"), F.chat.type == "private", IsAdmin())
async def cmd_expstart(message: Message) -> None:
    await _set_active(message, True)


@router.message(Command("expstop"), F.chat.type == "private", IsAdmin())
async def cmd_expstop(message: Message) -> None:
    await _set_active(message, False)


@router.message(Command("addpoints"), F.chat.type == "private", IsAdmin())
async def cmd_addpoints(message: Message, command: CommandObject) -> None:
    parts = (command.args or "").split()
    try:
        user_id, amount = int(parts[0]), int(parts[1])
    except (IndexError, ValueError):
        await message.answer(
            "Напиши так: <code>/addpoints ID 10</code> — добавить,\n"
            "<code>/addpoints ID -10</code> — снять (например, за спам).\n"
            "ID человек узнаёт командой /myid."
        )
        return
    await db.add_points(user_id, amount, "manual", message.from_user.id)
    total = await db.get_points(user_id)
    await message.answer(f"Готово: {amount:+d} для <code>{user_id}</code>. Теперь у него {total} балл.")

