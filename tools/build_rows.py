import json, re, sys
rows = json.load(open(sys.argv[1], encoding="utf-8"))

# раздел, кто видит, когда появляется — по функции
D = "Делегат (личка)"; DC = "Делегаты (общий чат)"; OC = "OC"; ALL = "Все"
CTX = {
 ("chatutil.py","sync_commands"): ("Подсказки команд", ALL, "Подсказки при вводе «/» (описания команд)"),
 ("chatutil.py","menu_button"): ("Служебное", D, "Кнопка-ссылка в личку бота"),
 ("chatutil.py","to_menu"): ("Служебное", DC, "Подпись к кнопке «Открыть меню»"),
 ("menu.py","back"): ("Кнопки меню", ALL, "Кнопки «назад»"),
 ("menu.py","scr_home"): ("Главное меню (/start)", ALL, "Экран /start в личке: приветствие делегату и панель OC"),
 ("expedition.py","format_board"): ("Экспедиция · лидерборд", DC, "Лидерборд (/top в чате и кнопка в личке)"),
 ("expedition.py","ranking"): ("Экспедиция · лидерборд", DC, "Имя, если у человека нет имени"),
 ("expedition.py","points_text"): ("Экспедиция · мои баллы", D, "Кнопка «Мои баллы» в личке"),
 ("expedition.py","cmd_points"): ("Экспедиция · мои баллы", DC, "/points в чате (исчезает через минуту)"),
 ("common.py","(модуль)"): ("Команды в группе", DC, "Список команд для /help в чате (и старый список команд OC — /commands)"),
 ("common.py","_group_help"): ("Команды в группе", DC, "/help и /start в чате (исчезает через минуту)"),
 ("common.py","cmd_commands"): ("Служебное OC", OC, "/commands — список команд OC"),
 ("common.py","cmd_myid"): ("Служебное OC", OC, "/myid"),
 ("phases.py","(модуль)"): ("Фазы · объявления", DC, "Названия фаз и текст объявления о старте фазы в чате"),
 ("phases.py","cmd_phase"): ("Фазы · объявления", DC, "Объявление о старте/конце фазы в чате + ответы админу"),
 ("phases.py","cmd_word"): ("Фаза 1 · слова", DC, "Пост с заданием-словом в чате + ответы OC"),
 ("phases.py","on_word_answer"): ("Фаза 1 · слова", D, "Ответы делегату на его ответ (в личку)"),
 ("phases.py","cmd_photo"): ("Фаза 2 · фото", DC, "Пост с фото-заданием в чате + ответы OC"),
 ("phases.py","on_photo_answer"): ("Фаза 2 · фото", D, "Ответы делегату на его фото (в личку)"),
 ("phases.py","on_photo_without_tag"): ("Фаза 2 · фото", D, "Делегат прислал фото без хэштега (в личку)"),
 ("phases.py","on_photo_review"): ("Фаза 2 · фото", D, "Результат проверки фото: делегату + кнопки/подписи OC"),
 ("phases.py","_review_kb"): ("Фаза 2 · фото", OC, "Кнопки проверки фото"),
 ("phases.py","_review_caption"): ("Фаза 2 · фото", OC, "Подпись фото на проверке у OC"),
 ("photohunt.py","cmd_task"): ("ФотоХант", DC, "Пост с заданием ФотоХанта в чате + ответы OC"),
 ("photohunt.py","on_group_photo"): ("ФотоХант", D, "Ответы делегату на повторное фото (в личку)"),
 ("photohunt.py","on_review"): ("ФотоХант", D, "Результат проверки фото: делегату + подписи OC"),
 ("photohunt.py","review_keyboard"): ("ФотоХант", OC, "Кнопки проверки фото"),
 ("photohunt.py","review_caption"): ("ФотоХант", OC, "Подпись фото на проверке у OC"),
 ("bingo.py","grid"): ("Бинго · карточка", D, "Карточка бинго 3×3 в личке"),
 ("bingo.py","to_card_kb"): ("Бинго · карточка", D, "Кнопка «к карточке»"),
 ("bingo.py","on_card"): ("Бинго · карточка", D, "Нажатие на номер задания"),
 ("bingo.py","on_answer"): ("Бинго · сдача", D, "Ответы после отправки задания"),
 ("bingo.py","on_stray_media"): ("Бинго · сдача", D, "Фото в личку без выбранного задания"),
 ("bingo.py","on_review"): ("Бинго · результат", D, "Результат проверки задания (делегату) + подписи/ответы OC"),
 ("bingo.py","_header"): ("Бинго · проверка OC", OC, "Шапка задания на проверке у OC"),
 ("bingo.py","_review_kb"): ("Бинго · проверка OC", OC, "Кнопки проверки"),
 ("bingo.py","send_to_review"): ("Бинго · проверка OC", OC, "Пометка тестовой сдачи OC"),
 ("bingo.py","status_text"): ("Бинго · OC", OC, "Раздел «Бинго» в панели OC"),
 ("bingo.py","cmd_bingo"): ("Бинго · OC", OC, "Включение/выключение приёма"),
 ("gate.py","not_activated_text"): ("Доступ (бот регистрации)", D, "Если человек не активировал бота регистрации"),
 ("gate.py","(модуль)"): ("Доступ (бот регистрации)", D, "Ошибка проверки / бинго до чекина"),
}
OC_PREFIX = {"menu.py","admin.py","diagnostics.py"}
OC_FUNCS_PREFIX = ("cmd_track","cmd_untrack","cmd_chats","cmd_expstart","cmd_expstop","cmd_addpoints","_apply_points","_quiet_confirm","_where","_status_line","cmd_top_private","_blind_warning","cmd_setphasechat","_require_open","cmd_wordoff","cmd_words","cmd_photos","_toggle_photo","cmd_setchat","cmd_tasks","_toggle_task")

