"""Мелочи для красивых текстов: числа баллов и склонения."""


def num(n) -> str:
    """27.0 → «27», 2.5 → «2,5»."""
    return f"{float(n or 0):g}".replace(".", ",")


def plural(n, one: str, few: str, many: str) -> str:
    """Склонение по числу: 1 балл, 2 балла, 5 баллов; дробные — «2,5 балла»."""
    x = float(n or 0)
    if not x.is_integer():
        return few
    k = abs(int(x))
    if k % 10 == 1 and k % 100 != 11:
        return one
    if 2 <= k % 10 <= 4 and not 12 <= k % 100 <= 14:
        return few
    return many


def points(n) -> str:
    """«27 баллов», «1 балл», «2,5 балла»."""
    return f"{num(n)} {plural(n, 'балл', 'балла', 'баллов')}"
