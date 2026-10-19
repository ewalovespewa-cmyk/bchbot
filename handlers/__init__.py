from aiogram import Router

from . import admin, common, diagnostics, expedition, phase3, phases, photohunt
from .expedition import ExpeditionCounter  # noqa: F401  подключается в main.py


def get_routers() -> list[Router]:
    # phases — до photohunt: фото на задания Экспедиции ловятся первыми,
    # остальные фото (ФотоХант) фильтр фаз пропускает дальше.
    return [common.router, admin.router, diagnostics.router, expedition.router, phases.router, phase3.router, photohunt.router]
