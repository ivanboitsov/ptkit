"""Поля модели и условия отбора для построителя PDQL.

Условия строятся операторами Python и объединяются через ``&`` (и), ``|`` (или),
``~`` (не)::

    (Host.os_name.contains("Windows") & (Host.importance == "high")).to_pdql()
    # "Host.OsName like '%Windows%' and Host.@Importance = 'H'"

Значения всегда экранируются (см. :mod:`ptkit.pdql.escape`).
"""

from __future__ import annotations

import ipaddress
import uuid
from datetime import date, datetime
from typing import Any, Iterable, List, Mapping, Optional, Tuple, Union

from .escape import check_identifier, literal, literal_list, quote_string

__all__ = [
    "Field",
    "Condition",
    "Comparison",
    "And",
    "Or",
    "Not",
    "STRING",
    "LIST",
    "UUID",
    "DATETIME",
    "IP",
    "NUMBER",
    "ANY",
]

# Виды полей: от вида зависит, как приводится значение и что значит contains().
STRING = "string"
LIST = "list"
UUID = "uuid"
DATETIME = "datetime"
IP = "ip"
NUMBER = "number"
ANY = "any"
_KINDS = frozenset({STRING, LIST, UUID, DATETIME, IP, NUMBER, ANY})

_Network = Union[ipaddress.IPv4Network, ipaddress.IPv6Network]
_NETWORK_TYPES = (ipaddress.IPv4Network, ipaddress.IPv6Network)


class Condition:
    """Условие отбора. Объединяется через ``&``, ``|``, ``~``."""

    def to_pdql(self) -> str:
        raise NotImplementedError

    def __and__(self, other: Condition) -> Condition:
        return And(self, _check_condition(other))

    def __or__(self, other: Condition) -> Condition:
        return Or(self, _check_condition(other))

    def __invert__(self) -> Condition:
        return Not(self)

    def __bool__(self) -> bool:
        raise TypeError(
            "Условие PDQL нельзя использовать как bool: объединяйте условия через &, | и ~, "
            "а не and, or и not"
        )

    def __str__(self) -> str:
        return self.to_pdql()

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.to_pdql()}>"


class Comparison(Condition):
    """Предикат вида ``<поле> <оператор> <значение>``."""

    __slots__ = ("field", "operator", "value")

    def __init__(self, field: Field, operator: str, value: str) -> None:
        self.field = field
        self.operator = operator
        self.value = value  # уже записанный литерал PDQL

    def to_pdql(self) -> str:
        return f"{self.field.pdql} {self.operator} {self.value}"


class _Junction(Condition):
    operator = ""

    def __init__(self, *parts: Condition) -> None:
        flat: List[Condition] = []
        for part in parts:
            if isinstance(part, _Junction) and type(part) is type(self):
                flat.extend(part.parts)
            else:
                flat.append(part)
        self.parts: Tuple[Condition, ...] = tuple(flat)

    def to_pdql(self) -> str:
        return f" {self.operator} ".join(_wrap(p) for p in self.parts)


class And(_Junction):
    operator = "and"


class Or(_Junction):
    operator = "or"


class Not(Condition):
    def __init__(self, part: Condition) -> None:
        self.part = part

    def to_pdql(self) -> str:
        return f"not ({self.part.to_pdql()})"


def _wrap(part: Condition) -> str:
    text = part.to_pdql()
    return f"({text})" if isinstance(part, _Junction) else text


def _check_condition(value: Any) -> Condition:
    if not isinstance(value, Condition):
        raise TypeError(f"Ожидалось условие PDQL, получено {type(value).__name__}")
    return value


