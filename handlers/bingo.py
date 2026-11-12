"""Бинго — офлайн-игра: 14 заданий (08, 10 — текст; 09 — фото + короткий ответ; остальные — фото/скриншот),
каждое сдаётся и проверяется отдельно.

Секретность: пока приём выключен, бинго нигде не видно — ни кнопок, ни команд, бот молчит на фото.
Админ включает приём: меню → 🎲 Бинго → «Включить приём» (или /bingo on).

Делегат: в меню (/start) появляется «🎲 Бинго» — карточка из 14 номеров:
  ⬜ не сдано · ⏳ на проверке · ✅ засчитано · ❌ нужно переделать.
Жмёт на номер → бот показывает задание и просит текст / фото → задание сразу уходит OC на проверку.
Порядок любой; на ❌ сразу приходит сообщение, переделать можно когда угодно.
Когда все 14 засчитаны — поздравление делегату и сообщение OC.

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
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, LinkPreviewOptions, Message

import db
import db_bingo
from integration import access as bc_access
from integration import config as bc_config
from integration.gate import NEED_CHECKIN_TEXT
from config import BINGO_ENABLED
from roles import IsAdmin, IsStaff, is_staff, review_targets

router = Router()
log = logging.getLogger(__name__)

# Задания: (название, описание, подтверждение). Тексты можно поправить в меню → Бинго → ✏️ Тексты заданий.
TASKS = {
    1: ("LINKED IN",
        "Опубликуй пост в LinkedIn о своём опыте участия в Business Cup и отметь “AIESEC in Kazakhstan” и “Zimran”.",
        "скриншот опубликованного поста."),
    2: ("TEAM CHECK",
        "Сделай фото своей команды у баннера Business Cup.",
        "фото команды."),
    3: ("NEW CONNECTION",
        "Познакомьтесь с другой командой и сделайте совместное селфи полными составами обеих команд.",
        "совместное фото."),
    4: ("JUST POSE",
        "Сделай с командой фото с смешными позами.",
        "фото команды."),
    5: ("HYDRATION CHECK",
        "Напомни тиммейту попить воды и сделайте фото со своими бутылками или стаканами.",
        "фото с водой."),
    6: ("PROJECT RUN MODE",
        "Покажи, как выглядит рабочее место твоей команды во время Project Run.",
        "фото рабочего места."),
    7: ("BC ON YOU",
        "Покажи свой мерч Business Cup - например, браслет на руке. Можно всей командой!",
        "фото с мерчем."),
    8: ("DELULU IS THE SOLULU",
        "Придумай самое амбициозное название или слоган для своего продукта. Чем смелее, тем лучше.",
        "текст."),
    9: ("MEET AIESEC",
        "Познакомься с одним AIESEC-ером, сделай совместное фото и узнай, что ему дал AIESEC. Поделись ответом.",
        "фото и короткий ответ."),
    10: ("HELP US COOK",
         "Предложи одну идею, которая сделает будущий Business Cup ещё интереснее.",
         "текст."),
    11: ("SHOUT-OUT",
         "Поделись одним впечатлением от  Business Cup 2.0 в Instagram Stories и отметь @aieseckz и @zimran.team",
         "скриншот сторис."),
    12: ("TAP FOLLOW",
         "Подпишись на Instagram одного из наших партнёров.",
         "скриншот подписки."),
    13: ("CHEAT MEAL",
         "Отметь в Instagram Stories продукцию партнеров  на кофе брейке.",
         "фото."),
    14: ("AIESEC.ORG REGISTRATION",
         "Зарегистрируйся на aiesec.org и стань на шаг ближе к международному сообществу AIESEC.",
         "скриншот регистрации или личного кабинета."),
}
# Ссылки в стандартных текстах заданий: слово из описания становится кликабельным.
LINKS = {
    14: ("aiesec.org", "https://aieseckz.vercel.app/r/bc2-tg-bot14"),
}
CELLS = len(TASKS)
TEXT_CELLS = {8, 10}   # только текст
BOTH_CELLS = {9}       # фото + короткий ответ в подписи; остальные — фото / скриншот
ROW = 4                # номеров в ряду карточки
BINGO_POINTS = int(os.getenv("BINGO_POINTS", "0"))
ICON = {None: "⬜", "pending": "⏳", "approved": "✅", "rejected": "❌"}


class BingoInput(StatesGroup):
    waiting = State()


def esc(text: str | None) -> str:
    return html.escape(text or "")


def kind_of(cell: int) -> str:
    if cell in TEXT_CELLS:
        return "text"
    return "both" if cell in BOTH_CELLS else "photo"


KIND_LABEL = {"text": "Текстовый ответ", "photo": "Фото-подтверждение", "both": "Фото + короткий ответ"}
KIND_SHORT = {"text": "текст", "photo": "фото", "both": "фото + ответ"}
KIND_ICON = {"text": "✍️", "photo": "📸", "both": "📸✍️"}


def title(cell: int) -> str:
    """«01. LINKED IN»"""
    return f"{cell:02d}. {TASKS[cell][0]}"


def cell_rows(prefix: str, label=lambda n: str(n)) -> list[list[InlineKeyboardButton]]:
    nums = list(range(1, CELLS + 1))
    return [[b(label(n), f"{prefix}{n}") for n in nums[i:i + ROW]] for i in range(0, CELLS, ROW)]


def b(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


async def is_open() -> bool:
    """Приём включён и бинго вообще разрешено (BINGO_ENABLED). Пока не разрешено — всегда False."""
    return BINGO_ENABLED and (await db.get_setting("bingo_open")) == "1"


DISABLED_TEXT = "🔒 Бинго отключено до проджект рана — делегаты его нигде не видят. Включу по твоей команде."


def default_text(cell: int) -> str:
    _, body, proof = TASKS[cell]
    return f"{body}\nПодтверждение: {proof}"


async def custom_text(cell: int) -> str | None:
    """Текст, который OC поменяли в меню. None — используется стандартный."""
    return await db.get_setting(f"bingo_v2_task_{cell}")


async def task_text(cell: int) -> str:
    """Описание задания (без названия): своё от OC или стандартное."""
    return await custom_text(cell) or default_text(cell)


HTML_MARK = "html:"  # текст из редактора сохранён с форматированием и ссылками


async def task_html(cell: int) -> str:
    """Описание задания для карточки (HTML): своё от OC — с его форматированием, стандартное — со ссылкой из LINKS."""
    custom = await custom_text(cell)
    if custom:
        return custom[len(HTML_MARK):] if custom.startswith(HTML_MARK) else esc(custom)
    _, body, proof = TASKS[cell]
    body = esc(body)
    if cell in LINKS:
        word, url = LINKS[cell]
        body = body.replace(esc(word), f'<a href="{esc(url)}"><b>{esc(word)}</b></a>', 1)
    return f"{body}\n\n<b>Подтверждение:</b> {esc(proof)}"


async def set_task_text(cell: int, text: str, html_text: str | None = None) -> None:
    """«-» — вернуть стандартный текст. html_text — тот же текст с форматированием и ссылками из Telegram."""
    text = text.strip()
    if text in {"", "-"}:
        value = None
    elif html_text:
        value = HTML_MARK + html_text.strip()
    else:
        value = text
    await db.set_setting(f"bingo_v2_task_{cell}", value)


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
        if not BINGO_ENABLED:
            await message.answer(DISABLED_TEXT)
            return
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
    if not BINGO_ENABLED:
        return (
            "🎲 <b>Бинго</b>\n"
            "Приём: 🔒 отключено до проджект рана — делегаты бинго нигде не видят.\n\n"
            "Пока можно заранее вписать тексты заданий и проверить карточку как делегат."
        )
    s = await db_bingo.stats()
    return (
        f"🎲 <b>Бинго</b>\n"
        f"Приём: {'🟢 включён — у делегатов есть кнопка' if await is_open() else '⚪️ выключен — делегаты бинго не видят'}\n\n"
        f"Ждут проверки: {s['pending']}\n"
        f"Засчитано заданий: {s['approved']} · на переделку: {s['rejected']}\n"
        f"Участвуют: {s['people']} · собрали всё бинго: {s['done']}\n\n"
        f"Заданий: {CELLS}. 08 и 10 — текст, 09 — фото + ответ, остальные — фото/скриншот. "
        "Каждое приходит на проверку отдельно."
    )


# ---------------------------------------------------------------- карточка делегата

async def grid(user_id: int) -> tuple[str, InlineKeyboardMarkup]:
    card = await db_bingo.card(user_id)
    done = sum(1 for s in card.values() if s == "approved")
    rows = cell_rows("bgo:c:", lambda n: f"{ICON[card.get(n)]} {n}")
    rows.append([b("⬅️ Главное меню", "m:home")])
    tasks = [f"{ICON[card.get(n)]} {esc(title(n))}" for n in range(1, CELLS + 1)]
    text = (
        "<b>BINGO: Business Cup 2.0</b>\n"
        "Выбери номер задания, чтобы отправить ответ. Задания можно выполнять в любом порядке.\n\n"
        + "\n".join(tasks) + "\n\n"
        + "<b>Статусы заданий:</b>\n"
        "⬜ Не выполнено\n⏳ На проверке\n✅ Принято\n❌ Требуется повторная отправка\n\n"
        f"Принято: <b>{done} из {CELLS}</b> заданий"
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
            await callback.answer(f"Задание {cell} принято ✅", show_alert=True)
            return
        if status == "pending":
            await callback.answer(f"Задание {cell} ещё на проверке ⏳", show_alert=True)
            return
        await state.set_state(BingoInput.waiting)
        await state.update_data(cell=cell)
        kind = kind_of(cell)
        task_part = f"\n\n📝 <b>{esc(title(cell))}</b>\n{await task_html(cell)}\n\n"
        if kind == "text":
            body = (f"<b>Задание {cell} · {KIND_LABEL[kind]}</b>{task_part}"
                    "Отправь ответ одним текстовым сообщением.\n\nЖду твой ответ!")
        elif kind == "both":
            body = (f"<b>Задание {cell} · {KIND_LABEL[kind]}</b>{task_part}"
                    "Отправь фотографию и напиши короткий ответ в подписи к ней — одним сообщением.\n\n"
                    "Очень интересно посмотреть, что ты подготовил!")
        else:
            body = (f"<b>Задание {cell} · {KIND_LABEL[kind]}</b>{task_part}"
                    "Отправь фотографию, подтверждающую выполнение задания.\n\n"
                    "Очень интересно посмотреть, что ты подготовил!")
        again = ("\n\n<i>Предыдущая отправка задания не была принята. "
                 "Ознакомься с результатом проверки и отправь новый ответ.</i>") if status == "rejected" else ""
        await callback.message.edit_text(
            f"{body}{again}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[b("✖️ Отмена", "bgo:grid")]]),
            link_preview_options=LinkPreviewOptions(is_disabled=True),  # без превью сайта под заданием
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
            await message.answer(f"Задание {cell} · Текст ✍️\nОтправь ответ одним текстовым сообщением")
            return
        content = message.text.strip()
    elif kind == "both":
        if not message.photo:
            await message.answer(f"Задание {cell} · Фото + ответ 📸✍️\nОтправь фотографию (не файлом) и напиши короткий ответ в подписи к ней.")
            return
        if not (message.caption or "").strip():
            await message.answer(f"Задание {cell} · Фото + ответ 📸✍️\nФото есть, но не хватает ответа. Отправь фото ещё раз и напиши короткий ответ в подписи к нему.")
            return
        content = message.photo[-1].file_id + "\n" + message.caption.strip()
    else:
        if not message.photo:
            await message.answer(f"Задание {cell} · Фото 📸\nОтправь фотографию для подтверждения задания. Не отправляй её файлом.")
            return
        content = message.photo[-1].file_id

    await state.clear()
    await db.save_user(user.id, user.username, user.full_name)
    item_id = await db_bingo.submit(user.id, cell, kind, content)
    if item_id is None:
        await message.answer(f"Задание {cell} уже отправлено на проверку или принято. Повторная отправка недоступна.", reply_markup=to_card_kb())
        return
    await message.answer(
        f"📨 Задание {cell} отправлено на проверку! Результат появится в этом чате. Пока можешь выполнять другие задания.",
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


def _photo_and_answer(item) -> tuple[str | None, str | None]:
    """(file_id фото, текст ответа) для любой сдачи."""
    if item["kind"] == "text":
        return None, item["content"]
    if item["kind"] == "both":
        file_id, _, answer = item["content"].partition("\n")
        return file_id, answer
    return item["content"], None


def _header(item) -> str:
    cell = item["cell"]
    head = (f"🎲 <b>Бинго · {esc(title(cell)) if cell in TASKS else cell}</b> "
            f"({KIND_SHORT.get(item['kind'], item['kind'])})\nОт: {_who(item)}")
    _, answer = _photo_and_answer(item)
    if answer:
        if item["kind"] == "both" and len(answer) > 600:  # подпись к фото ограничена 1024 символами
            answer = answer[:600] + "…"
        head += f"\n\n«{esc(answer)}»"
    return head


def _review_kb(item_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        b("✅ Засчитать", f"bg:a:{item_id}"),
        b("❌ Не засчитать", f"bg:r:{item_id}"),
    ]])


async def send_to_review(bot: Bot, item_id: int) -> None:
    item = await db_bingo.get(item_id)
    text, kb = _header(item), _review_kb(item_id)
    photo, _ = _photo_and_answer(item)
    if await is_staff(item["user_id"]):
        text = "🧪 <i>тест OC</i>\n" + text
    for target in await review_targets():
        try:
            if photo:
                sent = await bot.send_photo(target, photo, caption=text, reply_markup=kb)
            else:
                sent = await bot.send_message(target, text, reply_markup=kb)
            await db_bingo.add_msg(item_id, target, sent.message_id, bool(photo))
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
        await _notify(bot, user_id, f"✅ Задание {cell} принято! Бинго: {done} из {CELLS} заданий выполнено.")
        if done == CELLS and await db_bingo.mark_done(user_id):
            await _notify(bot, user_id, f"🎉 <b>Бинго собрано!</b> Все {CELLS} заданий приняты. Поздравляю с завершением!")
            for target in await review_targets():
                try:
                    await bot.send_message(target, f"🎉 {_who(item)} собрал(а) всё бинго — {CELLS} из {CELLS}!")
                except Exception:
                    pass
    else:
        what = {"text": "новый ответ", "both": "новое фото с ответом"}.get(kind_of(cell), "новое фото")
        await _notify(
            bot, user_id,
            f"❌ Задание {cell} не принято. Попробуй исправить недочёты и отправить {what}. "
            "Пока можешь выполнять другие задания.",
            redo=cell,
        )


async def _notify(bot: Bot, user_id: int, text: str, redo: int | None = None) -> None:
    markup = to_card_kb()
    if redo:
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [b(f"🔁 Переделать задание {redo}", f"bgo:c:{redo}")],
            [b("🎲 К карточке бинго", "bgo:grid")],
        ])
    try:
        await bot.send_message(user_id, text, reply_markup=markup)
    except Exception:
        log.warning("Не смог написать делегату %s про бинго", user_id)
