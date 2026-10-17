"""Команды для админа и модераторов."""
from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

import db
from roles import IsAdmin, IsStaff

router = Router()
router.message.filter(F.chat.type == "private")


def _parse_id(command: CommandObject) -> int | None:
    arg = (command.args or "").strip()
    return int(arg) if arg.isdigit() else None


@router.message(Command("stats"), IsStaff())
async def cmd_stats(message: Message) -> None:
    total = await db.count_users()
    await message.answer(f"Бота запустили: <b>{total}</b> чел.")


@router.message(Command("addmod"), IsAdmin())
async def cmd_addmod(message: Message, command: CommandObject) -> None:
    user_id = _parse_id(command)
    if user_id is None:
        await message.answer(
            "Напиши так: <code>/addmod 123456789</code>\n"
            "Свой ID человек может узнать, отправив боту /myid."
        )
        return
    added = await db.add_moderator(user_id, message.from_user.id)
    if not added:
        await message.answer("Этот человек уже модератор.")
        return
    await message.answer(f"✅ <code>{user_id}</code> теперь модератор.")
    try:
        await message.bot.send_message(
            user_id, "Тебя назначили модератором бота. Команды — /help"
        )
    except Exception:
        await message.answer(
            "Уведомить его не получилось: пусть сначала нажмёт /start в боте."
        )


@router.message(Command("delmod"), IsAdmin())
async def cmd_delmod(message: Message, command: CommandObject) -> None:
    user_id = _parse_id(command)
    if user_id is None:
        await message.answer("Напиши так: <code>/delmod 123456789</code>")
        return
    if await db.remove_moderator(user_id):
        await message.answer(f"Модератор <code>{user_id}</code> снят.")
    else:
        await message.answer("Такого модератора нет.")


@router.message(Command("mods"), IsAdmin())
async def cmd_mods(message: Message) -> None:
    mods = await db.list_moderators()
    if not mods:
        await message.answer("Модераторов пока нет. Добавить: /addmod ID")
        return
    lines = []
    for user_id, username, full_name in mods:
        name = full_name or "ещё не запускал бота"
        if username:
            name += f" (@{username})"
        lines.append(f"• <code>{user_id}</code> — {name}")
    await message.answer("<b>Модераторы:</b>\n" + "\n".join(lines))
