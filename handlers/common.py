"""Команды в группе и служебные. В личке /start, /help, /menu открывают меню на кнопках (handlers/menu.py).

В группе бот отвечает коротко и только тем, что сейчас доступно делегатам — ничего не палит.
"""
import html

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

import db
from chatutil import GROUP_REPLY_SECONDS, ephemeral
from handlers.expedition import is_active
from roles import ADMIN, MODERATOR, get_role, is_staff

router = Router()

GROUPS = {"group", "supergroup"}

HELP_EXPEDITION = (
    "/top – Лидерборд Экспедиции\n"
    "/points – Мои баллы и позиция в рейтинге\n"
)
HELP_STAFF = (
    "\n\n<b>📸 ФотоХант (для OC):</b>\n"
    "/task #хэштег текст — опубликовать задание в чат делегатов\n"
    "/tasks — все задания и статистика\n"
    "/close #хэштег — перестать принимать фото\n"
    "/open #хэштег — снова принимать фото\n"
    "Фото с хэштегами из чата будут приходить сюда с кнопками ✅ / ❌.\n\n"
    "<b>🧭 Экспедиция (для OC):</b>\n"
    "/top — лидерборд (в чате — опубликовать для всех, после открытия)\n"
    "/points — баллы (свои)\n"
    "/chats — статус и где считаются сообщения\n"
    "/word кофе — текстовое задание «предложение со словом» (бот проверяет сам)\n"
    "/wordoff — закрыть слово\n\n"
    "<b>🎲 Бинго (скрыто от делегатов):</b>\n"
    "/bingo — статус и статистика\n"
    "Делегаты сдают каждое из 14 заданий отдельно — они приходят на проверку с кнопками ✅ / ❌.\n\n"
    "/stats — сколько людей в базе бота"
)
HELP_ADMIN = (
    "\n\n<b>Только для админа:</b>\n"
    "/setchat — в чате или теме: принимать здесь фото ФотоХанта\n"
    "/track, /untrack — в чате или теме: считать / не считать сообщения\n"
    "/expstart — запустить Экспедицию / снять с паузы\n"
    "/expstop — пауза\n"
    "/addpoints 10 — reply на сообщение человека в группе: +10 (или -10)\n"
    "/addpoints @username 10 — то же из лички\n"
    "/check — проверить, всё ли бот видит и что сейчас настроено\n"
    "/bingo on, /bingo off — включить / выключить приём бинго\n"
    "/addmod ID — назначить модератора\n"
    "/delmod ID — снять модератора\n"
    "/mods — список модераторов"
)


async def user_help() -> str:
    """Что можно делегату прямо сейчас (для /help в группе). Пусто — нечего показывать."""
    if await is_active():
        return HELP_EXPEDITION.strip()
    return ""


@router.message(CommandStart(), F.chat.type.in_(GROUPS))
async def cmd_start_group(message: Message, bot: Bot) -> None:
    user = message.from_user
    await db.save_user(user.id, user.username, user.full_name)
    await _group_help(message, bot)


@router.message(Command("help"), F.chat.type.in_(GROUPS))
async def cmd_help_group(message: Message, bot: Bot) -> None:
    await _group_help(message, bot)


async def _group_help(message: Message, bot: Bot) -> None:
    """Список команд в группе — только то, что сейчас доступно. Ничего нет — молчим.
    Ответ исчезает через минуту вместе с командой."""
    text = await user_help()
    if not text:
        return
    await ephemeral(
        message, bot,
        "<b>Команды бота</b>\n" + text +
        "\nДля доступа к остальным разделам перейди в личные сообщения с Cupik и используй команду /start.",
        delay=GROUP_REPLY_SECONDS,
    )


@router.message(Command("commands"), F.chat.type == "private")
async def cmd_commands(message: Message) -> None:
    """Полный список команд для OC (на случай, если удобнее командами, чем кнопками)."""
    role = await get_role(message.from_user.id)
    if role not in (ADMIN, MODERATOR):
        return
    text = "<b>Команды</b> (то же самое есть на кнопках в /start)" + HELP_STAFF
    if role == ADMIN:
        text += HELP_ADMIN + "\n/setreviewchat — в чате OC: сюда приходят все фото на проверку"
    await message.answer(text)


@router.message(Command("myid"))
async def cmd_myid(message: Message) -> None:
    if not await is_staff(message.from_user.id):
        return  # делегатам эта команда не нужна
    text = f"Твой Telegram ID: <code>{message.from_user.id}</code>"
    if message.chat.type in GROUPS:
        from chatutil import delete_later, tell_user
        delete_later(message.bot, message.chat.id, [message.message_id], 0)
        await tell_user(message.bot, message.from_user.id, text, message)
        return
    await message.answer(text)
