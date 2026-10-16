"""Помощники для объектов ответа: разбор дат, ссылок и простых типов."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

_FRACTION = re.compile(r"\.(\d+)")


def parse_datetime(value: Any) -> Optional[datetime]:
    """Разобрать дату ISO 8601 из ответа MaxPatrol.

    Понимает суффикс ``Z`` и доли секунды любой длины (.NET отдаёт до 7 знаков).
    Время без часового пояса считается временем UTC: так время хранит MaxPatrol.
    Нераспознанное значение даёт ``None``; исходная строка остаётся в ``raw``.
    """
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text[-1] in "Zz":
        text = text[:-1] + "+00:00"
    text = _FRACTION.sub(lambda m: "." + (m.group(1) + "000000")[:6], text, count=1)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def as_str(value: Any) -> Optional[str]:
    if value is None or isinstance(value, (dict, list)):
        return None
    return str(value)


def as_bool(value: Any) -> bool:
    return value is True


def as_int(value: Any) -> Optional[int]:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


@dataclass(frozen=True)
class Ref:
    """Ссылка на связанный объект: идентификатор и имя."""

    id: Optional[str]
    name: Optional[str]

    @classmethod
    def parse(cls, value: Any) -> Optional[Ref]:
        if isinstance(value, dict):
            return cls(id=as_str(value.get("id")), name=as_str(value.get("name")))
        if isinstance(value, str) and value:
            return cls(id=value, name=None)
        return None


RawDict = Dict[str, Any]
