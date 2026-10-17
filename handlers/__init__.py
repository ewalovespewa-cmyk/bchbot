from aiogram import Router

from . import admin, common


def get_routers() -> list[Router]:
    return [common.router, admin.router]
