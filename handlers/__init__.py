from aiogram import Router

from . import admin, bingo, common, diagnostics, expedition, menu, photohunt, words
from .expedition import ExpeditionCounter  # noqa: F401  подключается в main.py


def get_routers() -> list[Router]:
    # menu — первым: /start в личке и ввод текста для кнопок.
    return [menu.router, common.router, admin.router, diagnostics.router, expedition.router, words.router, photohunt.router, bingo.router]
