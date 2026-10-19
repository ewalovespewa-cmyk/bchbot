"""Тесты интеграции с ботом регистрации: подпись событий, статус доступа, гейт, фильтр бинго."""
import hashlib
import hmac
import importlib
import json
import os
import time
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp.test_utils import TestClient, TestServer

os.environ.setdefault("BOT_TOKEN", "1:TEST")


@pytest.fixture
async def env(tmp_path, monkeypatch):
    """Чистая SQLite и включённая интеграция на каждый тест."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "bot.db"))
    monkeypatch.setenv("BC_API_URL", "http://regbot.test")
    monkeypatch.setenv("BC_API_TOKEN", "tok")
    monkeypatch.setenv("BC_WEBHOOK_SECRET", "sec")
    import config

    importlib.reload(config)
    import db

    importlib.reload(db)
    from integration import config as icfg

    importlib.reload(icfg)
    from integration import access, events, gate

    for module in (access, events, gate):
        importlib.reload(module)
    await db.init_db()
    await access.init()
    return access, events, gate


def signed(body: dict, secret: str = "sec", ts: int | None = None) -> tuple[bytes, dict]:
    raw = json.dumps(body).encode()
    ts = str(ts or int(time.time()))
    sig = "sha256=" + hmac.new(secret.encode(), ts.encode() + b"." + raw, hashlib.sha256).hexdigest()
    return raw, {"X-BC-Timestamp": ts, "X-BC-Signature": sig, "Content-Type": "application/json"}


async def _client(events) -> TestClient:
    client = TestClient(TestServer(events.make_app()))
    await client.start_server()
    return client


async def test_events_signature_idempotency_and_status(env):
    access, events, _ = env
    client = await _client(events)
    try:
        linked = {"event_id": "e1", "type": "participant.linked", "data": {"telegram_user_id": 42}}
        raw, headers = signed(linked, secret="wrong")
        assert (await client.post("/bc-events", data=raw, headers=headers)).status == 401

        raw, headers = signed(linked)
        assert (await client.post("/bc-events", data=raw, headers=headers)).status == 200
        assert await access.is_activated(42) is True
        assert await access.is_checked_in(42) is False

        checkin = {"event_id": "e2", "type": "checkin.created", "data": {"telegram_user_id": 42, "day": access.today()}}
        raw, headers = signed(checkin)
        await client.post("/bc-events", data=raw, headers=headers)
        assert await access.is_checked_in(42) is True

        resp = await client.post("/bc-events", data=raw, headers=headers)  # повтор того же события
        assert (await resp.json())["duplicate"] is True

        cancel = {"event_id": "e3", "type": "checkin.cancelled", "data": {"telegram_user_id": 42, "day": access.today()}}
        raw, headers = signed(cancel)
        await client.post("/bc-events", data=raw, headers=headers)
        assert await access.is_checked_in(42) is False

        stale_raw, stale_headers = signed({"event_id": "e4", "type": "participant.unlinked", "data": {}}, ts=int(time.time()) - 3 * 86400)
        assert (await client.post("/bc-events", data=stale_raw, headers=stale_headers)).status == 401
    finally:
        await client.close()


async def test_api_fallback_and_last_known_status(env, monkeypatch):
    access, _, _ = env
    monkeypatch.setattr(access, "fetch_from_api", AsyncMock(return_value=(True, [])))
    assert await access.is_activated(7) is True  # спросили API и закэшировали

    monkeypatch.setattr(access, "fetch_from_api", AsyncMock(return_value=None))  # API лёг
    assert await access.is_activated(7) is True  # берём последний известный статус
    assert await access.is_activated(8) is None  # про этого не знаем ничего


def _message(user_id: int, text: str = "/start", chat_type: str = "private") -> MagicMock:
    from aiogram.types import Message

    msg = MagicMock(spec=Message)
    msg.from_user = MagicMock(id=user_id, is_bot=False)
    msg.text, msg.photo, msg.document = text, None, None
    msg.chat = MagicMock(type=chat_type)
    msg.answer, msg.reply = AsyncMock(), AsyncMock()
    return msg


async def test_gate_blocks_strangers_and_passes_activated_and_staff(env, monkeypatch):
    access, _, gate = env
    monkeypatch.setattr(gate, "is_staff", AsyncMock(side_effect=lambda uid: uid == 1))
    monkeypatch.setattr(access, "fetch_from_api", AsyncMock(return_value=(False, [])))
    handler = AsyncMock(return_value="handled")
    mw = gate.AccessGate()

    stranger = _message(99)
    assert await mw(handler, stranger, {}) is None
    assert "активируй бота участника" in stranger.answer.await_args.args[0]

    assert await mw(handler, _message(99, "/myid"), {}) == "handled"  # /myid можно всем
    assert await mw(handler, _message(1), {}) == "handled"  # персонал

    await access.save(5, True, [], "event")
    assert await mw(handler, _message(5), {}) == "handled"


async def test_bingo_filter_requires_checkin_today(env, monkeypatch):
    access, _, gate = env
    monkeypatch.setattr(gate, "is_staff", AsyncMock(return_value=False))
    await access.save(5, True, [], "event")
    msg = _message(5)
    assert await gate.IsCheckedIn()(msg) is False
    assert "Бинго откроется" in msg.answer.await_args.args[0]
    await access.save(5, True, [access.today()], "event")
    assert await gate.IsCheckedIn()(_message(5)) is True
