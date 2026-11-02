"""Бинго — офлайн-игра: 9 заданий (1–3 — текст, 4–9 — фото), каждое сдаётся и проверяется отдельно.

Секретность: пока приём выключен, бинго нигде не видно — ни кнопок, ни команд, бот молчит на фото.
Админ включает приём: меню → 🎲 Бинго → «Включить приём» (или /bingo on).

Делегат: в меню (/start) появляется «🎲 Бинго» — карточка 3×3:
  ⬜ не сдано · ⏳ на проверке · ✅ засчитано · ❌ нужно переделать.
Жмёт на номер → бот просит текст (1–3) или фото (4–9) → задание сразу уходит OC на проверку.
Порядок любой; на ❌ сразу приходит сообщение, переделать можно когда угодно.
Когда все 9 засчитаны — поздравление делегату и сообщение OC.

OC: каждое задание приходит отдельным сообщением (в общий чат OC или в личку) с ✅ / ❌.
Решает первый нажавший. Для проверки со своего аккаунта: меню → 🎲 Бинго → 🧪 «как делегат».

Если подключён бот регистрации — бинго доступно только отметившимся на входе сегодня.
Баллы в Экспедицию за бинго: BINGO_POINTS (по умолчанию 0 — не начисляются).
"""
import html
import logging
import os

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import db
import db_bingo
from integration import access as bc_access
from integration import config as bc_config
from integration.gate import NEED_CHECKIN_TEXT
from roles import IsAdmin, IsStaff, is_staff, review_targets

router = Router()
log = logging.getLogger(__name__)

CELLS = 9
TEXT_CELLS = {1, 2, 3}  # остальные — фото
BINGO_POINTS = int(os.getenv("BINGO_POINTS", "0"))
ICON = {None: "⬜", "pending": "⏳", "approved": "✅", "rejected": "❌"}


class BingoInput(StatesGroup):
    waiting = State()


def esc(text: str | None) -> str:
    return html.escape(text or "")


def kind_of(cell: int) -> str:
    return "text" if cell in TEXT_CELLS else "photo"


def b(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


async def is_open() -> bool:
    return (await db.get_setting("bingo_open")) == "1"


async def available_for(user_id: int) -> bool:
    """Видит ли человек бинго. OC — всегда (чтобы тестировать), делегат — когда приём включён
    (и, с ботом регистрации, только если отметился на входе)."""
    if await is_staff(user_id):
        return True
    if not await is_open():
        return False
    if bc_config.ENABLED and not await bc_access.is_checked_in(user_id):
        return False
    return True


# ---------------------------------------------------------------- управление (OC)

@router.message(Command("bingo"), F.chat.type == "private", IsStaff())
async def cmd_bingo(message: Message, command: CommandObject) -> None:
    arg = (command.args or "").strip().lower()
    if arg in {"on", "off", "вкл", "выкл"}:
        if not await IsAdmin()(message):
            await message.answer("Включать и выключать бинго может только админ.")
            return
        opened = arg in {"on", "вкл"}
        await db.set_setting("bingo_open", "1" if opened else "0")
        await message.answer(
            "🎲 Приём бинго <b>включён</b>: у делегатов в меню появилась кнопка «🎲 Бинго»."
            if opened else
            "🎲 Приём бинго <b>выключен</b>: кнопка у делегатов скрыта, бот молчит."
        )
        return
    await message.answer(await status_text())


async def status_text() -> str:
    s = await db_bingo.stats()
    return (
        f"🎲 <b>Бинго</b>\n"
        f"Приём: {'🟢 включён — у делегатов есть кнопка' if await is_open() else '⚪️ выключен — делегаты бинго не видят'}\n\n"
        f"Ждут проверки: {s['pending']}\n"
        f"Засчитано заданий: {s['approved']} · на переделку: {s['rejected']}\n"
        f"Участвуют: {s['people']} · собрали всё бинго: {s['done']}\n\n"
        "Задания 1–3 — текст, 4–9 — фото. Каждое приходит на проверку отдельно."
    )


# ---------------------------------------------------------------- карточка делегата

async def grid(user_id: int) -> tuple[str, InlineKeyboardMarkup]:
    card = await db_bingo.card(user_id)
    done = sum(1 for s in card.values() if s == "approved")
    rows = []
    for r in range(3):
        rows.append([
            b(f"{ICON[card.get(n)]} {n}", f"bgo:c:{n}")
            for n in range(r * 3 + 1, r * 3 + 4)
        ])
    rows.append([b("⬅️ Меню", "m:home")])
    text = (
        "🎲 <b>Бинго</b>\n"
        "Задания <b>1–3</b> — текст ✍️, <b>4–9</b> — фото 📸.\n"
        "Нажми на номер задания, чтобы сдать его. Порядок любой.\n\n"
        "⬜ не сдано · ⏳ на проверке · ✅ засчитано · ❌ переделать\n\n"
        f"Засчитано: <b>{done} из {CELLS}</b>"
    )
    if await is_staff(user_id):
        text = "🧪 <i>Ты OC — это тестовый режим, сдачи придут на проверку как обычно.</i>\n\n" + text
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


def to_card_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[b("🎲 К карточке бинго", "bgo:grid")]])


