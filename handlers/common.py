"""Команды, доступные всем (в личке с ботом)."""
from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

import db
from roles import ADMIN, MODERATOR, ROLE_NAMES, get_role

router = Router()
router.message.filter(F.chat.type == "private")

HELP_USER = (
    "/start — начать\n"
    "/top — лидерборд Экспедиции 🧭\n"
    "/points — мои баллы и место\n"
    "/myid — узнать свой Telegram ID\n"
    "/help — список команд"
)
HELP_STAFF = (
    "\n\n<b>📸 ФотоХант (для OC):</b>\n"
    "/task #хэштег текст — опубликовать задание в чат делегатов\n"
    "/tasks — все задания и статистика\n"
    "/close #хэштег — перестать принимать фото\n"
    "/open #хэштег — снова принимать фото\n"
    "Фото с хэштегами из чата будут приходить сюда с кнопками ✅ / ❌.\n\n"
    "<b>🧭 Экспедиция (для OC):</b>\n"
    "/top — лидерборд (в чате — опубликовать его для всех)\n"
    "/chats — какие чаты считаются\n"
    "/stats — сколько людей в базе бота"
)
HELP_ADMIN = (
    "\n\n<b>Только для админа:</b>\n"
    "/setchat — в чате: принимать здесь фото ФотоХанта\n"
    "/track, /untrack — в чате: считать / не считать его сообщения\n"
    "/expstart, /expstop — запустить / поставить Экспедицию на паузу\n"
    "/addpoints ID 10 — добавить баллы (или -10 — снять)\n"
    "/addmod ID — назначить модератора\n"
    "/delmod ID — снять модератора\n"
    "/mods — список модераторов"
)


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    user = message.from_user
    await db.save_user(user.id, user.username, user.full_name)
    role = await get_role(user.id)
    text = (
        f"Привет, {user.first_name}! 👋\n"
        "Это бот Business Cup Hackathon.\n\n"
        f"Твоя роль: <b>{ROLE_NAMES[role]}</b>\n"
        "Список команд — /help"
    )
    await message.answer(text)


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    role = await get_role(message.from_user.id)
    text = HELP_USER
    if role in (ADMIN, MODERATOR):
        text += HELP_STAFF
    if role == ADMIN:
        text += HELP_ADMIN
    await message.answer(text)


@router.message(Command("myid"))
async def cmd_myid(message: Message) -> None:
    await message.answer(f"Твой Telegram ID: <code>{message.from_user.id}</code>")
