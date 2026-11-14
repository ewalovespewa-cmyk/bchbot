"""Бинго — офлайн-игра: 12 заданий (07, 09 — текст; 08 — фото + короткий ответ; остальные — фото/скриншоты),
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
import asyncio
import html
import json
import re
import logging
import os

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, LinkPreviewOptions, Message

import db
import db_bingo
from integration import access as bc_access
from integration import config as bc_config
from integration.gate import NEED_CHECKIN_TEXT
from config import BINGO_ENABLED
from roles import IsAdmin, IsStaff, is_staff, review_targets, staff_ids

router = Router()
log = logging.getLogger(__name__)

# Задания: (название, описание, подтверждение). Тексты можно поправить в меню → Бинго → ✏️ Тексты заданий.
TASKS = {
    1: ("AIESEC.ORG REGISTRATION",
        "Зарегистрируйся на aiesec.org и стань на шаг ближе к международному сообществу AIESEC.",
        "скриншот регистрации или личного кабинета."),
    2: ("TEAM CHECK",
        "Сделай фото своей команды у баннера Business Cup с смешными позами.",
        "фото команды."),
    3: ("NEW CONNECTION",
        "Познакомьтесь с другой командой и сделайте совместное селфи полными составами обеих команд.",
        "совместное фото."),
    4: ("HYDRATION CHECK",
        "Напомни тиммейту попить воды и сделайте фото со своими бутылками или стаканами.",
        "фото с водой."),
    5: ("PROJECT RUN MODE",
        "Покажи, как выглядит рабочее место твоей команды во время Project Run.",
        "фото рабочего места."),
    6: ("BC ON YOU",
        "Покажи свой мерч Business Cup - например, браслет на руке. Можно всей командой!",
        "фото с мерчем."),
    7: ("DELULU IS THE SOLULU",
        "Придумай самое амбициозное название или слоган для своего продукта. Чем смелее, тем лучше.",
        "текст."),
    8: ("MEET AIESEC",
        "Познакомься с одним AIESEC-ером, сделай совместное фото и узнай, что ему дал AIESEC. Поделись ответом.",
        "фото и короткий ответ."),
    9: ("HELP US COOK",
        "Предложи одну идею, которая сделает будущий Business Cup ещё интереснее.",
        "текст."),
    10: ("TAP FOLLOW",
         "Подпишись на Instagram одного из наших партнёров:\n"
         "firedrift.astana\naki._.time\nflip.kz\nkangojump_astana\nyescolor.astana\nclimbersgardenkz\nrpk.kz_",
         "скриншот подписки."),
    11: ("CHEAT MEAL",
         "Сделай фото своего Coffee Break, выложи в Instagram Stories и отметь aieseckz , а также аккаунт партнёра, "
         "чью продукцию ты попробовал(а)!\nНаши Coffee Break partners:\n"
         "nummi_kz\nkhalyq.sandwich01\npro_natige\ntalionigiri.kz\ndikiilori\nrccola_kaz\nglife_water\nlibellabottlers",
         "скриншот сторис."),
    12: ("SECRET STICKER",
         "Незаметно приклей стикер на другого делегата, не привлекая его внимания.",
         "фото."),
}
# Ссылки в стандартных текстах заданий: слово из описания становится кликабельным.
LINKS = {
    1: ("aiesec.org", "https://aieseckz.vercel.app/r/bc2-tg-bot14"),
}
# Строки-аккаунты Instagram в стандартных текстах: становятся ссылками на профиль
# (иначе Telegram сам делает из «flip.kz» ссылку на сайт).
IG_LINE = re.compile(r"^[A-Za-z0-9._]+$")
IG_CELLS = {10, 11}
CELLS = len(TASKS)
TEXT_CELLS = {7, 9}    # только текст
BOTH_CELLS = {8}       # фото + короткий ответ в подписи; остальные — фото / скриншот
MIN_PHOTOS: dict[int, int] = {}  # минимум фото/скринов по заданию (по умолчанию 1)
MAX_PHOTOS = 10        # альбом в Telegram — до 10
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
    # Невидимый пробел после точки: иначе Telegram сам делает из «AIESEC.ORG» ссылку на aiesec.org (без трекинга).
    return f"{cell:02d}. {TASKS[cell][0]}".replace(".", ".​").replace(f"{cell:02d}.​", f"{cell:02d}.", 1)


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
    return await db.get_setting(f"bingo_v3_task_{cell}")


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
    if cell in IG_CELLS:
        body = "\n".join(
            f'<a href="https://instagram.com/{line}">{line}</a>' if IG_LINE.match(line) else line
            for line in body.split("\n")
        )
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
    await db.set_setting(f"bingo_v3_task_{cell}", value)


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
        f"Заданий: {CELLS}. 07 и 09 — текст, 08 — фото + ответ, остальные — фото/скрины (можно несколько). "
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
                    "Отправь фотографию и напиши короткий ответ в подписи к ней — одним сообщением. "
                    "Можно несколько фото сразу (альбомом).\n\n"
                    "Очень интересно посмотреть, что ты подготовил!")
        else:
            body = (f"<b>Задание {cell} · {KIND_LABEL[kind]}</b>{task_part}"
                    "Отправь фотографию, подтверждающую выполнение задания. "
                    "Можно несколько фото или скринов сразу — одним сообщением (альбомом).\n\n"
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


ALBUM_WAIT = 1.5  # сек: ждём остальные фото альбома (или присланные по одному подряд)
_albums: dict[int, dict] = {}


def pack(photos: list[str], text: str | None = None) -> str:
    return json.dumps({"photos": photos, "text": text}, ensure_ascii=False)


def min_photos(cell: int) -> int:
    return MIN_PHOTOS.get(cell, 1)


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
        await _submit(message, state, bot, cell, kind, message.text.strip())
        return
    if not message.photo:
        if kind == "both":
            await message.answer(f"Задание {cell} · Фото + ответ 📸✍️\nОтправь фотографию (не файлом) и напиши короткий ответ в подписи к ней.")
        else:
            await message.answer(f"Задание {cell} · Фото 📸\nОтправь фотографию для подтверждения задания. Не отправляй её файлом.")
        return
    # Фото копим: альбом приходит отдельными сообщениями, а кто-то шлёт скрины по одному подряд.
    entry = _albums.get(user.id)
    if entry is None or entry["cell"] != cell:
        entry = _albums[user.id] = {"cell": cell, "photos": [], "caption": ""}
    entry["photos"].append(message.photo[-1].file_id)
    if (message.caption or "").strip():
        entry["caption"] = (entry["caption"] + "\n" + message.caption.strip()).strip()
    entry["last"] = message
    if entry.get("timer"):
        entry["timer"].cancel()
    entry["timer"] = asyncio.create_task(_finish_album(user.id, state, bot))


async def _finish_album(user_id: int, state: FSMContext, bot: Bot) -> None:
    try:
        await asyncio.sleep(ALBUM_WAIT)
    except asyncio.CancelledError:
        return
    entry = _albums.pop(user_id, None)
    if not entry:
        return
    cell, photos, caption, message = entry["cell"], entry["photos"], entry["caption"], entry["last"]
    kind = kind_of(cell)
    need = min_photos(cell)
    if len(photos) < need:
        await message.answer(
            f"Задание {cell} · Фото 📸\nДля этого задания нужно минимум {need} фото/скрин(а), а пришло {len(photos)}. "
            "Отправь все заново одним сообщением (альбомом)."
        )
        return
    if kind == "both" and not caption:
        await message.answer(f"Задание {cell} · Фото + ответ 📸✍️\nФото есть, но не хватает ответа. Отправь фото ещё раз и напиши короткий ответ в подписи к нему.")
        return
    await _submit(message, state, bot, cell, kind, pack(photos[:MAX_PHOTOS], caption if kind == "both" else None))


async def _submit(message: Message, state: FSMContext, bot: Bot, cell: int, kind: str, content: str) -> None:
    user = message.from_user
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


def _photos_and_answer(item) -> tuple[list[str], str | None]:
    """(file_id фото, текст ответа) для любой сдачи."""
    if item["kind"] == "text":
        return [], item["content"]
    content = item["content"]
    if content.startswith("{"):
        data = json.loads(content)
        return data.get("photos") or [], data.get("text")
    if item["kind"] == "both":  # старый формат: file_id\nответ
        file_id, _, answer = content.partition("\n")
        return [file_id], answer
    return [content], None


def _header(item, caption: bool = False) -> str:
    cell = item["cell"]
    photos, answer = _photos_and_answer(item)
    head = (f"🎲 <b>Бинго · {esc(title(cell)) if cell in TASKS else cell}</b> "
            f"({KIND_SHORT.get(item['kind'], item['kind'])})\nОт: {_who(item)}")
    if len(photos) > 1:
        head += f"\n📎 Фото: {len(photos)} шт. (выше)"
    if answer:
        if caption and len(answer) > 600:  # подпись к фото ограничена 1024 символами
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
    photos, _ = _photos_and_answer(item)
    single = len(photos) == 1
    text, kb = _header(item, caption=single), _review_kb(item_id)
    if await is_staff(item["user_id"]):
        text = "🧪 <i>тест OC</i>\n" + text
    for target in await review_targets():
        try:
            if single:
                sent = await bot.send_photo(target, photos[0], caption=text, reply_markup=kb)
            else:
                if photos:  # альбом, а под ним — сообщение с кнопками (к альбому кнопки не прикрепить)
                    await bot.send_media_group(target, [InputMediaPhoto(media=f) for f in photos])
                sent = await bot.send_message(target, text, reply_markup=kb)
            await db_bingo.add_msg(item_id, target, sent.message_id, single)
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
    text = _header(item, caption=len(_photos_and_answer(item)[0]) == 1) + "\n\n" + (f"✅ Засчитал(а): {who}" if approved else f"❌ Не засчитал(а): {who}")
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


# ---------------------------------------------------------------- рейтинг (для OC)

WINNERS = 10  # призовых мест


def _local_time(ts: str | None) -> str:
    """'2026-11-14 07:42:10' (UTC в базе) → '14.11 12:42' по местному времени."""
    if not ts:
        return ""
    from datetime import datetime, timezone
    from config import LOCAL_TZ
    dt = datetime.strptime(ts[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).astimezone(LOCAL_TZ)
    return dt.strftime("%d.%m %H:%M:%S")


async def ranking_text(limit: int = 40) -> str:
    from datetime import datetime
    from config import LOCAL_TZ
    rows = await db_bingo.ranking(exclude=await staff_ids())
    now = datetime.now(LOCAL_TZ).strftime("%H:%M:%S")
    lines = ["🏆 <b>Рейтинг бинго</b>", ""]
    if not rows:
        lines.append("Пока никто ничего не сдал.")
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    for place, r in enumerate(rows[:limit], 1):
        if place == WINNERS + 1:
            lines.append("— — — призовые места выше — — —")
        who = esc(r["full_name"]) or str(r["user_id"])
        if r["username"]:
            who += f" (@{esc(r['username'])})"
        line = f"{medals.get(place, f'{place}.')} {who} — <b>{r['done']}/{CELLS}</b>"
        if r["reached_at"]:
            line += f" · {_local_time(r['reached_at'])}"
        if r["pending"]:
            line += f" · ⏳ {r['pending']} на проверке"
        lines.append(line)
    if len(rows) > limit:
        lines.append(f"…и ещё {len(rows) - limit}")
    waiting = sum(1 for r in rows if r["pending"])
    lines += [
        "",
        f"Порядок: больше принятых заданий → выше. При равенстве выше тот, кто <b>раньше отправил</b> "
        f"последнее из принятых заданий (время — когда делегат сдал, а не когда OC проверил).",
        f"Первые {WINNERS} — победители. OC в рейтинг не попадают.",
    ]
    if waiting:
        lines.append(f"⚠️ У {waiting} чел. есть задания на проверке — проверь их до подведения итогов, "
                     "иначе места могут поменяться.")
    lines.append(f"\n<i>Обновлено в {now}</i>")
    return "\n".join(lines)


@router.message(Command("bingotop"), F.chat.type == "private", IsStaff())
async def cmd_bingotop(message: Message) -> None:
    await message.answer(await ranking_text(),
                         reply_markup=InlineKeyboardMarkup(inline_keyboard=[[b("🔄 Обновить", "m:bgtop")]]))
