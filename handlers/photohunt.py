"""ФотоХант.

Как это работает:
1. Админ в чате делегатов пишет /setchat — бот запоминает, куда публиковать задания
   и где ловить фото (если чат с темами — запоминается именно эта тема).
2. OC пишет боту в личку: /task #хэштег текст задания — бот публикует задание в чат.
3. Делегат кидает в чат фото с этим хэштегом в подписи.
4. Бот присылает фото админу и всем модераторам в личку с кнопками ✅ / ❌.
5. Первый, кто нажал, принимает решение: у остальных сообщение обновляется,
   делегату бот отвечает в чате.
6. Связь с Экспедицией: за каждый день, когда у человека засчитали хотя бы одно фото,
   он получает бонус EXP_PHOTOHUNT_DAY_POINTS (по умолчанию +5). День — когда фото прислали.
"""
import html
import logging
import re

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    ReplyParameters,
)

import db
from config import EXP_PHOTOHUNT_DAY_POINTS, LOCAL_TZ
from roles import IsAdmin, IsStaff, is_staff, staff_ids

router = Router()
log = logging.getLogger(__name__)

HASHTAG_RE = re.compile(r"^#?(\w{2,64})$")


def esc(text: str | None) -> str:
    return html.escape(text or "")


# ---------------------------------------------------------------- настройка чата

async def get_photo_chat() -> tuple[int | None, int | None]:
    chat_id = await db.get_setting("photo_chat_id")
    thread_id = await db.get_setting("photo_thread_id")
    return (int(chat_id) if chat_id else None, int(thread_id) if thread_id else None)


@router.message(Command("setchat"), F.chat.type.in_({"group", "supergroup"}), IsAdmin())
async def cmd_setchat(message: Message) -> None:
    thread_id = message.message_thread_id if message.is_topic_message else None
    await db.set_setting("photo_chat_id", str(message.chat.id))
    await db.set_setting("photo_thread_id", str(thread_id) if thread_id else None)
    where = "в этой теме" if thread_id else "в этом чате"
    await message.reply(f"✅ ФотоХант теперь работает {where}. Задания буду публиковать сюда.")


@router.message(Command("setchat"), F.chat.type == "private", IsAdmin())
async def cmd_setchat_private(message: Message) -> None:
    await message.answer(
        "Эту команду нужно отправить <b>в самом чате делегатов</b> "
        "(или в нужной теме, если в чате есть темы), куда добавлен бот."
    )


# ---------------------------------------------------------------- задания (для OC, в личке)

def parse_task_args(args: str | None) -> tuple[str, str] | None:
    """'#селфи Сфоткайся с ментором' -> ('селфи', 'Сфоткайся с ментором')."""
    parts = (args or "").split(maxsplit=1)
    if len(parts) < 2:
        return None
    m = HASHTAG_RE.match(parts[0])
    if not m or not parts[1].strip():
        return None
    return m.group(1).lower(), parts[1].strip()


@router.message(Command("task"), F.chat.type == "private", IsStaff())
async def cmd_task(message: Message, command: CommandObject, bot: Bot) -> None:
    parsed = parse_task_args(command.args)
    if not parsed:
        await message.answer(
            "Напиши так:\n<code>/task #хэштег текст задания</code>\n\n"
            "Хэштег — одно слово без пробелов (буквы, цифры, _)."
        )
        return
    hashtag, text = parsed

    chat_id, thread_id = await get_photo_chat()
    if not chat_id:
        await message.answer(
            "Сначала укажи чат делегатов: добавь туда бота и отправь в чате /setchat."
        )
        return

    task_id = await db.create_task(hashtag, text, 0, message.from_user.id)
    if task_id is None:
        await message.answer(f"Задание с хэштегом #{esc(hashtag)} уже есть. Придумай другой.")
        return

    post = (
        "📸 <b>Новое задание ФотоХанта!</b>\n\n"
        f"{esc(text)}\n\n"
        f"Присылайте фото в этот чат с хэштегом #{esc(hashtag)} в подписи.\n"
        f"Засчитанное фото = <b>+{EXP_PHOTOHUNT_DAY_POINTS}</b> в Экспедицию (бонус раз в день) 🧭"
    )
    try:
        await bot.send_message(chat_id, post, message_thread_id=thread_id)
    except Exception as e:
        log.exception("Не удалось опубликовать задание")
        await db.set_task_active(hashtag, False)
        await message.answer(
            f"Задание сохранено, но опубликовать его в чат не получилось: <code>{esc(str(e))}</code>\n"
            "Проверь, что бот всё ещё в чате и может писать. Задание пока выключено, "
            f"включить: /open #{esc(hashtag)}"
        )
        return
    await message.answer(f"✅ Задание #{esc(hashtag)} опубликовано в чат.")


