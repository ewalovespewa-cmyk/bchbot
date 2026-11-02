"""Меню на кнопках — вместо команд. Открывается по /start (или /menu, /help) в личке с ботом.

Делегат видит только то, что сейчас можно: пока Экспедиция идёт — «Лидерборд» и «Мои баллы»;
иначе просто приветствие без кнопок (ничего не палим: ни ФотоХанта, ни бинго, ни фаз).

OC видит панель по секциям: ФотоХант · Экспедиция · Фазы · Бинго · Настройки · Проверка.
Действия, где нужен текст (новое задание, слово, баллы, модератор), бот просит прислать одним
сообщением. Всё, что делают кнопки, делают и старые команды — они продолжают работать.

Настройки чатов делаются командой прямо в нужном чате: /setchat, /track, /setphasechat,
/setreviewchat — бот удаляет команду и подтверждает в личке.
"""
import html

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import db
import db_phases
from handlers import admin as admin_cmds
from handlers import bingo, diagnostics, expedition, phases, photohunt
from handlers.expedition import _quiet_confirm, format_board, is_active, is_revealed, points_text, ranking, visible_to
from roles import IsAdmin, is_staff
from config import ADMIN_IDS

router = Router()

GROUPS = {"group", "supergroup"}


class MenuInput(StatesGroup):
    waiting = State()


def esc(text: str | None) -> str:
    return html.escape(text or "")


def b(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


def kb(*rows) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[list(r) for r in rows if r])


def back(to: str = "home", text: str = "⬅️ Назад") -> list:
    return [b(text if to != "home" else "⬅️ Меню", f"m:{to}")]


def co(command: str, args: str | None) -> CommandObject:
    return CommandObject(prefix="/", command=command, args=args or None)


def as_user(callback: CallbackQuery, bot: Bot) -> Message:
    """Сообщение меню «от имени» нажавшего — чтобы переиспользовать обработчики команд."""
    return callback.message.model_copy(update={"from_user": callback.from_user}).as_(bot)


# ---------------------------------------------------------------- экраны

async def scr_home(user) -> tuple[str, InlineKeyboardMarkup | None]:
    if not await is_staff(user.id):
        if await is_active():
            return (
                f"Привет, {esc(user.first_name)}! 👋\n\n🧭 <b>Экспедиция идёт</b> — общайся в чате, "
                "выполняй задания и поднимайся в рейтинге!",
                kb([b("🏆 Лидерборд", "m:top"), b("⭐ Мои баллы", "m:pts")]),
            )
        return (f"Привет, {esc(user.first_name)}! 👋\nЭто бот Business Cup. Следи за новостями в чате 😉", None)

    admin = user.id in ADMIN_IDS
    phase = await phases.current_phase()
    exp = "🟢 идёт" if await is_active() else ("⏸ пауза" if await is_revealed() else "🔒 скрыта")
    review = "общий чат OC ✅" if await db.get_setting("review_chat_id") else "в личку каждому"
    text = (
        f"🛠 <b>Панель OC</b> ({'админ' if admin else 'модератор'})\n\n"
        f"🧭 Экспедиция: {exp}\n"
        f"✍️ Фаза: {phases.PHASES[phase][0] if phase in phases.PHASES else 'между фазами'}\n"
        f"🎲 Бинго: {'🟢 приём включён' if await bingo.is_open() else '⚪️ приём выключен'}\n"
        f"📨 Проверка фото: {review}"
    )
    rows = [
        [b("📸 ФотоХант", "m:ph"), b("🧭 Экспедиция", "m:exp")],
        [b("✍️ Фазы", "m:phs"), b("🎲 Бинго", "m:bg")],
    ]
    if admin:
        rows.append([b("⚙️ Настройки", "m:set"), b("🩺 Проверка", "m:check")])
    return text, kb(*rows)


async def scr_ph() -> tuple[str, InlineKeyboardMarkup]:
    tasks = await db.list_tasks()
    chat = "задан ✅" if await db.get_setting("photo_chat_id") else "⚠️ не задан — отправь /setchat в чате делегатов"
    lines = ["📸 <b>ФотоХант</b>", f"Чат: {chat}", ""]
    rows = [[b("➕ Новое задание", "m:in:task")]]
    if not tasks:
        lines.append("Заданий пока нет.")
    for t in list(tasks)[-10:]:
        state = "🟢" if t["active"] else "⚪️"
        lines.append(f"{state} #{esc(t['hashtag'])} — {esc(t['text'])} · ✅ {t['approved']} · ⏳ {t['pending']}")
        rows.append([b(f"{'⚪️ Закрыть' if t['active'] else '🟢 Открыть'} #{t['hashtag']}",
                       f"m:pht:{t['id']}:{0 if t['active'] else 1}")])
    rows.append(back())
    return "\n".join(lines), kb(*rows)