@router.callback_query(F.data.startswith("bgo:"))
async def on_card(callback: CallbackQuery, state: FSMContext) -> None:
    user_id = callback.from_user.id
    if not await available_for(user_id):
        await callback.answer()
        return
    parts = callback.data.split(":")
    if parts[1] == "grid":
        await state.clear()
        text, markup = await grid(user_id)
        try:
            await callback.message.edit_text(text, reply_markup=markup)
        except Exception:
            await callback.message.answer(text, reply_markup=markup)
        await callback.answer()
        return
    if parts[1] == "c":
        cell = int(parts[2])
        status = (await db_bingo.card(user_id)).get(cell)
        if status == "approved":
            await callback.answer(f"Задание {cell} уже засчитано ✅", show_alert=True)
            return
        if status == "pending":
            await callback.answer(f"Задание {cell} ещё на проверке ⏳", show_alert=True)
            return
        await state.set_state(BingoInput.waiting)
        await state.update_data(cell=cell)
        what = "<b>текст</b> ответа одним сообщением ✍️" if kind_of(cell) == "text" else "<b>фото</b> 📸"
        again = "\n\n<i>В прошлый раз не засчитали — попробуй ещё раз.</i>" if status == "rejected" else ""
        await callback.message.edit_text(
            f"🎲 <b>Задание {cell}</b>\n\nПришли {what}.{again}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[b("✖️ Отмена", "bgo:grid")]]),
        )
        await callback.answer()
        return
    await callback.answer()


@router.message(StateFilter(BingoInput.waiting), F.chat.type == "private", ~F.text.startswith("/"))
async def on_answer(message: Message, state: FSMContext, bot: Bot) -> None:
    user = message.from_user
    cell = (await state.get_data()).get("cell")
    if not cell or not await available_for(user.id):
        await state.clear()
        return
    kind = kind_of(cell)
    if kind == "text":
        if not message.text:
            await message.answer(f"Задание {cell} — текстовое ✍️ Пришли ответ текстом.")
            return
        content = message.text.strip()
    else:
        if not message.photo:
            await message.answer(f"Задание {cell} — с фото 📸 Пришли именно фото (не файлом и не текстом).")
            return
        content = message.photo[-1].file_id

    await state.clear()
    await db.save_user(user.id, user.username, user.full_name)
    item_id = await db_bingo.submit(user.id, cell, kind, content)
    if item_id is None:
        await message.answer(f"Задание {cell} уже на проверке или засчитано 👌", reply_markup=to_card_kb())
        return
    await message.answer(
        f"📨 Задание {cell} отправлено на проверку! Ответ придёт сюда. Можно делать следующие.",
        reply_markup=to_card_kb(),
    )
    await send_to_review(bot, item_id)


@router.message(F.chat.type == "private", F.photo | F.document | F.video)
async def on_stray_media(message: Message) -> None:
    """Фото в личку без выбранного задания."""
    if not await is_open() or not await available_for(message.from_user.id):
        if await is_open() and bc_config.ENABLED and not await is_staff(message.from_user.id):
            await message.answer(NEED_CHECKIN_TEXT)
        return  # бинго не идёт — молчим, ничего не палим
    await message.answer(
        "🎲 Чтобы сдать задание бинго, сначала выбери его номер в карточке 👇",
        reply_markup=to_card_kb(),
    )


