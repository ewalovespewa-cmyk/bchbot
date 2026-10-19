"""Диагностика: видит ли бот сообщения в нужных чатах и что сейчас настроено.

Главная ловушка Telegram — «режим приватности». С ним бот в группе получает ТОЛЬКО команды
и ответы на свои сообщения: обычные сообщения, кружки и фото с хэштегами до него не доходят,
поэтому баллы не считаются и фото не приходят на проверку. Лечится одним из способов:
  1) сделать бота админом группы (проще всего, заодно сможет удалять /track), или
  2) @BotFather → /setprivacy → бот → Disable, затем удалить бота из группы и добавить заново.

/check (админ, в личке) — полный отчёт. При запуске бот сам пишет админам, если что-то не так.
"""
import html
import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import Message

import db
import db_phases
from config import ADMIN_IDS
from roles import IsAdmin

router = Router()
log = logging.getLogger(__name__)

FIX_TEXT = (
    "Как исправить (любой способ):\n"
    "1) <b>Сделай бота админом группы</b> — проще всего.\n"
    "2) Или @BotFather → /setprivacy → выбери бота → <b>Disable</b>, "
    "потом удали бота из группы и добавь заново."
)


def esc(text: str | None) -> str:
    return html.escape(text or "")


async def chat_access(bot: Bot, chat_id: int) -> tuple[bool, str, str]:
    """(видит ли все сообщения, название чата, пояснение)."""
    me = await bot.me()
    try:
        member = await bot.get_chat_member(chat_id, me.id)
    except Exception:
        return False, str(chat_id), "⚠️ бота нет в этом чате (удалили?) — добавь его обратно"
    try:
        title = (await bot.get_chat(chat_id)).title or str(chat_id)
    except Exception:
        title = str(chat_id)
    if member.status in ("left", "kicked"):
        return False, title, "⚠️ бота нет в этом чате — добавь его обратно"
    if member.status in ("administrator", "creator"):
        return True, title, "бот — админ ✅"
    if me.can_read_all_group_messages:
        return True, title, "видит все сообщения ✅ (не админ — не сможет удалять /track)"
    return False, title, "⚠️ видит только команды — фото и сообщения до него НЕ доходят"


async def configured_chats() -> dict[int, list[str]]:
    """Все чаты, которые использует бот, и для чего."""
    uses: dict[int, list[str]] = {}

    def add(chat_id, what):
        if chat_id:
            uses.setdefault(int(chat_id), []).append(what)

    add(await db.get_setting("photo_chat_id"), "ФотоХант (/setchat)")
    add(await db.get_setting("phase_chat_id"), "задания фаз (/setphasechat)")
    for chat_id, thread_id, title in await db.list_exp_tracks():
        add(chat_id, f"Экспедиция: {title or 'чат'}" + (" (тема)" if thread_id else ""))
    return uses


async def problems(bot: Bot) -> list[str]:
    out = []
    for chat_id, uses in (await configured_chats()).items():
        ok, title, note = await chat_access(bot, chat_id)
        if not ok:
            out.append(f"• «{esc(title)}» ({', '.join(uses)}): {note}")
    return out


async def startup_check(bot: Bot) -> None:
    """При запуске: если бот слеп в каком-то чате — пишем в лог и админам в личку."""
    try:
        me = await bot.me()
        if not me.can_read_all_group_messages:
            log.warning("Режим приватности включён: без прав админа бот не увидит сообщения в группах")
        found = await problems(bot)
    except Exception:
        log.exception("Диагностика при запуске не удалась")
        return
    if not found:
        return
    text = "⚠️ <b>Бот не видит сообщения в чатах:</b>\n" + "\n".join(found) + "\n\n" + FIX_TEXT + "\n\nПроверить ещё раз: /check"
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text)
        except Exception:
            pass


@router.message(Command("check"), F.chat.type == "private", IsAdmin())
async def cmd_check(message: Message, bot: Bot) -> None:
    from handlers.expedition import is_active, is_revealed
    from handlers.phases import PHASES, current_phase

    me = await bot.me()
    lines = ["🩺 <b>Проверка бота</b>", ""]
    lines.append(
        "Режим приватности: " + ("выключен ✅" if me.can_read_all_group_messages
                                 else "включён (нужны права админа в группах)")
    )

    lines += ["", "<b>Чаты:</b>"]
    chats = await configured_chats()
    if not chats:
        lines.append("ничего не настроено — /setchat, /track, /setphasechat в нужных чатах")
    any_blind = False
    for chat_id, uses in chats.items():
        ok, title, note = await chat_access(bot, chat_id)
        any_blind |= not ok
        lines.append(f"• «{esc(title)}» — {', '.join(uses)}\n   {note}")

    phase = await current_phase()
    state = "🟢 идёт" if await is_active() else ("⏸ пауза" if await is_revealed() else "🔒 скрыта")
    lines += ["", f"<b>Экспедиция:</b> {state}",
              f"Фаза: {PHASES[phase][0] if phase in PHASES else 'между фазами'}"]
    word = await db_phases.active_word_task()
    lines.append(f"Активное слово: «{esc(word['word'])}»" if word else "Активного слова нет")
    photos = [r for r in await db_phases.list_photo_tasks() if r["active"]]
    lines.append(f"Активных фото-заданий: {len(photos)}")

    mods = await db.list_moderators()
    lines += ["", f"<b>OC:</b> админов {len(ADMIN_IDS)}, модераторов {len(mods)}",
              "<i>OC баллы не получают — тестируйте с обычных аккаунтов.</i>"]
    if any_blind:
        lines += ["", FIX_TEXT]
    await message.answer("\n".join(lines))
