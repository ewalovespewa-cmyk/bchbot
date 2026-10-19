"""Фазы Экспедиции.

Фаза — это этап игры с объявлением и своими заданиями. Баллы между фазами копятся,
задания прошлых фаз продолжают работать — переключение фазы ничего не сбрасывает.

  /phase 1 [текст]  — начать фазу: бот публикует объявление в чат делегатов.
                      Если Экспедиция ещё скрыта — она открывается и запускается.
  /phase end        — закончить текущую фазу (пауза между фазами, баллы на месте).

Фаза 1 — слова. OC: /word кофе [баллы] [текст]. Бот публикует задание; делегат пишет
предложение (от PHASE_WORD_MIN_WORDS слов) с этим словом — бот сам проверяет, ставит 👍
и начисляет баллы. Один раз на человека за слово. Новое слово закрывает предыдущее.
Падежи засчитываются: «кружка» → «кружкой», «кофе» → «кофейку».

Фаза 2 — фото (своя «пародия» на ФотоХант, сам ФотоХант не трогаем).
OC: /photo #тег [баллы] текст. Делегат отвечает фото на пост задания или шлёт фото
с хэштегом. Фото уходит OC на проверку ✅/❌, при одобрении — баллы. Можно несколько
заданий одновременно, каждое — один раз на человека.

Фаза 3 — финал, каркас в handlers/phase3.py.

Где принимаются ответы: в чате фаз (/setphasechat; если не задан — чат ФотоХанта)
и в чатах Экспедиции (/track). Ответы считаются, только пока Экспедиция идёт.
"""
import html
import logging
import re

from aiogram import Bot, F, Router
from aiogram.filters import BaseFilter, Command, CommandObject
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    ReactionTypeEmoji,
    ReplyParameters,
)

import db
import db_phases
from config import PHASE_PHOTO_POINTS, PHASE_WORD_MIN_WORDS, PHASE_WORD_POINTS
from handlers import phase3
from handlers.expedition import _quiet_confirm, is_active, is_revealed, reset_cache, thread_of, tracks
from roles import IsAdmin, IsStaff, is_staff, staff_ids

router = Router()
log = logging.getLogger(__name__)

GROUPS = {"group", "supergroup"}
HASHTAG_RE = re.compile(r"^#?(\w{2,64})$")

PHASES = {
    1: ("Фаза 1", "Каждый день OC будет давать слово — пишите в чат предложение с ним и получайте баллы ✍️"),
    2: ("Фаза 2", "Время фото-заданий 📸 Присылайте фото ответом на пост с заданием — после проверки OC начислим баллы."),
    3: ("Фаза 3 — финал", "Финальная фаза Экспедиции! Подробности — совсем скоро 🔥"),
}


def esc(text: str | None) -> str:
    return html.escape(text or "")


# ---------------------------------------------------------------- текущая фаза и чат

async def current_phase() -> int:
    value = await db.get_setting("exp_phase")
    return int(value) if value and value.isdigit() else 0


async def phase_chat() -> tuple[int | None, int | None]:
    """Куда публиковать задания фаз. По умолчанию — туда же, где ФотоХант."""
    chat_id = await db.get_setting("phase_chat_id") or await db.get_setting("photo_chat_id")
    if not chat_id:
        return None, None
    if await db.get_setting("phase_chat_id"):
        thread = await db.get_setting("phase_thread_id")
    else:
        thread = await db.get_setting("photo_thread_id")
    return int(chat_id), (int(thread) if thread else None)


async def in_game_place(message: Message) -> bool:
    """Ответ засчитывается в чате фаз (любая тема) и в чатах/темах Экспедиции."""
    chat_id, _ = await phase_chat()
    if message.chat.id == chat_id:
        return True
    t = await tracks()
    return (message.chat.id, 0) in t or (message.chat.id, thread_of(message)) in t


async def publish(bot: Bot, text: str) -> Message:
    chat_id, thread_id = await phase_chat()
    if not chat_id:
        raise RuntimeError("не задан чат: отправь /setphasechat в чате делегатов")
    return await bot.send_message(chat_id, text, message_thread_id=thread_id)


