"""Экспедиция — игра на весь проект: чем больше общаешься, тем выше в лидерборде.

Баллы:
- любое сообщение (текст, стикер, фото, гиф…) — EXP_MESSAGE_POINTS (1)
- голосовое или кружок — EXP_VOICE_POINTS (3)
- день, когда в ФотоХанте засчитали хотя бы одно фото — EXP_PHOTOHUNT_DAY_POINTS (5),
  начисляется в handlers/photohunt.py (дни копятся всегда, даже пока Экспедиция скрыта)
- ручные корректировки OC — /addpoints

Секретность: до первого /expstart Экспедиция скрыта. Делегатам /top и /points не отвечают
(как на несуществующую команду), в /help и текстах ФотоХанта она не упоминается,
сообщения не считаются. После /expstart — открыта; /expstop ставит на паузу (рейтинг виден).

Где считаются сообщения: только там, где админ отправил /track. В чате с темами /track,
отправленный внутри темы (например «Флуд»), подключает только эту тему.
Не считаются: команды, служебные сообщения, OC, боты, сообщения от имени канала,
сообщения одного человека чаще раза в EXP_COOLDOWN_SECONDS.
Если включена интеграция с ботом регистрации, подсчёт стоит ПОСЛЕ её фильтра доступа.
"""
import html
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from aiogram import BaseMiddleware, Bot, F, Router
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
GROUP_TOP_COOLDOWN = 60  # в чате лидерборд от делегатов — не чаще раза в минуту


def esc(text: str | None) -> str:
    return html.escape(text or "")


# ---------------------------------------------------------------- состояние (с кэшем)

class _State:
    tracks: set[tuple[int, int]] | None = None
    active: bool | None = None
    revealed: bool | None = None
    known_users: set[int] = set()
    last_counted: dict[int, float] = {}
    group_top_at: dict[int, float] = {}


async def tracks() -> set[tuple[int, int]]:
    if _State.tracks is None:
        _State.tracks = await db.exp_tracks()
    return _State.tracks


async def is_active() -> bool:
    """Идёт ли подсчёт сообщений. По умолчанию — нет, пока админ не сделает /expstart."""
    if _State.active is None:
        _State.active = (await db.get_setting("exp_active")) == "1"
    return _State.active


async def is_revealed() -> bool:
    """Знают ли делегаты об Экспедиции: да после первого /expstart."""
    if _State.revealed is None:
        _State.revealed = (await db.get_setting("exp_revealed")) == "1"
    return _State.revealed


async def visible_to(user_id: int) -> bool:
    return await is_revealed() or await is_staff(user_id)


def reset_cache() -> None:
    _State.tracks = None
    _State.active = None
    _State.revealed = None


def thread_of(message: Message) -> int:
    """Номер темы в чате с темами; 0 — обычный чат или «Общая» тема."""
    return message.message_thread_id if message.is_topic_message and message.message_thread_id else 0


def topic_title(message: Message) -> str | None:
    reply = message.reply_to_message
    if message.is_topic_message and reply and reply.forum_topic_created:
        return reply.forum_topic_created.name
    return None


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


async def is_tracked(message: Message) -> bool:
    t = await tracks()
    return (message.chat.id, 0) in t or (message.chat.id, thread_of(message)) in t


