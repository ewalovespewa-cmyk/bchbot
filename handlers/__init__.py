from aiogram import Router

from . import admin, common, expedition, photohunt
from .expedition import ExpeditionCounter  # noqa: F401  подключается в main.py


def get_routers() -> list[Router]:
    return [common.router, admin.router, expedition.router, photohunt.router]
