"""Тесты Экспедиции: стоимость сообщений, фильтры, бонус ФотоХанта раз в день,
и что с включённой интеграцией баллы получают только активировавшие бота регистрации."""
import importlib
import os
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from aiogram.types import Message

os.environ.setdefault("BOT_TOKEN", "1:TEST")

GROUP = -1001234567890
DATE = datetime(2026, 10, 19, 10, 0, tzinfo=timezone.utc)


@pytest.fixture
async def exp(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "bot.db"))
    monkeypatch.setenv("ADMIN_IDS", "1")
    monkeypatch.setenv("EXP_COOLDOWN_SECONDS", "0")
    import config

    importlib.reload(config)
    import db

    importlib.reload(db)
    import roles

    importlib.reload(roles)
    import handlers.expedition as expedition

    importlib.reload(expedition)
    await db.init_db()
    await db.add_exp_chat(GROUP, "test")
    return db, expedition


def make(user_id: int = 10, chat_id: int = GROUP, **content) -> Message:
    data = {
        "message_id": 1,
        "date": DATE,
        "chat": {"id": chat_id, "type": "supergroup", "title": "t"},
        "from": {"id": user_id, "is_bot": False, "first_name": "U"},
    }
    data.update(content or {"text": "привет"})
    return Message.model_validate(data)


async def test_points_per_type(exp):
    db, expedition = exp
    assert await expedition.count_message(make(text="ок"))
    assert await expedition.count_message(make(voice={"file_id": "v", "file_unique_id": "v", "duration": 1}))
    assert await expedition.count_message(make(video_note={"file_id": "c", "file_unique_id": "c", "length": 1, "duration": 1}))
    assert await db.get_points(10) == 1 + 3 + 3


async def test_not_counted(exp):
    db, expedition = exp
    assert not await expedition.count_message(make(text="/top"))
    assert not await expedition.count_message(make(user_id=1, text="я админ"))
    assert not await expedition.count_message(make(chat_id=-100777, text="чужой чат"))
    assert not await expedition.count_message(make(new_chat_members=[{"id": 10, "is_bot": False, "first_name": "U"}]))
    await db.set_setting("exp_active", "0")
    expedition.reset_cache()
    assert not await expedition.count_message(make(text="пауза"))
    assert await db.get_points(10) == 0


async def test_photohunt_bonus_once_per_day(exp):
    db, _ = exp
    assert await db.award_photohunt_day(10, "2026-10-19", 1, 5)
    assert not await db.award_photohunt_day(10, "2026-10-19", 2, 5)
    assert await db.award_photohunt_day(10, "2026-10-20", 3, 5)
    assert await db.get_points(10) == 10


async def test_gate_blocks_counting_for_not_activated(exp, monkeypatch):
    """Порядок как в main.py: сначала фильтр доступа, потом счётчик."""
    db, expedition = exp
    from integration import gate

    importlib.reload(gate)
    monkeypatch.setattr(gate.access, "is_activated", AsyncMock(side_effect=lambda uid: uid == 10))
    counter = expedition.ExpeditionCounter()
    handler = AsyncMock()

    async def chain(event):
        return await gate.AccessGate()(lambda e, d: counter(handler, e, d), event, {})

    await chain(make(user_id=10, text="я активировал"))
    await chain(make(user_id=20, text="а я нет"))
    assert await db.get_points(10) == 1
    assert await db.get_points(20) == 0
