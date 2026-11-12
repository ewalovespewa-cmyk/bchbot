"""Бот вообще запускается: main.py импортируется без синтаксических ошибок."""
import os

os.environ.setdefault("BOT_TOKEN", "1:TEST")


def test_main_imports():
    import main

    assert callable(main.main)