async def count_message(message: Message) -> bool:
    """Начисляет баллы за сообщение, если оно подходит. True — посчитали."""
    user = message.from_user
    if message.chat.type not in GROUPS or user is None or user.is_bot:
        return False
    if message.sender_chat is not None or message.is_automatic_forward:
        return False  # от имени канала/группы или автопересылка из канала
    if not await is_active() or not await is_tracked(message):
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
    """Считает каждое сообщение в отслеживаемых чатах/темах и пропускает его дальше —
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


# ---------------------------------------------------------------- лидерборд и баллы

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
    user_id = message.from_user.id
    if not await visible_to(user_id):
        return  # Экспедиция ещё секрет — молчим, как на несуществующую команду
    staff = await is_staff(user_id)
    text = format_board(await ranking(), None if staff else user_id)
    if staff and not await is_revealed():
        text = "🔒 <i>Экспедиция скрыта — это видит только OC. Открыть: /expstart</i>\n\n" + text
    await message.answer(text)


@router.message(Command("top"), F.chat.type.in_(GROUPS))
async def cmd_top_group(message: Message) -> None:
    if not await is_revealed():
        return  # в общем чате до открытия молчим даже для OC
    if not await is_staff(message.from_user.id):
        now = time.monotonic()
        if now - _State.group_top_at.get(message.chat.id, -1e9) < GROUP_TOP_COOLDOWN:
            return  # только что публиковали — не засоряем чат
        _State.group_top_at[message.chat.id] = now
    await message.answer(format_board(await ranking()))


@router.message(Command("points"))
async def cmd_points(message: Message) -> None:
    user_id = message.from_user.id
    if not await visible_to(user_id):
        return
    if await is_staff(user_id):
        await message.answer(
            "Ты OC — тебе баллы не начисляются (и модераторам тоже). "
            "Проверяй с обычного аккаунта. Рейтинг участников — /top, состояние бота — /check."
        )
        return
    total = await db.get_points(user_id)
    place = next((r[0] for r in await ranking() if r[1] == user_id), None)

    if message.chat.type in GROUPS:
        where = f", {place} место" if place else ""
        await message.reply(f"🧭 {esc(message.from_user.first_name)}: {total} балл.{where}")
        return

    b = await db.points_breakdown(user_id)
    lines = [
        f"🧭 <b>Твоя Экспедиция: {total} балл.</b>",
        f"Место в рейтинге: <b>{place}</b>" if place else "В рейтинге тебя пока нет",
        "",
        f"💬 Сообщения: {b['messages']}",
        f"🎙 Голосовые и кружки: {b['voices']}",
        f"📸 Дней в ФотоХанте: {b['photohunt_days']} (+{b['photohunt_points']})",
    ]
    if b["word_count"]:
        lines.append(f"✍️ Задания со словами: {b['word_count']} (+{b['word_points']})")
    if b["photo_count"]:
        lines.append(f"🖼 Фото-задания: {b['photo_count']} (+{b['photo_points']})")
    if b["adjust_points"]:
        lines.append(f"🛠 Корректировка OC: {b['adjust_points']:+d}")
    await message.answer("\n".join(lines))


# ---------------------------------------------------------------- управление (OC)

async def _quiet_confirm(message: Message, bot: Bot, text: str) -> None:
    """Подтверждение без шума в чате: удаляем команду и пишем админу в личку."""
    try:
        await message.delete()
    except Exception:
        pass  # у бота нет права удалять сообщения — не страшно
    try:
        await bot.send_message(message.from_user.id, text)
    except Exception:
        # админ ещё не нажал /start у бота — тогда коротко отвечаем в чате, без подробностей
        await message.answer("✅")


def _where(message: Message) -> str:
    chat = esc(message.chat.title) or "чат"
    if thread_of(message):
        return f"тема «{esc(topic_title(message)) or thread_of(message)}» в «{chat}»"
    return f"весь чат «{chat}»"


@router.message(Command("track"), F.chat.type.in_(GROUPS), IsAdmin())
async def cmd_track(message: Message, bot: Bot) -> None:
    title = message.chat.title
    if thread_of(message):
        title = f"{message.chat.title} → {topic_title(message) or thread_of(message)}"
    added = await db.add_exp_track(message.chat.id, thread_of(message), title)
    reset_cache()
    state = "" if await is_active() else "\n\nПодсчёт начнётся после /expstart."
    from handlers.diagnostics import FIX_TEXT, chat_access
    ok, _, _ = await chat_access(bot, message.chat.id)
    if not ok:
        state += "\n\n⚠️ <b>Бот сейчас не видит обычные сообщения в этом чате</b> — баллы считаться не будут.\n" + FIX_TEXT
    if added:
        await _quiet_confirm(message, bot, f"🧭 Экспедиция будет считать: {_where(message)}.{state}")
    else:
        await _quiet_confirm(message, bot, f"Уже подключено: {_where(message)}.")


@router.message(Command("untrack"), F.chat.type.in_(GROUPS), IsAdmin())
async def cmd_untrack(message: Message, bot: Bot) -> None:
    removed = await db.remove_exp_track(message.chat.id, thread_of(message))
    reset_cache()
    if removed:
        await _quiet_confirm(message, bot, f"Больше не считается: {_where(message)}.")
    else:
        await _quiet_confirm(message, bot, f"Это и так не подключено: {_where(message)}.")


@router.message(Command(commands=["track", "untrack"]), F.chat.type == "private", IsAdmin())
async def cmd_track_private(message: Message) -> None:
    await message.answer(
        "Эту команду нужно отправить <b>в самом чате</b>. Если в чате есть темы — "
        "внутри нужной темы (например «Флуд»): тогда считаться будет только она."
    )


async def _status_line() -> str:
    if await is_active():
        return "🟢 идёт"
    if await is_revealed():
        return "⏸ на паузе"
    return "🔒 скрыта (делегаты о ней не знают)"


@router.message(Command("chats"), F.chat.type == "private", IsStaff())
async def cmd_chats(message: Message) -> None:
    rows = await db.list_exp_tracks()
    head = f"Экспедиция: {await _status_line()}"
    if not rows:
        await message.answer(f"{head}\n\nНичего не подключено. В нужном чате или теме отправь /track.")
        return
    lines = []
    for chat_id, thread_id, title in rows:
        kind = "тема" if thread_id else "весь чат"
        lines.append(f"• {esc(title) or 'без названия'} — {kind}")
    await message.answer(f"{head}\n\n<b>Считаются:</b>\n" + "\n".join(lines))


@router.message(Command("expstart"), F.chat.type == "private", IsAdmin())
async def cmd_expstart(message: Message) -> None:
    first_time = not await is_revealed()
    await db.set_setting("exp_active", "1")
    await db.set_setting("exp_revealed", "1")
    reset_cache()
    text = "🟢 Экспедиция идёт — сообщения считаются."
    if first_time:
        text = (
            "🚀 Экспедиция открыта! Сообщения считаются, делегатам теперь доступны /top и /points.\n"
            "Бот сам ничего в чат не пишет — объявите старт своим постом "
            "или отправьте /top в чат, чтобы показать рейтинг."
        )
    if not await tracks():
        text += "\n\n⚠️ Пока не подключено ни одного чата — отправь /track в теме «Флуд»."
    await message.answer(text)


@router.message(Command("expstop"), F.chat.type == "private", IsAdmin())
async def cmd_expstop(message: Message) -> None:
    await db.set_setting("exp_active", "0")
    reset_cache()
    await message.answer("⏸ Экспедиция на паузе — сообщения не считаются, баллы и рейтинг сохранены.")


ADDPOINTS_HELP = (
    "Как начислить или снять баллы:\n"
    "• <b>в группе</b>: ответь (reply) на сообщение человека командой <code>/addpoints 10</code> "
    "(или <code>-10</code>) — команда исчезнет, подтверждение придёт тебе в личку;\n"
    "• <b>в личке</b>: <code>/addpoints @username 10</code> или <code>/addpoints ID 10</code>."
)


def _amount(text: str) -> int | None:
    try:
        value = int(text)
    except ValueError:
        return None
    return value or None


async def _apply_points(user_id: int, amount: int, by: int, name: str) -> str:
    await db.add_points(user_id, amount, "manual", by)
    total = await db.get_points(user_id)
    return f"🛠 {amount:+d} для {esc(name)}. Теперь у него {total} балл."


@router.message(Command("addpoints"), F.chat.type.in_(GROUPS), IsAdmin())
async def cmd_addpoints_group(message: Message, command: CommandObject, bot: Bot) -> None:
    target = message.reply_to_message.from_user if message.reply_to_message else None
    amount = _amount((command.args or "").strip().split(" ")[0]) if command.args else None
    if target is None or target.is_bot or amount is None:
        await _quiet_confirm(message, bot, ADDPOINTS_HELP)
        return
    await db.save_user(target.id, target.username, target.full_name)
    await _quiet_confirm(message, bot, await _apply_points(target.id, amount, message.from_user.id, target.full_name))


@router.message(Command("addpoints"), F.chat.type == "private", IsAdmin())
async def cmd_addpoints(message: Message, command: CommandObject) -> None:
    parts = (command.args or "").split()
    amount = _amount(parts[1]) if len(parts) >= 2 else None
    if amount is None:
        await message.answer(ADDPOINTS_HELP)
        return
    who = parts[0]
    if who.startswith("@"):
        row = await db.find_user_by_username(who)
        if row is None:
            await message.answer(
                f"Не знаю {esc(who)} — бот ещё не видел его сообщений. "
                "Проще ответить на его сообщение в группе: <code>/addpoints 10</code>"
            )
            return
        user_id, name = row
    elif who.lstrip("-").isdigit():
        user_id, name = int(who), who
    else:
        await message.answer(ADDPOINTS_HELP)
        return
    await message.answer(await _apply_points(user_id, amount, message.from_user.id, name or str(user_id)))
