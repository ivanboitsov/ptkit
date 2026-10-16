"""Чтение плоского TOML-файла настроек.

В Python 3.11+ используется стандартный ``tomllib``. Для 3.9–3.10 — встроенный
разборщик подмножества TOML: пары ``ключ = значение`` верхнего уровня, строки
в двойных и одинарных кавычках, целые и дробные числа, ``true``/``false``,
комментарии. Этого достаточно для ``ptkit.toml`` и не требует зависимостей.
"""

from __future__ import annotations

import re
import sys
from typing import Any, Dict, List, Tuple

__all__ = ["loads"]

_KEY = re.compile(r"[A-Za-z0-9_-]+")
_ESCAPES = {"b": "\b", "t": "\t", "n": "\n", "f": "\f", "r": "\r", '"': '"', "\\": "\\"}
_NUMBER = re.compile(r"[+-]?(\d[\d_]*)(\.\d[\d_]*)?([eE][+-]?\d+)?")


def loads(text: str) -> Dict[str, Any]:
    if sys.version_info >= (3, 11):
        import tomllib

        return tomllib.loads(text)
    return _loads_flat(text)


def _loads_flat(text: str) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for number, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("["):
            raise ValueError(f"Строка {number}: таблицы в файле настроек ptkit не поддерживаются")
        key, sep, rest = stripped.partition("=")
        key = key.strip()
        if not sep or not _KEY.fullmatch(key):
            raise ValueError(f"Строка {number}: ожидалось «ключ = значение»")
        if key in result:
            raise ValueError(f"Строка {number}: ключ {key!r} задан повторно")
        value, tail = _parse_value(rest.strip(), number)
        tail = tail.strip()
        if tail and not tail.startswith("#"):
            raise ValueError(f"Строка {number}: лишние символы после значения")
        result[key] = value
    return result


def _parse_value(text: str, number: int) -> Tuple[Any, str]:
    if text.startswith('"'):
        out: List[str] = []
        i = 1
        while i < len(text):
            ch = text[i]
            if ch == '"':
                return "".join(out), text[i + 1 :]
            if ch == "\\":
                i += 1
                esc = text[i : i + 1]
                if esc in _ESCAPES:
                    out.append(_ESCAPES[esc])
                elif esc in ("u", "U"):
                    size = 4 if esc == "u" else 8
                    out.append(chr(int(text[i + 1 : i + 1 + size], 16)))
                    i += size
                else:
                    raise ValueError(f"Строка {number}: неизвестная escape-последовательность")
            else:
                out.append(ch)
            i += 1
        raise ValueError(f"Строка {number}: незакрытая строка")
    if text.startswith("'"):
        end = text.find("'", 1)
        if end < 0:
            raise ValueError(f"Строка {number}: незакрытая строка")
        return text[1:end], text[end + 1 :]
    for word, value in (("true", True), ("false", False)):
        if text.startswith(word) and not text[len(word) : len(word) + 1].isalnum():
            return value, text[len(word) :]
    match = _NUMBER.match(text)
    if match:
        raw = match.group(0).replace("_", "")
        is_float = match.group(2) is not None or match.group(3) is not None
        return (float(raw) if is_float else int(raw)), text[match.end() :]
    raise ValueError(f"Строка {number}: неподдерживаемое значение")
