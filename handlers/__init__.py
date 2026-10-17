from aiogram import Router

from . import admin, common, photohunt


def get_routers() -> list[Router]:
    return [common.router, admin.router, photohunt.router]
