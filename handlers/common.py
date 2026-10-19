"""Команды для всех: работают и в личке, и в группе.

В группе бот отвечает коротко и только участницкими командами — команды OC в общий чат не попадают.
Пока Экспедиция скрыта, в /help о ней ни слова.
"""
import html

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

import db
from handlers.expedition import is_revealed
from roles import ADMIN, MODERATOR, ROLE_NAMES, get_role

router = Router()

GROUPS = {"group", "supergroup"}

HELP_PHOTOHUNT = "📸 ФотоХант: присылай фото в чат с хэштегом из задания."
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
    "/addmod ID — назначить модератора\n"
    "/delmod ID — снять модератора\n"
    "/mods — список модераторов"
)


async def user_help() -> str:
    text = "/start — начать\n"
    if await is_revealed():
        text += HELP_EXPEDITION
    text += "/myid — узнать свой Telegram ID\n/help — список команд\n\n" + HELP_PHOTOHUNT
    return text


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    user = message.from_user
    await db.save_user(user.id, user.username, user.full_name)
    if message.chat.type in GROUPS:
        await message.reply(f"Привет, {html.escape(user.first_name)}! 👋 Я бот Business Cup. Команды — /help")
        return
    role = await get_role(user.id)
    await message.answer(
        f"Привет, {html.escape(user.first_name)}! 👋\n"
        "Это бот Business Cup Hackathon.\n\n"
        f"Твоя роль: <b>{ROLE_NAMES[role]}</b>\n"
        "Список команд — /help"
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    text = await user_help()
    role = await get_role(message.from_user.id)
    if message.chat.type in GROUPS:
        if role in (ADMIN, MODERATOR):
            text += "\n\n<i>Команды OC — в личке у бота.</i>"
        await message.reply(text)
        return
    if role in (ADMIN, MODERATOR):
        text += HELP_STAFF
    if role == ADMIN:
        text += HELP_ADMIN
    await message.answer(text)


@router.message(Command("myid"))
async def cmd_myid(message: Message) -> None:
    text = f"Твой Telegram ID: <code>{message.from_user.id}</code>"
    if message.chat.type in GROUPS:
        await message.reply(text)
    else:
        await message.answer(text)