async def scr_exp(admin: bool) -> tuple[str, InlineKeyboardMarkup]:
    active, revealed = await is_active(), await is_revealed()
    state = "🟢 идёт" if active else ("⏸ на паузе" if revealed else "🔒 скрыта — делегаты о ней не знают")
    tracks = await db.list_exp_tracks()
    text = (
        f"🧭 <b>Экспедиция</b>: {state}\n"
        f"Считается сообщений в: {len(tracks)} чат(ах/темах)\n\n"
        "<i>Подключить тему «Флуд»: отправь /track прямо в ней.</i>"
    )
    rows = []
    if admin:
        rows.append([b("⏸ Пауза", "m:exp:off")] if active else [b("▶️ Запустить", "m:exp:on")])
    rows.append([b("🏆 Лидерборд", "m:top"), b("📍 Где считается", "m:chats")])
    if admin:
        rows.append([b("🛠 Начислить / снять баллы", "m:in:addpoints")])
    rows.append(back())
    return text, kb(*rows)


async def scr_chats() -> tuple[str, InlineKeyboardMarkup]:
    rows = await db.list_exp_tracks()
    lines = ["📍 <b>Где считаются сообщения</b>", ""]
    lines += [f"• {esc(t) or 'без названия'} — {'тема' if th else 'весь чат'}" for _, th, t in rows] or ["Пока нигде. Отправь /track в нужной теме."]
    return "\n".join(lines), kb(back("exp"))


async def scr_phs(admin: bool) -> tuple[str, InlineKeyboardMarkup]:
    phase = await phases.current_phase()
    word = await db_phases.active_word_task()
    photos = [r for r in await db_phases.list_photo_tasks() if r["active"]]
    text = (
        f"✍️ <b>Фазы Экспедиции</b>\n"
        f"Сейчас: <b>{phases.PHASES[phase][0] if phase in phases.PHASES else 'между фазами'}</b>\n"
        f"Активное слово: {('«' + esc(word['word']) + '»') if word else 'нет'}\n"
        f"Активных фото-заданий: {len(photos)}"
    )
    rows = []
    if admin:
        rows.append([b(f"▶️ Фаза {n}", f"m:phq:{n}") for n in (1, 2, 3)])
        if phase in phases.PHASES:
            rows.append([b("⏹ Завершить фазу", "m:phendq")])
    rows += [
        [b("✍️ Новое слово", "m:in:word"), b("⚪️ Закрыть слово", "m:wordoff")],
        [b("📜 История слов", "m:words")],
        [b("🖼 Новое фото-задание", "m:in:photo"), b("📋 Фото-задания", "m:photos")],
        back(),
    ]
    return text, kb(*rows)


async def scr_words() -> tuple[str, InlineKeyboardMarkup]:
    rows = await db_phases.list_word_tasks()
    lines = ["📜 <b>Слова</b> (последние)", ""]
    lines += [f"{'🟢' if r['active'] else '⚪️'} «{esc(r['word'])}» · +{r['points']} · выполнили: {r['done']}" for r in rows] or ["Слов пока не было."]
    return "\n".join(lines), kb(back("phs"))


async def scr_photos() -> tuple[str, InlineKeyboardMarkup]:
    tasks = await db_phases.list_photo_tasks()
    lines = ["📋 <b>Фото-задания Экспедиции</b>", ""]
    rows = []
    if not tasks:
        lines.append("Пока нет.")
    for t in tasks[:10]:
        lines.append(f"{'🟢' if t['active'] else '⚪️'} #{esc(t['hashtag'])} · +{t['points']} — {esc(t['text'])} · ✅ {t['approved']} · ⏳ {t['pending']}")
        rows.append([b(f"{'⚪️ Закрыть' if t['active'] else '🟢 Открыть'} #{t['hashtag']}",
                       f"m:ept:{t['id']}:{0 if t['active'] else 1}")])
    rows.append(back("phs"))
    return "\n".join(lines), kb(*rows)


