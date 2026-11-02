"""Команды в группе и служебные. В личке /start, /help, /menu открывают меню на кнопках (handlers/menu.py).

В группе бот отвечает коротко и только тем, что сейчас доступно делегатам — ничего не палит.
"""
import html

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

import db
from chatutil import to_menu
from handlers.expedition import is_active
from roles import ADMIN, MODERATOR, get_role, is_staff

router = Router()

GROUPS = {"group", "supergroup"}

HELP_EXPEDITION = (
    "/top — лидерборд Экспедиции 🧭\n"
    "/points — мои баллы и место\n"
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
    "/phase — какая сейчас фаза\n\n"
    "<b>✍️ Фаза 1 — слова:</b>\n"
    "/word кофе — задание «предложение со словом» (бот проверяет сам)\n"
    "/word кофе 10 — то же за 10 баллов\n"
    "/wordoff — закрыть слово · /words — история\n\n"
    "<b>🖼 Фаза 2 — фото:</b>\n"
    "/photo #тег текст — фото-задание (проверка ✅/❌ тут)\n"
    "/photo #тег 15 текст — за 15 баллов\n"
    "/photos — список · /photoclose #тег, /photoopen #тег\n\n"
    "<b>🎲 Бинго (скрыто от делегатов):</b>\n"
    "/bingo — статус и статистика\n"
    "Делегаты шлют боту в личку альбом из 9 фото — он придёт сюда с кнопками ✅ / ❌.\n\n"
    "/stats — сколько людей в базе бота"
)
HELP_ADMIN = (
    "\n\n<b>Только для админа:</b>\n"
    "/setchat — в чате или теме: принимать здесь фото ФотоХанта\n"
    "/track, /untrack — в чате или теме: считать / не считать сообщения\n"
    "/phase 1 [текст] — начать фазу (1, 2, 3) с объявлением в чат; открывает Экспедицию\n"
    "/phase end — закончить фазу: объявление в чат, задания фазы закрываются, баллы сохраняются\n"
    "/setphasechat — в чате: куда публиковать задания фаз\n"
    "/expstart — открыть Экспедицию без фазы / снять с паузы\n"
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
    await to_menu(message, bot)  # без ответа в чате: кнопка в личку, сама исчезнет


@router.message(Command("help"), F.chat.type.in_(GROUPS))
async def cmd_help_group(message: Message, bot: Bot) -> None:
    await to_menu(message, bot)


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