# фрагменты, которые видит OC внутри «делегатских» функций
OC_MARKERS = ("Засчитал(а)", "Не засчитал(а)", "Отклонил(а)", "проверил кто-то", "только OC", "старая кнопка",
              "Засчитано ✅", "Отклонено ❌", "Не засчитано ❌", "собрал(а) всё бинго", "Проверка OC", "Напиши так",
              "опубликовано", "Не получилось опубликовать", "уже было. Придумай", "уже есть. Придумай", "Сначала укажи чат",
              "Задание сохранено", "Переключать фазы", "Сейчас: <b>", "завершена.</b>", "Началась <b>", "никакая фаза",
              "Объявление о завершении", "Объявление не опубликовано", "Объявление опубликовано", "Закрыто:", "активных заданий не было",
              "Экспедиция открыта: делегатам", "Включать и выключать", "Приём бинго", "только админ", "Напиши <code>")

SKIP_TEXT = {"ё", "е", "вкл", "выкл", "on", "off", "стоп", "конец"}

def humanize(t):
    reps = [
        (r"\{esc\((?:user|message\.from_user|callback\.from_user)\.first_name\)\}", "{имя}"),
        (r"\{esc\(callback\.from_user\.full_name\)\}", "{кто проверил}"),
        (r"\{(?:who|reviewer)\}", "{кто}"), (r"\{_who\(item\)\}", "{кто сдал}"),
        (r"\{(?:cell|item\['cell'\])\}", "{номер задания}"),
        (r"\{esc\((?:task|photo_task|sub)\['hashtag'\]\)\}|\{esc\(hashtag\)\}|\{esc\(t\['hashtag'\]\)\}|\{t\['hashtag'\]\}|\{esc\(r\['hashtag'\]\)\}", "{хэштег}"),
        (r"\{esc\((?:word_task|word|r)\['word'\]\)\}|\{esc\(word\)\}|\{word\}", "{слово}"),
        (r"\{(?:word_task|sub|t|r)\['points'\]\}|\{points\}", "{баллы}"),
        (r"\{total\}", "{баллов всего}"), (r"\{place\}", "{место}"), (r"\{done\}", "{засчитано}"),
        (r"\{CELLS\}", "9"), (r"\{PHASE_WORD_MIN_WORDS\}", "3"), (r"\{EXP_PHOTOHUNT_DAY_POINTS\}", "5"),
        (r"\{EXP_TOP_SIZE\}", "15"), (r"\{EXP_PRIZE_PLACES\}", "10"), (r"\{EXP_PRIZE_PLACES \+ 1\}", "11"),
        (r"\{PHASE_WORD_POINTS\}", "5"), (r"\{PHASE_PHOTO_POINTS\}", "10"),
        (r"\{esc\(text\.strip\(\)\) or default_text\}", "{текст объявления}"),
        (r"\{esc\(text\)\}|\{esc\(sub\['task_text'\]\)\}|\{esc\(t\['text'\]\)\}|\{esc\(r\['text'\]\)\}", "{текст задания}"),
        (r"\{title\}", "{название фазы}"), (r"\{stamp\}", "{дата и время}"),
        (r"\{esc\(item\['content'\]\)\}", "{ответ делегата}"),
        (r"\{esc\(message\.chat\.title\)\}", "{название чата}"),
        (r"\{mark\}", "{медаль/место}"), (r"\{name\}", "{имя}"), (r"\{gift\}", " 🎁"),
        (r"\{again\}", "{пометка «в прошлый раз не засчитали»}"), (r"\{what\}", "{текст/фото}"),
        (r"\{listed\}", "{номера}"), (r"\{amount:\+d\}", "{±баллы}"),
        (r"\{b\['(?:messages|voices|photohunt_days|word_count|photo_count)'\]\}", "{сколько}"),
        (r"\{b\['(?:photohunt_points|word_points|photo_points)'\]\}", "{баллы}"),
        (r"\{b\['adjust_points'\]:\+d\}|\{b\['adjust_points'\]\}", "{±баллы}"),
        (r"\{mine\[0\]\}", "{место}"), (r"\{mine\[3\]\}", "{баллы}"), (r"\{gap\}", "{сколько не хватает}"),
        (r"\{user_id\}", "{ID}"),
        (r"\{esc\(text\.strip\(\)\) or '([^']*)'\}", r"{свой текст, иначе: }"), (r"\{esc\(name\)\}", "{имя}"),
    ]
    t = re.sub(r"\{esc\(text\.strip\(\)\) or '([^']*)'\}", lambda m: "{свой текст, иначе: " + m.group(1) + "}", t)
    t = t.replace("{config.BC_REG_BOT_USERNAME}", "{бот регистрации}")
    for a, b in reps:
        t = re.sub(a, b, t)
    # условные куски: {'A' if x else 'B'} -> [A / B]
    t = re.sub(r"\{'([^']*)' if [^{}]*? else '([^']*)'\}", r"[\1 / \2]", t)
    t = re.sub(r'\{"([^"]*)" if [^{}]*? else "([^"]*)"\}', r"[\1 / \2]", t)
    return t