# ---------------------------------------------------------------- проверка OC

def _who(item) -> str:
    who = esc(item["full_name"]) or str(item["user_id"])
    if item["username"]:
        who += f" (@{esc(item['username'])})"
    return who


def _header(item) -> str:
    what = "текст" if item["kind"] == "text" else "фото"
    head = f"🎲 <b>Бинго · задание {item['cell']}</b> ({what})\nОт: {_who(item)}"
    if item["kind"] == "text":
        head += f"\n\n«{esc(item['content'])}»"
    return head


def _review_kb(item_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        b("✅ Засчитать", f"bg:a:{item_id}"),
        b("❌ Не засчитать", f"bg:r:{item_id}"),
    ]])


async def send_to_review(bot: Bot, item_id: int) -> None:
    item = await db_bingo.get(item_id)
    text, kb = _header(item), _review_kb(item_id)
    if await is_staff(item["user_id"]):
        text = "🧪 <i>тест OC</i>\n" + text
    for target in await review_targets():
        try:
            if item["kind"] == "photo":
                sent = await bot.send_photo(target, item["content"], caption=text, reply_markup=kb)
            else:
                sent = await bot.send_message(target, text, reply_markup=kb)
            await db_bingo.add_msg(item_id, target, sent.message_id, item["kind"] == "photo")
        except Exception:
            log.warning("Бинго %s не доставлено на проверку в %s (нет /start или бот не в чате?)", item_id, target)


@router.callback_query(F.data.startswith("bg:"))
async def on_review(callback: CallbackQuery, bot: Bot) -> None:
    if not await is_staff(callback.from_user.id):
        await callback.answer("Это может делать только OC.", show_alert=True)
        return
    parts = callback.data.split(":")
    if len(parts) != 3 or parts[1] not in {"a", "r"} or not parts[2].isdigit():
        await callback.answer("Это старая кнопка — она больше не работает.", show_alert=True)
        return
    approved, item_id = parts[1] == "a", int(parts[2])
    if not await db_bingo.decide(item_id, approved, callback.from_user.id):
        await callback.answer("Это задание уже проверил кто-то другой.", show_alert=True)
        return
    item = await db_bingo.get(item_id)
    who = esc(callback.from_user.full_name)
    text = _header(item) + "\n\n" + (f"✅ Засчитал(а): {who}" if approved else f"❌ Не засчитал(а): {who}")
    for chat_id, message_id, is_photo in await db_bingo.msgs(item_id):
        try:
            if is_photo:
                await bot.edit_message_caption(chat_id=chat_id, message_id=message_id, caption=text, reply_markup=None)
            else:
                await bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, reply_markup=None)
        except Exception:
            pass
    await callback.answer("Засчитано ✅" if approved else "Не засчитано ❌")

    user_id, cell = item["user_id"], item["cell"]
    if approved:
        if BINGO_POINTS:
            await db.add_points(user_id, BINGO_POINTS, "bingo", item_id)
        card = await db_bingo.card(user_id)
        done = sum(1 for s in card.values() if s == "approved")
        await _notify(bot, user_id, f"✅ Бинго: задание {cell} засчитано! ({done} из {CELLS})")
        if done == CELLS and await db_bingo.mark_done(user_id):
            await _notify(bot, user_id, "🎉 <b>Бинго собрано полностью!</b> Все 9 заданий засчитаны — ты молодец!")
            for target in await review_targets():
                try:
                    await bot.send_message(target, f"🎉 {_who(item)} собрал(а) всё бинго — 9 из 9!")
                except Exception:
                    pass
    else:
        what = "новый текст" if kind_of(cell) == "text" else "новое фото"
        await _notify(
            bot, user_id,
            f"❌ Бинго: задание {cell} не засчитано. Переделай и пришли {what}, когда будет удобно — "
            "можно пока делать другие задания.",
        )


async def _notify(bot: Bot, user_id: int, text: str) -> None:
    try:
        await bot.send_message(user_id, text, reply_markup=to_card_kb())
    except Exception:
        log.warning("Не смог написать делегату %s про бинго", user_id)