async def scr_bg(admin: bool) -> tuple[str, InlineKeyboardMarkup]:
    rows = []
    if admin:
        rows.append([b("⚪️ Выключить приём", "m:bg:off")] if await bingo.is_open() else [b("🟢 Включить приём", "m:bg:on")])
    rows.append(back())
    return await bingo.status_text(), kb(*rows)


async def scr_set() -> tuple[str, InlineKeyboardMarkup]:
    def mark(v):
        return "✅" if v else "—"
    photo = await db.get_setting("photo_chat_id")
    phase_chat = await db.get_setting("phase_chat_id")
    review = await db.get_setting("review_chat_id")
    tracks = await db.list_exp_tracks()
    text = (
        "⚙️ <b>Настройки</b>\n\n"
        "Чаты настраиваются командой <b>прямо в нужном чате</b> (бот удалит её и ответит в личку):\n"
        f"{mark(review)} <code>/setreviewchat</code> — в чате OC: сюда приходят все фото на проверку\n"
        f"{mark(photo)} <code>/setchat</code> — в чате делегатов: ФотоХант\n"
        f"{mark(phase_chat or photo)} <code>/setphasechat</code> — куда публиковать задания фаз (по умолчанию — чат ФотоХанта)\n"
        f"{mark(tracks)} <code>/track</code> — в теме «Флуд»: там считаются сообщения\n\n"
        "Бот должен быть <b>админом</b> в этих чатах — проверить: «🩺 Проверка»."
    )
    rows = [[b("👥 Модераторы", "m:mods")]]
    if review:
        rows.append([b("↩️ Проверка снова в личку (сбросить чат OC)", "m:revoff")])
    rows.append(back())
    return text, kb(*rows)


async def scr_mods() -> tuple[str, InlineKeyboardMarkup]:
    mods = await db.list_moderators()
    lines = ["👥 <b>Модераторы</b>", ""]
    rows = []
    for user_id, username, full_name in mods:
        name = full_name or str(user_id)
        lines.append(f"• {esc(name)}" + (f" (@{esc(username)})" if username else ""))
        rows.append([b(f"❌ Снять: {name[:30]}", f"m:delmod:{user_id}")])
    if not mods:
        lines.append("Пока нет.")
    rows.append([b("➕ Добавить модератора", "m:in:addmod")])
    rows.append(back("set"))
    return "\n".join(lines), kb(*rows)


async def render(screen: str, user, bot: Bot) -> tuple[str, InlineKeyboardMarkup | None]:
    admin = user.id in ADMIN_IDS
    if screen == "home":
        return await scr_home(user)
    if screen == "ph":
        return await scr_ph()
    if screen == "exp":
        return await scr_exp(admin)
    if screen == "chats":
        return await scr_chats()
    if screen == "phs":
        return await scr_phs(admin)
    if screen == "words":
        return await scr_words()
    if screen == "photos":
        return await scr_photos()
    if screen == "bg":
        return await scr_bg(admin)
    if screen == "set" and admin:
        return await scr_set()
    if screen == "mods" and admin:
        return await scr_mods()
    if screen == "check" and admin:
        return await diagnostics.check_text(bot), kb(back())
    return await scr_home(user)


async def show(event: Message | CallbackQuery, screen: str, bot: Bot, new: bool = False) -> None:
    text, markup = await render(screen, event.from_user, bot)
    if isinstance(event, CallbackQuery) and not new:
        try:
            await event.message.edit_text(text, reply_markup=markup)
            return
        except Exception:
            pass  # текст не изменился или сообщение старое — отправим новое
    target = event.message if isinstance(event, CallbackQuery) else event
    await target.answer(text, reply_markup=markup)


# ---------------------------------------------------------------- вход

@router.message(CommandStart(), F.chat.type == "private")
@router.message(Command(commands=["menu", "help"]), F.chat.type == "private")
async def cmd_start(message: Message, state: FSMContext, bot: Bot) -> None:
    await state.clear()
    user = message.from_user
    await db.save_user(user.id, user.username, user.full_name)
    await show(message, "home", bot)


# ---------------------------------------------------------------- ввод текста для действий

