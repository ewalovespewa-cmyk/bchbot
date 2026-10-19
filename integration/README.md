# Интеграция с ботом регистрации (bc2regbot)

Правило доступа:
- **Фотохант и экспедиция** (до проекта) — для всех, кто активировал бота регистрации.
- **Бинго** (на проекте) — только для тех, кто сегодня отметился на входе.
- Админы и модераторы этого бота проходят всегда.

## Как работает
1. Человек активирует бота регистрации (персональная ссылка или контакт). Бот регистрации шлёт
   сюда событие `participant.linked`.
2. На входе человек сканирует QR. Бот регистрации шлёт `checkin.created` и присылает человеку
   кнопку «🎲 Открыть бинго» (обычная ссылка на этого бота).
3. Этот бот хранит статус в той же SQLite (таблицы `bc_access`, `bc_events`). Если статуса
   нет или он устарел, бот спрашивает API бота регистрации. Если API недоступен, используется
   последний известный статус.

`AccessGate` (outer middleware) не пускает к существующим хендлерам тех, кто не активировал
бота регистрации. В личке он отвечает подсказкой со ссылкой, в общем чате изредка отвечает
на фото, и такие фото не уходят на проверку.

Для бинго есть фильтр `IsCheckedIn`:
```python
from integration import IsCheckedIn

@router.message(Command("bingo"), IsCheckedIn())
async def cmd_bingo(message: Message) -> None:
    ...  # сюда попадут только отметившиеся сегодня
```

## Контракт
**События** — `POST /bc-events` на этом боте (порт `PORT`):
```
X-BC-Event-Id: <uuid>
X-BC-Timestamp: <unix seconds>
X-BC-Signature: sha256=<hex HMAC-SHA256(BC_WEBHOOK_SECRET, "<timestamp>.<raw body>")>

{"event_id": "…", "type": "checkin.created", "created_at": "…",
 "data": {"telegram_user_id": 123, "participant_id": 5, "team": "Rockets",
          "day": "2026-11-14", "day_label": "День 1", "method": "self_qr", "timestamp": "…"}}
```
Типы событий: `participant.linked`, `participant.unlinked`, `checkin.created`, `checkin.cancelled`.
Ответ 2xx — принято. Повтор того же `event_id` подтверждается и не применяется второй раз.
Если этот бот лежит, бот регистрации повторяет доставку до суток.

**API** бота регистрации, заголовок `Authorization: Bearer <BC_API_TOKEN>`:
- `GET /api/participant-status?telegram_user_id=…` возвращает
  `{activated, participant_id, full_name, team, checkins: [{day, at}], checked_in_today}`;
- `GET /api/checkin-status?telegram_user_id=…&day=YYYY-MM-DD` возвращает `{checked_in, at}`.

## Настройка на Railway
1. Оба сервиса в одном Railway-проекте, приём событий идёт по приватной сети.
2. В этом боте задай переменные:
   - `BC_API_URL=http://${{bc2regbot.RAILWAY_PRIVATE_DOMAIN}}:8080`
   - `BC_API_TOKEN=${{bc2regbot.INTEGRATION_TOKEN}}`
   - `BC_WEBHOOK_SECRET=${{bc2regbot.GAMIFICATION_WEBHOOK_SECRET}}`
3. В боте регистрации задай переменные:
   - `GAMIFICATION_WEBHOOK_URL=http://${{bchbot.RAILWAY_PRIVATE_DOMAIN}}:8080/bc-events` (а в этом боте `PORT=8080`)
   - `GAMES_BOT_USERNAME=<username этого бота>`
4. Автоодобрение заявок в общий чат (`BC_AUTO_APPROVE_JOIN=1`):
   - бот должен быть админом чата с правом «Добавлять участников»;
   - ссылка-приглашение должна быть со включённой «Заявкой на вступление».
