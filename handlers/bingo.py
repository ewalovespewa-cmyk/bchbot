"""Бинго — офлайн-игра, которую бот только принимает и проверяет. Полностью скрыта от делегатов:
никаких команд, рассылок и упоминаний в /help.

Как работает:
- Админ включает приём: /bingo on (выключает: /bingo off). Пока приём выключен, бот молча
  игнорирует фото в личке — ничего не палится.
- Делегат присылает боту в личку ОДИН альбом ровно из 9 фото. Меньше/больше, по одному,
  файлами — бот просит прислать все 9 заново одним альбомом. Если подключён бот регистрации,
  сдать бинго могут только отметившиеся на входе сегодня.
- OC получают 9 фото с номерами №1–№9 и кнопки ✅ Засчитать / ❌ Не засчитать.
  ❌ открывает сетку 3×3 с номерами: отмечаешь непрошедшие фото и жмёшь «На переработку».
  Делегат получает список номеров; чтобы засчитать, он присылает снова все 9 фото.
- Решает первый нажавший; у остальных OC сообщение обновляется.
- Баллы в Экспедицию за бинго: BINGO_POINTS (по умолчанию 0 — не начисляются).
"""
import asyncio
import html
import logging
import os

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    Message,
)

import db
import db_bingo
from integration import access as bc_access
from integration import config as bc_config
from integration.gate import NEED_CHECKIN_TEXT
from roles import IsAdmin, IsStaff, is_staff, staff_ids

router = Router()
log = logging.getLogger(__name__)

CELLS = 9
ALBUM_WAIT = 2.5  # секунд ждём остальные фото альбома
BINGO_POINTS = int(os.getenv("BINGO_POINTS", "0"))

RESEND = "Чтобы бинго засчитали, отправь <b>все 9 фото одним альбомом</b> (выбери 9 фото и отправь разом)."


def esc(text: str | None) -> str:
    return html.escape(text or "")


async def is_open() -> bool:
    return (await db.get_setting("bingo_open")) == "1"


# ---------------------------------------------------------------- управление (OC)

@router.message(Command("bingo"), F.chat.type == "private", IsStaff())
async def cmd_bingo(message: Message, command: CommandObject) -> None:
    arg = (command.args or "").strip().lower()
    if arg in {"on", "off", "вкл", "выкл"}:
        if not await IsAdmin()(message):
            await message.answer("Включать и выключать бинго может только админ.")
            return
        opened = arg in {"on", "вкл"}
        await db.set_setting("bingo_open", "1" if opened else "0")
        await message.answer(
            "🎲 Приём бинго <b>включён</b>: делегаты могут присылать боту в личку альбом из 9 фото."
            if opened else
            "🎲 Приём бинго <b>выключен</b>: фото в личке бот молча игнорирует."
        )
        return
    s = await db_bingo.stats()
    await message.answer(
        f"🎲 <b>Бинго</b> (скрыто от делегатов)\n"
        f"Приём: {'🟢 включён' if await is_open() else '⚪️ выключен'}\n\n"
        f"Ждут проверки: {s['pending']}\n"
        f"Засчитано: {s['approved']} (людей: {s['people_done']})\n"
        f"На переработке было: {s['rejected']}\n\n"
        "Включить/выключить приём: <code>/bingo on</code> · <code>/bingo off</code>"
    )


# ---------------------------------------------------------------- приём альбома в личке

class _Album:
    def __init__(self, user, chat_id: int):
        self.user = user
        self.chat_id = chat_id
        self.items: list[tuple[int, str | None]] = []  # (message_id, file_id фото или None)
        self.task: asyncio.Task | None = None


_albums: dict[str, _Album] = {}


@router.message(F.chat.type == "private", F.photo | F.document | F.video | F.animation)
async def on_private_media(message: Message, bot: Bot) -> None:
    if not await is_open():
        return  # бинго не идёт — молчим, ничего не палим
    if message.media_group_id is None:
        await message.answer(f"🎲 Одно фото не засчитать. {RESEND}")
        return
    key = message.media_group_id
    album = _albums.get(key)
    if album is None:
        album = _albums[key] = _Album(message.from_user, message.chat.id)
    album.items.append((message.message_id, message.photo[-1].file_id if message.photo else None))
    if album.task:
        album.task.cancel()
    album.task = asyncio.create_task(_finish_later(bot, key))


async def _finish_later(bot: Bot, key: str) -> None:
    try:
        await asyncio.sleep(ALBUM_WAIT)
    except asyncio.CancelledError:
        return
    album = _albums.pop(key, None)
    if album is None:
        return
    try:
        await finish_album(bot, album)
    except Exception:
        log.exception("Бинго: не смог обработать альбом")


async def finish_album(bot: Bot, album: _Album) -> None:
    user = album.user
    items = sorted(album.items)
    if any(f is None for _, f in items):
        await bot.send_message(album.chat_id, "🎲 Пришли именно фото (не файлами и не видео). " + RESEND)
        return
    if len(items) != CELLS:
        await bot.send_message(
            album.chat_id, f"🎲 В альбоме {len(items)} фото, а нужно ровно {CELLS}. {RESEND}"
        )
        return
    if bc_config.ENABLED and not await is_staff(user.id) and not await bc_access.is_checked_in(user.id):
        await bot.send_message(album.chat_id, NEED_CHECKIN_TEXT)
        return
    status = await db_bingo.user_status(user.id)
    if status == "approved":
        await bot.send_message(album.chat_id, "🎲 Твоё бинго уже засчитано 🎉")
        return
    if status == "pending":
        await bot.send_message(album.chat_id, "🎲 Твоё бинго ещё на проверке ⏳ Дождись ответа.")
        return

    await db.save_user(user.id, user.username, user.full_name)
    sub_id = await db_bingo.create(user.id, [f for _, f in items])
    await bot.send_message(album.chat_id, "📨 Бинго принято на проверку! Ответ придёт сюда.")
    await send_to_staff(bot, sub_id)