@router.message(Command("setphasechat"), F.chat.type.in_(GROUPS), IsAdmin())
async def cmd_setphasechat(message: Message, bot: Bot) -> None:
    thread = thread_of(message)
    await db.set_setting("phase_chat_id", str(message.chat.id))
    await db.set_setting("phase_thread_id", str(thread) if thread else None)
    where = "в эту тему" if thread else "в этот чат"
    await _quiet_confirm(message, bot, f"🧭 Задания фаз Экспедиции буду публиковать {where} («{esc(message.chat.title)}»).")


@router.message(Command("setphasechat"), F.chat.type == "private", IsAdmin())
async def cmd_setphasechat_private(message: Message) -> None:
    await message.answer("Отправь эту команду <b>в чате делегатов</b> (или в нужной теме).")


# ---------------------------------------------------------------- переключение фаз

@router.message(Command("phase"), F.chat.type == "private", IsStaff())
async def cmd_phase(message: Message, command: CommandObject, bot: Bot) -> None:
    args = (command.args or "").strip()
    now = await current_phase()
    if not args:
        name = PHASES[now][0] if now in PHASES else "между фазами"
        await message.answer(
            f"🧭 Сейчас: <b>{name}</b>\n\n"
            "Начать фазу: <code>/phase 1</code> (или 2, 3), можно с текстом объявления:\n"
            "<code>/phase 1 Экспедиция начинается! …</code>\n"
            "Закончить фазу: <code>/phase end</code>"
        )
        return
    if not await IsAdmin()(message):
        await message.answer("Переключать фазы может только админ.")
        return

    first, _, text = args.partition(" ")
    if first.lower() in {"end", "0", "стоп", "конец"}:
        await db.set_setting("exp_phase", "0")
        await message.answer(
            "⏹ Фаза завершена. Баллы и задания на месте; сообщения в чате продолжают считаться.\n"
            "Новую фазу — /phase 2 (или 3)."
        )
        return
    if not first.isdigit() or int(first) not in PHASES:
        await message.answer("Напиши <code>/phase 1</code>, <code>/phase 2</code>, <code>/phase 3</code> или <code>/phase end</code>.")
        return

    phase = int(first)
    title, default_text = PHASES[phase]
    opened_now = not await is_revealed()
    await db.set_setting("exp_phase", str(phase))
    await db.set_setting("exp_active", "1")
    await db.set_setting("exp_revealed", "1")
    reset_cache()

    post = f"🧭 <b>Экспедиция · {title}</b>\n\n{esc(text.strip()) or default_text}"
    try:
        await publish(bot, post)
        published = "Объявление опубликовано в чат."
    except Exception as e:
        published = f"⚠️ Объявление не опубликовано: {esc(str(e))}"
    extra = "\nЭкспедиция открыта: делегатам доступны /top и /points." if opened_now else ""
    await message.answer(f"✅ Началась <b>{title}</b>. {published}{extra}")
    if phase == 3:
        await phase3.on_phase_start(bot)


async def _require_open(message: Message) -> bool:
    if await is_revealed():
        return True
    await message.answer("Экспедиция ещё скрыта — сначала начни фазу: /phase 1")
    return False


def _split_points(rest: str, default: int) -> tuple[int, str]:
    """'10 текст' -> (10, 'текст'); 'текст' -> (default, 'текст')."""
    first, _, tail = rest.strip().partition(" ")
    if first.lstrip("-").isdigit() and int(first) > 0:
        return int(first), tail.strip()
    return default, rest.strip()


# ---------------------------------------------------------------- фаза 1: слова

def _norm(text: str) -> str:
    return text.lower().replace("ё", "е")


def word_matches(text: str, word: str) -> bool:
    """Есть ли слово в тексте, с учётом падежей: сравниваем по основе слова."""
    w = _norm(word).strip()
    t = _norm(text)
    if " " in w:
        return w in t
    stem = w if len(w) <= 3 else w[:-1] if len(w) <= 5 else w[:-2]
    return any(tok.startswith(stem) and len(tok) <= len(w) + 4 for tok in re.findall(r"\w+", t))


def is_sentence(text: str) -> bool:
    return len(re.findall(r"\w+", text)) >= PHASE_WORD_MIN_WORDS