@router.message(Command("tasks"), IsStaff())
async def cmd_tasks(message: Message) -> None:
    tasks = await db.list_tasks()
    if not tasks:
        await message.answer("Заданий пока нет. Создать: /task #хэштег текст")
        return
    lines = []
    for t in tasks:
        state = "🟢" if t["active"] else "⚪️ закрыто"
        lines.append(
            f"{state} #{esc(t['hashtag'])} — {esc(t['text'])}\n"
            f"    засчитано: {t['approved']} · ждут проверки: {t['pending']}"
        )
    await message.answer("<b>Задания ФотоХанта:</b>\n\n" + "\n\n".join(lines))


async def _toggle_task(message: Message, command: CommandObject, active: bool) -> None:
    m = HASHTAG_RE.match((command.args or "").strip())
    if not m:
        cmd = "open" if active else "close"
        await message.answer(f"Напиши так: <code>/{cmd} #хэштег</code>")
        return
    hashtag = m.group(1).lower()
    if not await db.set_task_active(hashtag, active):
        await message.answer(f"Задания #{esc(hashtag)} нет.")
        return
    if active:
        await message.answer(f"🟢 Задание #{esc(hashtag)} снова принимает фото.")
    else:
        await message.answer(f"⚪️ Задание #{esc(hashtag)} закрыто, новые фото не принимаются.")


@router.message(Command("close"), IsStaff())
async def cmd_close(message: Message, command: CommandObject) -> None:
    await _toggle_task(message, command, False)


@router.message(Command("open"), IsStaff())
async def cmd_open(message: Message, command: CommandObject) -> None:
    await _toggle_task(message, command, True)


# ---------------------------------------------------------------- ловим фото в чате делегатов

def extract_hashtags(message: Message) -> list[str]:
    text = message.caption or message.text or ""
    entities = message.caption_entities or message.entities or []
    tags = []
    for ent in entities:
        if ent.type == "hashtag":
            tag = ent.extract_from(text).lstrip("#").lower()
            if tag and tag not in tags:
                tags.append(tag)
    return tags


def get_image(message: Message) -> tuple[str, bool] | None:
    """(file_id, это_файл?) — принимаем обычное фото или картинку, отправленную файлом."""
    if message.photo:
        return message.photo[-1].file_id, False
    doc = message.document
    if doc and (doc.mime_type or "").startswith("image/"):
        return doc.file_id, True
    return None


def message_link(chat_id: int, message_id: int, thread_id: int | None) -> str | None:
    s = str(chat_id)
    if not s.startswith("-100"):
        return None  # у обычных (не супер-) групп ссылок на сообщения нет
    link = f"https://t.me/c/{s[4:]}/{message_id}"
    return link + (f"?thread={thread_id}" if thread_id else "")


def review_keyboard(submission_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="✅ Засчитать", callback_data=f"ph:a:{submission_id}"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"ph:r:{submission_id}"),
        ]]
    )


def review_caption(sub, decision: str | None = None) -> str:
    who = esc(sub["full_name"]) or str(sub["user_id"])
    if sub["username"]:
        who += f" (@{esc(sub['username'])})"
    lines = [
        f"📸 <b>#{esc(sub['hashtag'])}</b> — {esc(sub['task_text'])}",
        f"От: {who}",
    ]
    link = message_link(sub["chat_id"], sub["message_id"], None)
    if link:
        lines.append(f'<a href="{link}">Открыть в чате</a>')
    if decision:
        lines.append("")
        lines.append(decision)
    return "\n".join(lines)