# ---------------------------------------------------------------- проверка OC

def _who(sub) -> str:
    who = esc(sub["full_name"]) or str(sub["user_id"])
    if sub["username"]:
        who += f" (@{esc(sub['username'])})"
    return who


def _header(sub) -> str:
    return f"🎲 <b>Бинго</b> от {_who(sub)}\n9 фото — выше, подписаны №1–№9."


def _main_kb(sub_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Засчитать", callback_data=f"bg:a:{sub_id}")],
        [InlineKeyboardButton(text="❌ Не засчитать", callback_data=f"bg:r:{sub_id}:0")],
    ])


def _select_kb(sub_id: int, mask: int) -> InlineKeyboardMarkup:
    rows = []
    for r in range(3):
        row = []
        for c in range(3):
            i = r * 3 + c + 1
            bit = 1 << (i - 1)
            row.append(InlineKeyboardButton(
                text=f"❌ {i}" if mask & bit else str(i),
                callback_data=f"bg:r:{sub_id}:{mask ^ bit}",
            ))
        rows.append(row)
    if mask:
        rows.append([InlineKeyboardButton(text="📨 Отправить на переработку", callback_data=f"bg:s:{sub_id}:{mask}")])
    rows.append([InlineKeyboardButton(text="↩️ Назад", callback_data=f"bg:b:{sub_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _numbers(mask: int) -> list[int]:
    return [i for i in range(1, CELLS + 1) if mask & (1 << (i - 1))]


async def send_to_staff(bot: Bot, sub_id: int) -> None:
    sub = await db_bingo.get(sub_id)
    files = await db_bingo.photos(sub_id)
    media = [InputMediaPhoto(media=f, caption=f"№{i}") for i, f in enumerate(files, 1)]
    for staff_id in await staff_ids():
        try:
            await bot.send_media_group(staff_id, media=media)
            sent = await bot.send_message(staff_id, _header(sub), reply_markup=_main_kb(sub_id))
            await db_bingo.add_review_msg(sub_id, staff_id, sent.message_id)
        except Exception:
            log.warning("Бинго %s не доставлено OC %s (нет /start?)", sub_id, staff_id)


async def _finish_review(bot: Bot, sub_id: int, decision: str) -> None:
    sub = await db_bingo.get(sub_id)
    text = _header(sub) + "\n\n" + decision
    for chat_id, message_id in await db_bingo.review_msgs(sub_id):
        try:
            await bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, reply_markup=None)
        except Exception:
            pass


@router.callback_query(F.data.startswith("bg:"))
async def on_bingo_button(callback: CallbackQuery, bot: Bot) -> None:
    if not await is_staff(callback.from_user.id):
        await callback.answer("Это может делать только OC.", show_alert=True)
        return
    parts = callback.data.split(":")
    try:
        action, sub_id = parts[1], int(parts[2])
        mask = int(parts[3]) if len(parts) > 3 else 0
    except (IndexError, ValueError):
        await callback.answer()
        return
    sub = await db_bingo.get(sub_id)
    if sub is None or sub["status"] != "pending":
        await callback.answer("Это бинго уже проверил кто-то другой.", show_alert=True)
        return
    reviewer = esc(callback.from_user.full_name)

    if action == "r":  # режим выбора непрошедших фото
        await callback.message.edit_text(
            _header(sub) + "\n\n<b>Отметь фото, которые не прошли</b>, и нажми «Отправить на переработку».",
            reply_markup=_select_kb(sub_id, mask),
        )
        await callback.answer()
        return
    if action == "b":
        await callback.message.edit_text(_header(sub), reply_markup=_main_kb(sub_id))
        await callback.answer()
        return

    if action == "a":
        if not await db_bingo.decide(sub_id, True, callback.from_user.id):
            await callback.answer("Это бинго уже проверил кто-то другой.", show_alert=True)
            return
        if BINGO_POINTS:
            await db.add_points(sub["user_id"], BINGO_POINTS, "bingo", sub_id)
        await _finish_review(bot, sub_id, f"✅ Засчитал(а): {reviewer}")
        await _notify(bot, sub["user_id"], "🎲 Твоё бинго засчитано! 🎉")
        await callback.answer("Засчитано ✅")
        return

    if action == "s":
        nums = _numbers(mask)
        if not nums:
            await callback.answer("Отметь хотя бы одно фото.", show_alert=True)
            return
        if not await db_bingo.decide(sub_id, False, callback.from_user.id, ",".join(map(str, nums))):
            await callback.answer("Это бинго уже проверил кто-то другой.", show_alert=True)
            return
        listed = ", ".join(f"№{n}" for n in nums)
        await _finish_review(bot, sub_id, f"❌ На переработку: {listed} — {reviewer}")
        await _notify(
            bot, sub["user_id"],
            f"🎲 Бинго пока не засчитано. Переделай фото: <b>{listed}</b>.\n\n{RESEND}",
        )
        await callback.answer("Отправлено на переработку")
        return
    await callback.answer()


async def _notify(bot: Bot, user_id: int, text: str) -> None:
    try:
        await bot.send_message(user_id, text)
    except Exception:
        log.warning("Не смог написать делегату %s про бинго", user_id)
