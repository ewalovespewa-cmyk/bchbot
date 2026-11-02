from aiogram import Router

from . import admin, bingo, common, diagnostics, expedition, menu, phase3, phases, photohunt
from .expedition import ExpeditionCounter  # noqa: F401  подключается в main.py


def get_routers() -> list[Router]:
    # phases — до photohunt: фото на задания Экспедиции ловятся первыми,
    # остальные фото (ФотоХант) фильтр фаз пропускает дальше.
    # menu — первым: /start в личке и ввод текста для кнопок.
    return [menu.router, common.router, admin.router, diagnostics.router, expedition.router, phases.router, phase3.router, photohunt.router, bingo.router]