@router.message(F.chat.type.in_({"group", "supergroup"}), F.photo | F.document)
async def on_group_photo(message: Message, bot: Bot) -> None:
    chat_id, thread_id = await get_photo_chat()
    if message.chat.id != chat_id or message.from_user is None or message.from_user.is_bot:
        return
    if thread_id and message.message_thread_id != thread_id:
        return
    image = get_image(message)
    if not image:
        return
    tasks = await db.get_active_tasks_by_hashtags(extract_hashtags(message))
    if not tasks:
        return
    task = tasks[0]  # если в подписи несколько хэштегов заданий — берём первый

    user = message.from_user
    await db.save_user(user.id, user.username, user.full_name)

    if await db.user_has_approved(task["id"], user.id):
        await message.reply(f"Задание #{esc(task['hashtag'])} у тебя уже засчитано 👌")
        return
    if await db.user_has_pending(task["id"], user.id):
        await message.reply("Твоё прошлое фото по этому заданию ещё на проверке ⏳")
        return

    file_id, is_document = image
    day = message.date.astimezone(LOCAL_TZ).date().isoformat()
    sub_id = await db.create_submission(
        task["id"], user.id, message.chat.id, message.message_id, file_id, is_document, day
    )
    sub = await db.get_submission(sub_id)
    caption = review_caption(sub)
    keyboard = review_keyboard(sub_id)

    delivered = 0
    for staff_id in await staff_ids():
        try:
            if is_document:
                sent = await bot.send_document(staff_id, file_id, caption=caption, reply_markup=keyboard)
            else:
                sent = await bot.send_photo(staff_id, file_id, caption=caption, reply_markup=keyboard)
            await db.add_review_message(sub_id, staff_id, sent.message_id)
            delivered += 1
        except Exception:
            # чаще всего человек ещё не нажал /start в личке с ботом
            log.warning("Не смог отправить фото на проверку пользователю %s", staff_id)
    if delivered == 0:
        log.error("Фото %s никому из OC не доставлено — пусть все нажмут /start у бота", sub_id)


# ---------------------------------------------------------------- решение OC

@router.callback_query(F.data.startswith("ph:"))
async def on_review(callback: CallbackQuery, bot: Bot) -> None:
    if not await is_staff(callback.from_user.id):
        await callback.answer("Это может делать только OC.", show_alert=True)
        return
    try:
        _, action, raw_id = callback.data.split(":")
        sub_id = int(raw_id)
    except ValueError:
        await callback.answer()
        return

    approved = action == "a"
    status = "approved" if approved else "rejected"
    if not await db.decide_submission(sub_id, status, callback.from_user.id):
        await callback.answer("Это фото уже проверил кто-то другой.", show_alert=True)
        return

    sub = await db.get_submission(sub_id)
    bonus = False
    if approved:
        day = sub["day"] or sub["created_at"][:10]
        bonus = await db.award_photohunt_day(sub["user_id"], day, sub_id, EXP_PHOTOHUNT_DAY_POINTS)

    reviewer = esc(callback.from_user.full_name)
    decision = f"✅ Засчитал(а): {reviewer}" if approved else f"❌ Отклонил(а): {reviewer}"
    caption = review_caption(sub, decision)
    for chat_id, message_id in await db.get_review_messages(sub_id):
        try:
            await bot.edit_message_caption(
                chat_id=chat_id, message_id=message_id, caption=caption, reply_markup=None
            )
        except Exception:
            log.warning("Не смог обновить сообщение проверки у %s", chat_id)

    if approved:
        reply = f"✅ Фото по заданию #{esc(sub['hashtag'])} засчитано!"
        if bonus:
            reply += f"\n🧭 +{EXP_PHOTOHUNT_DAY_POINTS} в Экспедицию за участие в ФотоХанте сегодня"
        else:
            reply += "\n(бонус Экспедиции за этот день уже получен)"
    else:
        reply = f"❌ Фото по заданию #{esc(sub['hashtag'])} не засчитано. Можно прислать другое."
    try:
        await bot.send_message(
            sub["chat_id"],
            reply,
            reply_parameters=ReplyParameters(
                message_id=sub["message_id"], allow_sending_without_reply=True
            ),
        )
    except Exception:
        log.warning("Не смог ответить делегату в чате (submission %s)", sub_id)

    await callback.answer("Засчитано ✅" if approved else "Отклонено ❌")
