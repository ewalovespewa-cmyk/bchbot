"""Команды, доступные всем."""
from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

import db
from roles import ADMIN, MODERATOR, ROLE_NAMES, get_role

router = Router()

HELP_USER = (
    "/start — начать\n"
    "/help — список команд\n"
    "/myid — узнать свой Telegram ID"
)
HELP_STAFF = (
    "\n\n<b>Для команды бота:</b>\n"
    "/stats — сколько людей запустили бота"
)
HELP_ADMIN = (
    "\n\n<b>Только для админа:</b>\n"
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
