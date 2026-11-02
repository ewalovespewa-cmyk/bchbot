"""Чистый чат: бот не болтает в группах.

- ephemeral(): короткий ответ в чате, который вместе с командой исчезает через несколько секунд;
- tell_user(): сообщение человеку в личку; если он ещё не нажимал /start у бота — короткий ответ
  в чате, который удаляется через 15 секунд;
- menu_button(): кнопка «Открыть меню» — ведёт в личку с ботом;
- react(): реакция 👍 на сообщение (тихий знак «засчитано»).
"""
import asyncio
import logging

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, ReactionTypeEmoji, ReplyParameters

log = logging.getLogger(__name__)

CONFIRM_SECONDS = 5     # подтверждения команд OC в чате
NOTICE_SECONDS = 15     # подсказки делегатам в чате, если в личку написать нельзя

_tasks: set[asyncio.Task] = set()


def _keep(task: asyncio.Task) -> None:
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


def delete_later(bot: Bot, chat_id: int, message_ids: list[int], delay: float) -> None:
    async def run():
        await asyncio.sleep(delay)
        for mid in message_ids:
            try:
                await bot.delete_message(chat_id, mid)
            except Exception:
                pass  # нет прав админа или уже удалено
    _keep(asyncio.create_task(run()))


async def ephemeral(message: Message, bot: Bot, text: str, delay: float = CONFIRM_SECONDS, markup=None) -> None:
    """Ответ в чате, который через delay секунд удаляется вместе с исходной командой."""
    ids = [message.message_id]
    try:
        sent = await bot.send_message(
            message.chat.id, text, reply_markup=markup,
            message_thread_id=message.message_thread_id if message.is_topic_message else None,
        )
        ids.append(sent.message_id)
    except Exception:
        log.warning("Не смог ответить в чате %s", message.chat.id)
    delete_later(bot, message.chat.id, ids, delay)


async def tell_user(bot: Bot, user_id: int, text: str, chat_message: Message | None = None) -> bool:
    """Написать человеку в личку. Не вышло — коротко ответить в чате и удалить ответ через 15 секунд.
    True — дошло в личку."""
    try:
        await bot.send_message(user_id, text)
        return True
    except Exception:
        pass
    if chat_message is not None:
        try:
            sent = await bot.send_message(
                chat_message.chat.id, text,
                reply_parameters=ReplyParameters(message_id=chat_message.message_id, allow_sending_without_reply=True),
            )
            delete_later(bot, chat_message.chat.id, [sent.message_id], NOTICE_SECONDS)
        except Exception:
            log.warning("Не смог ответить %s ни в личку, ни в чате", user_id)
    return False


async def tell_user_about(bot: Bot, user_id: int, chat_id: int, message_id: int, text: str) -> bool:
    """То же, но когда исходного сообщения нет под рукой (например, после проверки OC)."""
    try:
        await bot.send_message(user_id, text)
        return True
    except Exception:
        pass
    try:
        sent = await bot.send_message(
            chat_id, text, reply_parameters=ReplyParameters(message_id=message_id, allow_sending_without_reply=True)
        )
        delete_later(bot, chat_id, [sent.message_id], NOTICE_SECONDS)
    except Exception:
        log.warning("Не смог сообщить %s результат", user_id)
    return False


async def react(bot: Bot, chat_id: int, message_id: int, emoji: str = "👍") -> bool:
    try:
        await bot.set_message_reaction(chat_id, message_id, reaction=[ReactionTypeEmoji(emoji=emoji)])
        return True
    except Exception:
        return False


async def menu_button(bot: Bot) -> InlineKeyboardMarkup:
    me = await bot.me()
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🤖 Открыть меню", url=f"https://t.me/{me.username}?start=menu")
    ]])


async def to_menu(message: Message, bot: Bot) -> None:
    """Делегат написал команду в группе: убираем её и даём кнопку в личку (исчезает сама)."""
    await ephemeral(message, bot, "Всё в личке у бота 👇", delay=NOTICE_SECONDS, markup=await menu_button(bot))
