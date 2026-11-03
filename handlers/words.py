"""Текстовые задания Экспедиции («напиши предложение со словом»). Фаз больше нет.

OC: меню → 🧭 Экспедиция → ✍️ Новое слово (или /word кофе [баллы] [свой текст]).
Бот публикует задание в чат делегатов (тот же, что у ФотоХанта, — /setchat).
Делегат ОТВЕЧАЕТ (reply) на пост бота предложением (от PHASE_WORD_MIN_WORDS слов) с этим словом —
бот сам проверяет (падежи учитываются), ставит 👍 и начисляет баллы. Обычные сообщения без reply
заданием не считаются. Один раз на человека за слово. Новое слово закрывает предыдущее.
Задания работают, только пока Экспедиция идёт.
"""
import html
import re

from aiogram import Bot, F, Router
from aiogram.filters import BaseFilter, Command, CommandObject
from aiogram.types import Message

import db
import db_phases
from chatutil import react, tell_user
from config import PHASE_WORD_MIN_WORDS, PHASE_WORD_POINTS
from handlers.expedition import is_active
from roles import IsStaff, is_staff

router = Router()
GROUPS = {"group", "supergroup"}


def esc(text: str | None) -> str:
    return html.escape(text or "")


async def tasks_chat() -> tuple[int | None, int | None]:
    """Куда публиковать задания: в чат делегатов (настраивается /setchat)."""
    chat_id = await db.get_setting("photo_chat_id")
    thread = await db.get_setting("photo_thread_id")
    return (int(chat_id) if chat_id else None, int(thread) if thread else None)


async def publish(bot: Bot, text: str) -> Message:
    chat_id, thread_id = await tasks_chat()
    if not chat_id:
        raise RuntimeError("не задан чат делегатов — отправь /setchat в этом чате")
    return await bot.send_message(chat_id, text, message_thread_id=thread_id)


def _split_points(rest: str, default: int) -> tuple[int, str]:
    """'10 текст' -> (10, 'текст'); 'текст' -> (default, 'текст')."""
    first, _, tail = rest.strip().partition(" ")
    if first.isdigit() and int(first) > 0:
        return int(first), tail.strip()
    return default, rest.strip()


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
            f"<code>/word кофе 10</code> — то же, но за 10 баллов (по умолчанию {PHASE_WORD_POINTS})\n"
            "<code>/word кофе 10 Свой текст задания</code> — со своим текстом\n\n"
            "Новое слово заменяет предыдущее."
        )
        return
    if not await is_active():
        await message.answer("Экспедиция сейчас не идёт — сначала запусти её: меню → 🧭 Экспедиция → ▶️ Запустить.")
        return
    word, _, rest = args.partition(" ")
    word = word.strip("«»\"'")
    points, text = _split_points(rest, PHASE_WORD_POINTS)
    if not text:
        text = f"Напишите предложение со словом «{word}»"

    task_id = await db_phases.create_word_task(word, text, points, 0, message.from_user.id)
    post = (
        f"✍️ <b>Задание Экспедиции</b>\n\n{esc(text)}\n\n"
        f"↩️ Ответь (reply) на это сообщение — иначе не засчитается.\n"
        f"За выполнение: <b>+{points}</b> 🧭"
    )
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


def _reply_to_bot(message: Message, bot: Bot):
    reply = message.reply_to_message
    if reply and reply.from_user and reply.from_user.id == bot.id:
        return reply
    # бот-админ с «Remain Anonymous»: его посты идут от имени группы
    if reply and reply.sender_chat and reply.sender_chat.id == message.chat.id:
        return reply
    return None


class WordAnswer(BaseFilter):
    """Пропускает только ответы (reply) на пост бота с заданием-словом.
    Обычные сообщения проходят дальше к другим хендлерам."""

    async def __call__(self, message: Message, bot: Bot) -> bool | dict:
        user = message.from_user
        reply = _reply_to_bot(message, bot)
        if reply is None or user is None or user.is_bot or message.sender_chat:
            return False
        if (message.text or "").startswith("/"):
            return False
        task = await db_phases.word_task_by_post(message.chat.id, reply.message_id)
        if task is None or not await is_active():
            return False
        return {"word_task": task, "oc_test": await is_staff(user.id)}


@router.message(F.chat.type.in_(GROUPS), WordAnswer())
async def on_word_answer(message: Message, bot: Bot, word_task, oc_test: bool = False) -> None:
    user = message.from_user
    text = message.text or message.caption or ""
    if oc_test:
        ok = word_task["active"] and is_sentence(text) and word_matches(text, word_task["word"])
        await tell_user(
            bot, user.id,
            "🧪 Проверка OC: " + ("✅ у делегата такой ответ засчитался бы." if ok
                                  else "❌ такой ответ не засчитался бы.") +
            " OC баллы не получает.",
            message,
        )
        return
    if not word_task["active"]:
        await tell_user(bot, user.id, f"✍️ Слово «{esc(word_task['word'])}» уже закрыто — ищи новое задание 😉", message)
        return
    if await db_phases.word_done(word_task["id"], user.id):
        await tell_user(bot, user.id, f"✍️ Слово «{esc(word_task['word'])}» у тебя уже засчитано 👌", message)
        return
    if not is_sentence(text) or not word_matches(text, word_task["word"]):
        await tell_user(
            bot, user.id,
            f"✍️ Не засчитано: нужно предложение (от {PHASE_WORD_MIN_WORDS} слов) "
            f"со словом «{esc(word_task['word'])}». Ответь (reply) на пост с заданием ещё раз.",
            message,
        )
        return
    await db.save_user(user.id, user.username, user.full_name)
    if not await db_phases.complete_word(word_task["id"], user.id, message.chat.id, message.message_id, word_task["points"]):
        return
    if not await react(bot, message.chat.id, message.message_id):
        await tell_user(bot, user.id, f"✅ Слово засчитано: +{word_task['points']} 🧭", message)