@router.message(Command("word"), F.chat.type == "private", IsStaff())
async def cmd_word(message: Message, command: CommandObject, bot: Bot) -> None:
    args = (command.args or "").strip()
    if not args:
        await message.answer(
            "Напиши так:\n<code>/word кофе</code> — задание «напишите предложение со словом кофе»\n"
            f"<code>/word кофе 10</code> — то же, но за {10} баллов (по умолчанию {PHASE_WORD_POINTS})\n"
            "<code>/word кофе 10 Свой текст задания</code> — со своим текстом\n\n"
            "Новое слово заменяет предыдущее. Закрыть текущее: /wordoff"
        )
        return
    if not await _require_open(message):
        return
    word, _, rest = args.partition(" ")
    word = word.strip("«»\"'")
    points, text = _split_points(rest, PHASE_WORD_POINTS)
    if not text:
        text = f"Напишите в чат предложение со словом «{word}»"

    task_id = await db_phases.create_word_task(word, text, points, await current_phase(), message.from_user.id)
    post = f"✍️ <b>Задание Экспедиции</b>\n\n{esc(text)}\n\nЗа выполнение: <b>+{points}</b> 🧭"
    try:
        sent = await publish(bot, post)
    except Exception as e:
        await db_phases.close_word_tasks()
        await message.answer(f"Не получилось опубликовать задание: <code>{esc(str(e))}</code>")
        return
    await db_phases.set_word_post(task_id, sent.chat.id, sent.message_id)
    await message.answer(f"✅ Слово «{esc(word)}» опубликовано (+{points}). Бот сам засчитывает ответы.")


@router.message(Command("wordoff"), F.chat.type == "private", IsStaff())
async def cmd_wordoff(message: Message) -> None:
    closed = await db_phases.close_word_tasks()
    await message.answer("⚪️ Текущее слово закрыто." if closed else "Активного слова нет.")


@router.message(Command("words"), F.chat.type == "private", IsStaff())
async def cmd_words(message: Message) -> None:
    rows = await db_phases.list_word_tasks()
    if not rows:
        await message.answer("Слов пока не было. Дать задание: /word слово")
        return
    lines = [
        f"{'🟢' if r['active'] else '⚪️'} «{esc(r['word'])}» · +{r['points']} · выполнили: {r['done']}"
        for r in rows
    ]
    await message.answer("<b>Задания со словами</b> (последние):\n\n" + "\n".join(lines))


class WordAnswer(BaseFilter):
    """Пропускает сообщение, если это засчитываемый ответ на активное слово.
    Остальные сообщения проходят дальше к другим хендлерам (ФотоХант и т. д.)."""

    async def __call__(self, message: Message) -> bool | dict:
        user = message.from_user
        text = message.text or message.caption or ""
        if not text or text.startswith("/") or user is None or user.is_bot or message.sender_chat:
            return False
        task = await db_phases.active_word_task()
        if task is None or not await is_active() or not await in_game_place(message):
            return False
        if not is_sentence(text) or not word_matches(text, task["word"]):
            return False
        if await is_staff(user.id) or await db_phases.word_done(task["id"], user.id):
            return False
        return {"word_task": task}


@router.message(F.chat.type.in_(GROUPS), WordAnswer())
async def on_word_answer(message: Message, bot: Bot, word_task) -> None:
    user = message.from_user
    await db.save_user(user.id, user.username, user.full_name)
    if not await db_phases.complete_word(word_task["id"], user.id, message.chat.id, message.message_id, word_task["points"]):
        return
    try:
        await bot.set_message_reaction(message.chat.id, message.message_id, reaction=[ReactionTypeEmoji(emoji="👍")])
    except Exception:
        await message.reply(f"✅ +{word_task['points']} 🧭")


# ---------------------------------------------------------------- фаза 2: фото

def _hashtags(message: Message) -> list[str]:
    text = message.caption or message.text or ""
    tags = []
    for ent in message.caption_entities or message.entities or []:
        if ent.type == "hashtag":
            tag = ent.extract_from(text).lstrip("#").lower()
            if tag and tag not in tags:
                tags.append(tag)
    return tags


