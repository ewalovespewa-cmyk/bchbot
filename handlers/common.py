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
    "/points — мои баллы\n"
    "/myid — узнать свой Telegram ID\n"
    "/help — список команд"
)
HELP_STAFF = (
    "\n\n<b>📸 ФотоХант (для OC):</b>\n"
    "/task #хэштег текст — опубликовать задание в чат делегатов\n"
    "/task #хэштег 5 текст — то же, задание на 5 баллов\n"
    "/tasks — все задания и статистика\n"
    "/close #хэштег — перестать принимать фото\n"
    "/open #хэштег — снова принимать фото\n"
    "/top — рейтинг по баллам\n"
    "/stats — сколько людей в базе бота\n\n"
    "Фото с хэштегами из чата будут приходить сюда с кнопками ✅ / ❌."
)
HELP_ADMIN = (
    "\n\n<b>Только для админа:</b>\n"
    "/setchat — отправь в чате делегатов, чтобы бот работал там\n"
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


@router.message(Command("points"))
async def cmd_points(message: Message) -> None:
    total = await db.get_points(message.from_user.id)
    await message.answer(f"⭐ У тебя <b>{total}</b> балл(ов).")
