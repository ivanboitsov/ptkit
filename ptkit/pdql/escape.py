"""Экранирование значений для подстановки в PDQL.

Правила взяты из справочника PDQL (MaxPatrol VM 2.7, «Типы данных»):

- строка заключается в одинарные или двойные кавычки;
- IP-адрес, подсеть, UUID, дата и время, число, ``true``/``false``, ``null``
  записываются без кавычек;
- список записывается в квадратных скобках через запятую.

Обратная косая черта внутри строки удваивается: так она записана в примерах
PDQL в документации MaxPatrol SIEM (``"C:\\\\ProgramData"``). Экранирование
кавычек в документации не описано, поэтому строка заключается в тот вид
кавычек, которого в ней нет. Значения, в которых есть оба вида кавычек или
управляющие символы, отклоняются: их нельзя безопасно записать в запрос.

Значение без кавычек получается только из типизированного объекта Python
(``uuid.UUID``, ``ipaddress``, ``datetime``, число), строковое представление
которого не может изменить структуру запроса.
"""

from __future__ import annotations

import ipaddress
import math
import re
import uuid
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Iterable

__all__ = ["quote_string", "literal", "literal_list", "format_datetime", "check_identifier"]

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")

# Путь к полю модели: Host.OsName, Host.@Id, @Host,
# Host.Endpoints<TransportEndpoint>.Port, WindowsHost.Softs<Software:Kaspersky:Ksc>.Plugins.
_SEGMENT = r"@?[A-Za-z_][A-Za-z0-9_]*(?:<[A-Za-z0-9_:]+>)?"
_IDENTIFIER = re.compile(rf"{_SEGMENT}(?:\.{_SEGMENT})*")

_IP_TYPES = (
    ipaddress.IPv4Address,
    ipaddress.IPv6Address,
    ipaddress.IPv4Network,
    ipaddress.IPv6Network,
)


def quote_string(value: str) -> str:
    """Записать строку как строковый литерал PDQL.

    Raises:
        ValueError: В строке есть управляющие символы или оба вида кавычек.
    """
    if _CONTROL.search(value):
        raise ValueError("Строка для PDQL содержит управляющие символы")
    has_single = "'" in value
    if has_single and '"' in value:
        raise ValueError(
            "Строка для PDQL содержит и одинарные, и двойные кавычки; "
            "такое значение нельзя безопасно подставить в запрос"
        )
    quote = '"' if has_single else "'"
    return quote + value.replace("\\", "\\\\") + quote


def format_datetime(value: datetime) -> str:
    """Записать момент времени в формате ``YYYY-MM-DDTHH:MM:SS`` (UTC).

    Время в MaxPatrol хранится в UTC. Наивный ``datetime`` считается временем UTC,
    время с часовым поясом приводится к UTC. Доли секунды отбрасываются.
    """
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc)
    return value.strftime("%Y-%m-%dT%H:%M:%S")


def literal(value: Any) -> str:
    """Записать значение Python как литерал PDQL.

    Raises:
        TypeError: Тип значения не поддерживается.
        ValueError: Значение нельзя безопасно записать в запрос.
    """
    if isinstance(value, Enum):
        value = value.value
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Число для PDQL должно быть конечным")
        return repr(value)
    if isinstance(value, str):
        return quote_string(value)
    if isinstance(value, datetime):
        return format_datetime(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, _IP_TYPES):
        return str(value)
    if isinstance(value, (list, tuple, set, frozenset)):
        return literal_list(value)
    raise TypeError(f"Значение типа {type(value).__name__} нельзя записать в PDQL")


def literal_list(values: Iterable[Any]) -> str:
    """Записать список значений как ``[a, b, c]``."""
    return "[" + ", ".join(literal(v) for v in values) + "]"


def check_identifier(path: str) -> str:
    """Проверить, что строка — путь к полю модели, а не произвольный фрагмент запроса.

    Raises:
        ValueError: Строка не похожа на путь к полю.
    """
    if not _IDENTIFIER.fullmatch(path):
        raise ValueError(f"Недопустимое имя поля PDQL: {path!r}")
    return path