HOME_SPLIT = next(r["line"] for r in rows if r["func"] == "scr_home" and "Следи за новостями" in r["text"])
out = []
for r in rows:
    f = r["file"].split("/")[-1]; fn = r["func"]; t = r["text"]
    if t.strip() in SKIP_TEXT:
        continue
    if (f, fn) in CTX:
        sec, who, when = CTX[(f, fn)]
    elif f in OC_PREFIX or fn.startswith(OC_FUNCS_PREFIX):
        nice = {"menu.py": "Панель OC (меню)", "admin.py": "Модераторы", "diagnostics.py": "Проверка /check"}.get(f, "Экспедиция · управление OC")
        sec, who, when = nice, OC, fn
    else:
        sec, who, when = "Прочее", OC, fn
    if who != OC and any(m in t for m in OC_MARKERS):
        who = OC
    # экран /start: всё после приветствия делегата — панель OC
    if (f, fn) == ("menu.py", "scr_home") and r["line"] > HOME_SPLIT:
        who = OC; sec = "Панель OC (меню)"; when = "Панель OC на /start"
    elif (f, fn) == ("menu.py", "scr_home"):
        who = D
    if (f, fn) == ("common.py", "(модуль)") and ("ФотоХант (для OC)" in t or "Только для админа" in t):
        who = OC; sec = "Служебное OC"; when = "/commands — список команд OC"
    if (f, fn) in {("chatutil.py", "menu_button"), ("chatutil.py", "to_menu")}:
        continue  # больше не используется
    if t in ("✅ у делегата такой ответ засчитался бы.", "❌ такой ответ не засчитался бы.", "между фазами"):
        who = OC
    if "Ты OC" in t or "OC баллы не получает" in t or t.startswith(("слово «", "фото-заданий:")):
        who = OC
    if (f, fn) == ("expedition.py", "format_board") and ("Ты на" in t or "Тебя пока нет" in t):
        who = D; when = "Кнопка «Лидерборд» в личке: строка про своё место"
    out.append({"section": sec, "who": who, "when": when, "text": humanize(t), "src": f"{r['file']}:{r['line']}"})

order = ["Главное меню (/start)", "Подсказки команд", "Команды в группе", "Экспедиция · лидерборд", "Экспедиция · мои баллы",
         "Фазы · объявления", "Фаза 1 · слова", "Фаза 2 · фото", "ФотоХант", "Бинго · карточка", "Бинго · сдача",
         "Бинго · результат", "Доступ (бот регистрации)", "Кнопки меню", "Служебное",
         "Бинго · проверка OC", "Бинго · OC", "Панель OC (меню)", "Экспедиция · управление OC", "Модераторы",
         "Проверка /check", "Служебное OC", "Прочее"]
out.sort(key=lambda x: (0 if x["who"] != OC else 1, order.index(x["section"]) if x["section"] in order else 99, x["src"]))
for i, x in enumerate(out, 1):
    x["id"] = i
json.dump(out, open(sys.argv[2], "w", encoding="utf-8"), ensure_ascii=False, indent=0)
from collections import Counter
print(len(out), Counter(x["who"] for x in out))
print(Counter(x["section"] for x in out if x["section"] == "Прочее"))