class Field:
    """Поле модели в PDQL, например ``Host.OsName``.

    Args:
        pdql: Путь к полю в PDQL. Проверяется: произвольный фрагмент запроса
            передать нельзя.
        name: Имя атрибута в объектах ответа (``os_name``).
        kind: Вид поля; определяет приведение значений и смысл ``contains``.
        item: Вид элементов для поля-списка (``kind=LIST``).
        values: Синонимы значений, например ``{"high": "H"}``.
    """

    __slots__ = ("pdql", "name", "kind", "item", "values")

    def __init__(
        self,
        pdql: str,
        name: Optional[str] = None,
        *,
        kind: str = ANY,
        item: str = ANY,
        values: Optional[Mapping[str, str]] = None,
    ) -> None:
        if kind not in _KINDS or item not in _KINDS or item == LIST:
            raise ValueError(f"Неизвестный вид поля: {kind!r}/{item!r}")
        self.pdql = check_identifier(pdql)
        self.name = name
        self.kind = kind
        self.item = item
        self.values = dict(values or {})

    # Сравнения возвращают условие, а не bool, поэтому хэш задан явно.
    __hash__ = object.__hash__

    def __eq__(self, other: Any) -> Comparison:  # type: ignore[override]
        return Comparison(self, "=", self._literal(other))

    def __ne__(self, other: Any) -> Comparison:  # type: ignore[override]
        return Comparison(self, "!=", self._literal(other))

    def __lt__(self, other: Any) -> Comparison:
        return Comparison(self, "<", self._literal(other))

    def __le__(self, other: Any) -> Comparison:
        return Comparison(self, "<=", self._literal(other))

    def __gt__(self, other: Any) -> Comparison:
        return Comparison(self, ">", self._literal(other))

    def __ge__(self, other: Any) -> Comparison:
        return Comparison(self, ">=", self._literal(other))

    def contains(self, value: Any) -> Comparison:
        """Для списка — содержит элемент (``CONTAINS``), для строки — подстроку (``LIKE``).

        В строковом режиме знаки ``%`` и ``_`` внутри ``value`` работают как шаблон
        ``LIKE``: экранирование для них в PDQL не описано. Сравнение ``LIKE``
        в MaxPatrol регистронезависимое.
        """
        if self.kind == LIST:
            return Comparison(self, "contains", self._literal(value))
        return Comparison(self, "like", quote_string(f"%{self._text(value)}%"))

    def startswith(self, prefix: str) -> Comparison:
        """Строка начинается с ``prefix`` (``LIKE 'prefix%'``)."""
        return Comparison(self, "like", quote_string(f"{self._text(prefix)}%"))

    def like(self, pattern: str) -> Comparison:
        """Шаблон ``LIKE``: ``%`` — любое число символов, ``_`` — один символ."""
        return Comparison(self, "like", quote_string(self._text(pattern)))

    def match(self, regex: str) -> Comparison:
        """Регулярное выражение (``MATCH``)."""
        return Comparison(self, "match", quote_string(self._text(regex)))

    def in_(self, values: Union[Iterable[Any], str, _Network]) -> Comparison:
        """Значение входит в список или, для IP-поля, в подсеть (``"10.0.0.0/8"``)."""
        if self.kind == IP and isinstance(values, (str, *_NETWORK_TYPES)):
            network = ipaddress.ip_network(values, strict=False)
            return Comparison(self, "in", str(network))
        if isinstance(values, (str, bytes)):
            raise TypeError("in_() ожидает список значений, а не строку")
        return Comparison(self, "in", literal_list(self._value(v) for v in values))

    def _text(self, value: Any) -> str:
        if not isinstance(value, str):
            raise TypeError(f"Ожидалась строка, получено {type(value).__name__}")
        return value

    def _literal(self, value: Any) -> str:
        return literal(self._value(value))

    def _value(self, value: Any) -> Any:
        """Привести значение к типу, который соответствует виду поля (элемента списка)."""
        if isinstance(value, Field):
            raise TypeError("Сравнение двух полей построитель не поддерживает")
        if value is None:
            return None
        if isinstance(value, str) and value in self.values:
            return self.values[value]
        kind = self.item if self.kind == LIST else self.kind
        if isinstance(value, str):
            if kind == UUID:
                return uuid.UUID(value)
            if kind == IP:
                return ipaddress.ip_address(value)
            if kind == DATETIME:
                return datetime.fromisoformat(value)
        if kind == DATETIME and not isinstance(value, (datetime, date)):
            raise TypeError(f"Поле {self.pdql} ожидает datetime, получено {type(value).__name__}")
        return value

    def __repr__(self) -> str:
        return f"Field({self.pdql!r})"

    def __str__(self) -> str:
        return self.pdql