INPUTS = {
    "task": ("📸 Пришли хэштег и текст задания ФотоХанта одним сообщением:\n<code>#кружка Сфоткайся с кружкой</code>", "ph"),
    "word": ("✍️ Пришли слово. Можно с баллами и своим текстом:\n<code>кофе</code>\n<code>кофе 10</code>\n<code>кофе 10 Напишите, как вы пьёте кофе</code>", "phs"),
    "photo": ("🖼 Пришли хэштег и текст фото-задания (можно с баллами):\n<code>#кружка Сфоткайся с кружкой</code>\n<code>#кружка 15 Сфоткайся с кружкой</code>", "phs"),
    "addpoints": ("🛠 Пришли username (или ID) и число баллов, минус — снять:\n<code>@username 10</code>\n<code>@username -5</code>\n\n"
                  "<i>Ещё проще: в группе ответь на сообщение человека командой</i> <code>/addpoints 10</code>", "exp"),
    "addmod": ("👥 Пришли @username или ID будущего модератора.\n<i>Он должен хотя бы раз нажать /start у бота.</i>", "mods"),
}
ADMIN_INPUTS = {"addpoints", "addmod"}


async def ask(callback: CallbackQuery, state: FSMContext, action: str, prompt: str, back_to: str) -> None:
    await state.set_state(MenuInput.waiting)
    await state.update_data(action=action, back=back_to)
    await callback.message.edit_text(prompt, reply_markup=kb([b("✖️ Отмена", f"m:cancel:{back_to}")]))
    await callback.answer()


