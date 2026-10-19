"""Тесты фаз Экспедиции: проверка «предложения со словом»."""
import os

os.environ.setdefault("BOT_TOKEN", "1:TEST")

from handlers.phases import is_sentence, word_matches  # noqa: E402


def test_word_forms():
    assert word_matches("Пью чай из кружки", "кружка")
    assert word_matches("Утром с кружкой кофе", "кружка")
    assert word_matches("Хочу КОФЕ прямо сейчас", "кофе")
    assert word_matches("Ёлка стоит в зале", "елка")
    assert not word_matches("Пью чай из стакана", "кружка")
    assert word_matches("мы идём на бизнес кап завтра", "бизнес кап")


def test_sentence_needs_words():
    assert not is_sentence("кружка")
    assert not is_sentence("моя кружка")
    assert is_sentence("моя любимая кружка")
