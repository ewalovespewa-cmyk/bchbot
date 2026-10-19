"""Приём событий от бота регистрации: POST /bc-events.

Бот регистрации шлёт события participant.linked / participant.unlinked /
checkin.created / checkin.cancelled с подписью
    X-BC-Signature: sha256=HMAC-SHA256(BC_WEBHOOK_SECRET, "<X-BC-Timestamp>.<тело>")
Повторная доставка того же X-BC-Event-Id игнорируется (но отвечаем 200, чтобы не слали снова).
"""
import hashlib
import hmac
import json
import logging
import time

import aiosqlite
from aiohttp import web

from config import DB_PATH
from integration import access, config

log = logging.getLogger(__name__)

MAX_SKEW = 24 * 3600  # события из outbox могут прийти с опозданием до суток


def valid_signature(secret: str, timestamp: str, body: bytes, signature: str) -> bool:
    if not secret or not timestamp or not signature:
        return False
    expected = "sha256=" + hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


async def _seen(event_id: str, event_type: str) -> bool:
    """Отмечает событие полученным. True — уже было."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT OR IGNORE INTO bc_events (event_id, type, received_at) VALUES (?, ?, ?)",
            (event_id, event_type, time.time()),
        )
        await db.commit()
        return cur.rowcount == 0


async def apply_event(event_type: str, data: dict) -> None:
    user_id = data.get("telegram_user_id")
    if not user_id:
        return
    current = await access._get(int(user_id))
    activated, days = (current[0], current[1]) if current else (False, [])
    if event_type == "participant.linked":
        activated = True
    elif event_type == "participant.unlinked":
        activated = False
    elif event_type == "checkin.created":
        activated, days = True, [*days, data["day"]]
    elif event_type == "checkin.cancelled":
        days = [d for d in days if d != data.get("day")]
    else:
        log.info("Неизвестное событие %s — пропускаю", event_type)
        return
    await access.save(int(user_id), activated, days, "event")


async def handle(request: web.Request) -> web.Response:
    body = await request.read()
    ts = request.headers.get("X-BC-Timestamp", "")
    if not valid_signature(config.BC_WEBHOOK_SECRET, ts, body, request.headers.get("X-BC-Signature", "")):
        return web.Response(status=401, text="bad signature")
    try:
        if abs(time.time() - int(ts)) > MAX_SKEW:
            return web.Response(status=401, text="stale")
        event = json.loads(body)
        event_id, event_type = event["event_id"], event["type"]
    except (ValueError, KeyError):
        return web.Response(status=400, text="bad request")

    if await _seen(event_id, event_type):
        return web.json_response({"ok": True, "duplicate": True})
    await apply_event(event_type, event.get("data") or {})
    log.info("Событие %s от бота регистрации применено", event_type)
    return web.json_response({"ok": True})


async def health(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


def make_app() -> web.Application:
    app = web.Application()
    app.router.add_post("/bc-events", handle)
    app.router.add_get("/health", health)
    return app


async def start_server() -> web.AppRunner:
    runner = web.AppRunner(make_app(), access_log=None)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", config.BC_EVENTS_PORT).start()
    log.info("Приём событий от бота регистрации: порт %s", config.BC_EVENTS_PORT)
    return runner