@router.message(StateFilter(MenuInput.waiting), F.chat.type == "private", F.text, ~F.text.startswith("/"))
async def on_input(message: Message, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    await state.clear()
    action, back_to, text = data.get("action", ""), data.get("back", "home"), message.text.strip()
    if not await is_staff(message.from_user.id):
        return
    if action == "task":
        await photohunt.cmd_task(message, co("task", text), bot)
    elif action == "word":
        await phases.cmd_word(message, co("word", text), bot)
    elif action == "photo":
        await phases.cmd_photo(message, co("photo", text), bot)
    elif action == "addpoints":
        await expedition.cmd_addpoints(message, co("addpoints", text))
    elif action == "addmod":
        who = text.split()[0]
        if who.startswith("@"):
            row = await db.find_user_by_username(who)
            if row is None:
                await message.answer(f"Не знаю {esc(who)} — пусть он нажмёт /start у бота, и попробуй снова.")
                await show(message, back_to, bot)
                return
            who = str(row[0])
        await admin_cmds.cmd_addmod(message, co("addmod", who))
    elif action.startswith("phase:"):
        await phases.cmd_phase(message, co("phase", f"{action.split(':')[1]} {text}"), bot)
    await show(message, back_to, bot)


# ---------------------------------------------------------------- кнопки

@router.callback_query(F.data.startswith("m:"))
async def on_menu(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    parts = callback.data.split(":")
    key = parts[1]
    user = callback.from_user
    staff = await is_staff(user.id)
    admin = user.id in ADMIN_IDS

    # --- делегаты ---
    if key in {"top", "pts"} and not staff:
        if not await visible_to(user.id):
            await show(callback, "home", bot)
            await callback.answer()
            return
        if key == "top":
            text = format_board(await ranking(), user.id)
        else:
            text = await points_text(user.id)
        try:
            await callback.message.edit_text(text, reply_markup=kb(back()))
        except Exception:
            pass
        await callback.answer()
        return
    if not staff:
        await show(callback, "home", bot)
        await callback.answer()
        return

    # --- OC ---
    if key == "cancel":
        await state.clear()
        await show(callback, parts[2] if len(parts) > 2 else "home", bot)
        await callback.answer("Отменено")
        return
    if key == "in":
        action = parts[2]
        if action in ADMIN_INPUTS and not admin:
            await callback.answer("Это может только админ.", show_alert=True)
            return
        if action == "phase" and admin:
            n = parts[3]
            prompt = f"✏️ Пришли текст объявления для <b>{phases.PHASES[int(n)][0]}</b> — он уйдёт в чат делегатов."
            await ask(callback, state, f"phase:{n}", prompt, "phs")
            return
        prompt, back_to = INPUTS[action]
        await ask(callback, state, action, prompt, back_to)
        return
    if key == "top":
        note = "" if await is_active() else "🔒 <i>Сейчас делегаты рейтинг не видят (Экспедиция не идёт).</i>\n\n"
        await callback.message.edit_text(note + format_board(await ranking()), reply_markup=kb(back("exp")))
        await callback.answer()
        return
    if key == "pht":  # открыть/закрыть задание ФотоХанта
        tag = await db.set_task_active_by_id(int(parts[2]), parts[3] == "1")
        await callback.answer(f"#{tag}: {'открыто' if parts[3] == '1' else 'закрыто'}" if tag else "Задание не найдено")
        await show(callback, "ph", bot)
        return
    if key == "ept":  # открыть/закрыть фото-задание фазы
        await db_phases.set_photo_active_by_id(int(parts[2]), parts[3] == "1")
        await callback.answer("Открыто" if parts[3] == "1" else "Закрыто")
        await show(callback, "photos", bot)
        return
    if key == "wordoff":
        closed = await db_phases.close_word_tasks()
        await callback.answer("Слово закрыто" if closed else "Активного слова нет")
        await show(callback, "phs", bot)
        return

    # --- только админ ---
    admin_keys = {"exp", "bg", "phq", "phgo", "phendq", "phend", "revoff", "delmod"}
    if key in admin_keys and len(parts) > 2 and not admin:
        await callback.answer("Это может только админ.", show_alert=True)
        return
    if key == "exp" and len(parts) > 2:
        proxy = as_user(callback, bot)
        if parts[2] == "on":
            await expedition.cmd_expstart(proxy)
        else:
            await expedition.cmd_expstop(proxy)
        await callback.answer()
        await show(callback, "exp", bot, new=True)
        return
    if key == "bg" and len(parts) > 2:
        await db.set_setting("bingo_open", "1" if parts[2] == "on" else "0")
        await callback.answer("Приём бинго включён" if parts[2] == "on" else "Приём бинго выключен")
        await show(callback, "bg", bot)
        return
    if key == "phq":
        n = int(parts[2])
        title, default_text = phases.PHASES[n]
        await callback.message.edit_text(
            f"Начать <b>{title}</b>?\n\nВ чат делегатов уйдёт объявление:\n<i>{esc(default_text)}</i>",
            reply_markup=kb([b("✅ Начать", f"m:phgo:{n}"), b("✏️ Свой текст", f"m:in:phase:{n}")], back("phs")),
        )
        await callback.answer()
        return
    if key == "phgo":
        await callback.answer()
        await phases.cmd_phase(as_user(callback, bot), co("phase", parts[2]), bot)
        await show(callback, "phs", bot, new=True)
        return
    if key == "phendq":
        await callback.message.edit_text(
            "Завершить текущую фазу?\n\nВ чат уйдёт объявление о завершении, активные задания фазы закроются. "
            "Баллы и рейтинг сохранятся.",
            reply_markup=kb([b("✅ Завершить", "m:phend:1")], back("phs")),
        )
        await callback.answer()
        return
    if key == "phend":
        await callback.answer()
        await phases.cmd_phase(as_user(callback, bot), co("phase", "end"), bot)
        await show(callback, "phs", bot, new=True)
        return
    if key == "revoff":
        await db.set_setting("review_chat_id", None)
        await callback.answer("Фото на проверку снова приходят в личку")
        await show(callback, "set", bot)
        return
    if key == "delmod":
        removed = await db.remove_moderator(int(parts[2]))
        await callback.answer("Модератор снят" if removed else "Уже не модератор")
        await show(callback, "mods", bot)
        return

    await show(callback, key, bot)
    await callback.answer()


# ---------------------------------------------------------------- общий чат OC

@router.message(Command("setreviewchat"), F.chat.type.in_(GROUPS), IsAdmin())
async def cmd_setreviewchat(message: Message, bot: Bot) -> None:
    await db.set_setting("review_chat_id", str(message.chat.id))
    await _quiet_confirm(
        message, bot,
        f"📨 Теперь все фото на проверку (ФотоХант, фото-задания, бинго) приходят в «{esc(message.chat.title)}». "
        "Кто первый нажал ✅/❌ — тот и решил, у всех сразу видно.\n"
        "Сбросить обратно в личку: меню → ⚙️ Настройки.",
    )


@router.message(Command("setreviewchat"), F.chat.type == "private", IsAdmin())
async def cmd_setreviewchat_private(message: Message) -> None:
    await message.answer("Создай группу с модераторами, добавь туда бота и отправь <code>/setreviewchat</code> в этой группе.")