def _image(message: Message) -> tuple[str, bool] | None:
    if message.photo:
        return message.photo[-1].file_id, False
    doc = message.document
    if doc and (doc.mime_type or "").startswith("image/"):
        return doc.file_id, True
    return None


def _link(chat_id: int, message_id: int) -> str | None:
    s = str(chat_id)
    return f"https://t.me/c/{s[4:]}/{message_id}" if s.startswith("-100") else None


@router.message(Command("photo"), F.chat.type == "private", IsStaff())
async def cmd_photo(message: Message, command: CommandObject, bot: Bot) -> None:
    parts = (command.args or "").strip().split(maxsplit=1)
    m = HASHTAG_RE.match(parts[0]) if parts else None
    points, text = _split_points(parts[1], PHASE_PHOTO_POINTS) if len(parts) > 1 else (0, "")
    if not m or not text:
        await message.answer(
            "Напиши так:\n<code>/photo #кружка Сфоткайся с кружкой</code>\n"
            f"<code>/photo #кружка 15 Сфоткайся с кружкой</code> — за 15 баллов (по умолчанию {PHASE_PHOTO_POINTS})\n\n"
            "Делегаты отвечают фото на пост задания или шлют фото с этим хэштегом. "
            "Фото придут сюда на проверку ✅/❌."
        )
        return
    if not await _require_open(message):
        return
    hashtag = m.group(1).lower()
    task_id = await db_phases.create_photo_task(hashtag, text, points, await current_phase(), message.from_user.id)
    if task_id is None:
        await message.answer(f"Фото-задание #{esc(hashtag)} уже было. Придумай другой хэштег.")
        return
    post = (
        f"📸 <b>Фото-задание Экспедиции</b>\n\n{esc(text)}\n\n"
        f"Ответь фото на это сообщение (или пришли фото с #{esc(hashtag)}).\n"
        f"За засчитанное фото: <b>+{points}</b> 🧭"
    )
    try:
        sent = await publish(bot, post)
    except Exception as e:
        await db_phases.set_photo_active(hashtag, False)
        await message.answer(f"Не получилось опубликовать задание: <code>{esc(str(e))}</code>")
        return
    await db_phases.set_photo_post(task_id, sent.chat.id, sent.message_id)
    await message.answer(f"✅ Фото-задание #{esc(hashtag)} опубликовано (+{points}).")


@router.message(Command("photos"), F.chat.type == "private", IsStaff())
async def cmd_photos(message: Message) -> None:
    rows = await db_phases.list_photo_tasks()
    if not rows:
        await message.answer("Фото-заданий пока нет. Создать: /photo #тег текст")
        return
    lines = [
        f"{'🟢' if r['active'] else '⚪️'} #{esc(r['hashtag'])} · +{r['points']} — {esc(r['text'])}\n"
        f"    засчитано: {r['approved']} · ждут проверки: {r['pending']}"
        for r in rows
    ]
    await message.answer("<b>Фото-задания Экспедиции:</b>\n\n" + "\n\n".join(lines) +
                         "\n\nЗакрыть: /photoclose #тег · открыть снова: /photoopen #тег")


async def _toggle_photo(message: Message, command: CommandObject, active: bool) -> None:
    m = HASHTAG_RE.match((command.args or "").strip())
    if not m:
        await message.answer(f"Напиши так: <code>/{'photoopen' if active else 'photoclose'} #тег</code>")
        return
    if not await db_phases.set_photo_active(m.group(1).lower(), active):
        await message.answer("Такого фото-задания нет.")
        return
    await message.answer("🟢 Снова принимает фото." if active else "⚪️ Закрыто, новые фото не принимаются.")


@router.message(Command("photoclose"), F.chat.type == "private", IsStaff())
async def cmd_photoclose(message: Message, command: CommandObject) -> None:
    await _toggle_photo(message, command, False)


@router.message(Command("photoopen"), F.chat.type == "private", IsStaff())
async def cmd_photoopen(message: Message, command: CommandObject) -> None:
    await _toggle_photo(message, command, True)


