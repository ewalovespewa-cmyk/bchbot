"""Интеграция с ботом регистрации Business Cup (bc2regbot).

Подключение — одна строка в main.py: `runner = await setup_integration(dp)`.
Без переменной BC_API_URL ничего не включается.
"""
import logging

from aiogram import Dispatcher, F, Router
from aiogram.types import ChatJoinRequest

from integration import access, config, events
from integration.gate import AccessGate, IsCheckedIn  # noqa: F401  IsCheckedIn — для хендлеров бинго

log = logging.getLogger(__name__)


def _join_router() -> Router:
    router = Router(name="bc_join_requests")

    @router.chat_join_request(F.chat.type.in_({"group", "supergroup"}))
    async def on_join_request(request: ChatJoinRequest) -> None:
        if await access.is_activated(request.from_user.id):
            await request.approve()
            log.info("Заявка в чат %s одобрена: %s", request.chat.id, request.from_user.id)
        else:
            await request.decline()
            log.info("Заявка в чат %s отклонена (не активировал бота регистрации): %s", request.chat.id, request.from_user.id)

    return router


async def setup_integration(dp: Dispatcher):
    """Включает гейт доступа и приём событий. Возвращает aiohttp runner (или None, если выключено)."""
    if not config.ENABLED:
        log.info("Интеграция с ботом регистрации выключена (BC_API_URL не задан)")
        return None
    await access.init()
    gate = AccessGate()
    dp.message.outer_middleware(gate)
    dp.callback_query.outer_middleware(gate)
    if config.BC_AUTO_APPROVE_JOIN:
        dp.include_router(_join_router())
    runner = await events.start_server()
    log.info("Интеграция с ботом регистрации включена: %s", config.BC_API_URL)
    return runner