class PhotoAnswer(BaseFilter):
    """Фото на задание Экспедиции. Чужие фото (например, для ФотоХанта) проходят дальше."""

    async def __call__(self, message: Message) -> bool | dict:
        user = message.from_user
        if user is None or user.is_bot or message.sender_chat or not _image(message):
            return False
        reply = message.reply_to_message
        task = await db_phases.find_photo_task(
            _hashtags(message),
            message.chat.id if reply else None,
            reply.message_id if reply else None,
        )
        if task is None or not await is_active() or not await in_game_place(message):
            return False
        if await is_staff(user.id):
            return False
        return {"photo_task": task}


def _review_kb(sub_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Засчитать", callback_data=f"ep:a:{sub_id}"),
        InlineKeyboardButton(text="❌ Отклонить", callback_data=f"ep:r:{sub_id}"),
    ]])


def _review_caption(sub, decision: str | None = None) -> str:
    who = esc(sub["full_name"]) or str(sub["user_id"])
    if sub["username"]:
        who += f" (@{esc(sub['username'])})"
    lines = [
        f"🧭 <b>Экспедиция · фото #{esc(sub['hashtag'])}</b> (+{sub['points']})",
        esc(sub["task_text"]),
        f"От: {who}",
    ]
    link = _link(sub["chat_id"], sub["message_id"])
    if link:
        lines.append(f'<a href="{link}">Открыть в чате</a>')
    if decision:
        lines += ["", decision]
    return "\n".join(lines)


@router.message(F.chat.type.in_(GROUPS), PhotoAnswer())
async def on_photo_answer(message: Message, bot: Bot, photo_task) -> None:
    user = message.from_user
    await db.save_user(user.id, user.username, user.full_name)
    status = await db_phases.photo_status(photo_task["id"], user.id)
    if status == "approved":
        await message.reply("Это задание у тебя уже засчитано 👌")
        return
    if status == "pending":
        await message.reply("Твоё фото по этому заданию ещё на проверке ⏳")
        return
    file_id, is_document = _image(message)
    sub_id = await db_phases.create_photo_sub(photo_task["id"], user.id, message.chat.id, message.message_id, file_id, is_document)
    sub = await db_phases.get_photo_sub(sub_id)
    caption, kb = _review_caption(sub), _review_kb(sub_id)
    for staff_id in await staff_ids():
        try:
            send = bot.send_document if is_document else bot.send_photo
            sent = await send(staff_id, file_id, caption=caption, reply_markup=kb)
            await db_phases.add_photo_review_msg(sub_id, staff_id, sent.message_id)
        except Exception:
            log.warning("Фото Экспедиции не доставлено OC %s (нет /start?)", staff_id)


@router.callback_query(F.data.startswith("ep:"))
async def on_photo_review(callback: CallbackQuery, bot: Bot) -> None:
    if not await is_staff(callback.from_user.id):
        await callback.answer("Это может делать только OC.", show_alert=True)
        return
    try:
        _, action, raw = callback.data.split(":")
        sub_id = int(raw)
    except ValueError:
        await callback.answer()
        return
    approved = action == "a"
    if not await db_phases.decide_photo_sub(sub_id, approved, callback.from_user.id):
        await callback.answer("Это фото уже проверил кто-то другой.", show_alert=True)
        return
    sub = await db_phases.get_photo_sub(sub_id)
    who = esc(callback.from_user.full_name)
    caption = _review_caption(sub, f"✅ Засчитал(а): {who}" if approved else f"❌ Отклонил(а): {who}")
    for chat_id, message_id in await db_phases.get_photo_review_msgs(sub_id):
        try:
            await bot.edit_message_caption(chat_id=chat_id, message_id=message_id, caption=caption, reply_markup=None)
        except Exception:
            log.warning("Не смог обновить проверку у %s", chat_id)
    reply = (
        f"✅ Фото засчитано! +{sub['points']} в Экспедицию 🧭" if approved
        else "❌ Фото не засчитано. Можно прислать другое."
    )
    try:
        await bot.send_message(
            sub["chat_id"], reply,
            reply_parameters=ReplyParameters(message_id=sub["message_id"], allow_sending_without_reply=True),
        )
    except Exception:
        log.warning("Не смог ответить делегату (фото Экспедиции %s)", sub_id)
    await callback.answer("Засчитано ✅" if approved else "Отклонено ❌")
