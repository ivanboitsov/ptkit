"""Построитель PDQL-запросов.

Построитель собирает конвейер ``filter(...) | select(...) | sort(...) | limit(N)``.
Отбор идёт до выбора колонок: так фильтр работает по всем полям модели, включая
псевдонимы, которые доступны только до ``select`` (например, ``@IpAddresses.Item``).

Объект неизменяемый: каждый метод возвращает новый запрос, поэтому общую часть
можно сохранить и достраивать по-разному.

Построитель покрывает основные конструкции PDQL, а не весь язык. Для остального
используйте сырой запрос — это штатный путь.
"""

from __future__ import annotations

import copy
from typing import Optional, Tuple, TypeVar, Union

from .fields import Condition, Field

__all__ = ["Query"]

Q = TypeVar("Q", bound="Query")
FieldLike = Union[Field, str]


class Query:
    """Построитель PDQL без привязки к продукту и серверу."""

    #: Колонки, которые всегда идут первыми в ``select`` (например, ``@Host``).
    base_select: Tuple[str, ...] = ()

    def __init__(self) -> None:
        self._select: Tuple[Field, ...] = ()
        self._filter: Optional[Condition] = None
        self._sort: Tuple[Tuple[Field, bool], ...] = ()
        self._limit: Optional[int] = None

    def select(self: Q, *fields: FieldLike) -> Q:
        """Какие поля вернуть. Повторный вызов добавляет поля."""
        if not fields:
            raise ValueError("select() ожидает хотя бы одно поле")
        query = self._copy()
        query._select = self._select + tuple(_as_field(f) for f in fields)
        return query

    def filter(self: Q, condition: Condition) -> Q:
        """Условие отбора. Несколько вызовов объединяются через «и»."""
        if not isinstance(condition, Condition):
            raise TypeError(
                f"filter() ожидает условие PDQL, получено {type(condition).__name__}"
            )
        query = self._copy()
        query._filter = condition if self._filter is None else self._filter & condition
        return query

    def sort(self: Q, field: FieldLike, desc: bool = False) -> Q:
        """Сортировка. Повторный вызов добавляет следующий ключ сортировки.

        Поле сортировки, которого нет среди выбранных, добавляется в ``select``:
        сортировка применяется к результату выбора колонок.
        """
        query = self._copy()
        query._sort = self._sort + ((_as_field(field), bool(desc)),)
        return query

    def limit(self: Q, n: int) -> Q:
        """Ограничение числа строк."""
        if isinstance(n, bool) or not isinstance(n, int) or n < 0:
            raise ValueError("limit() ожидает неотрицательное целое число")
        query = self._copy()
        query._limit = n
        return query

    def to_pdql(self) -> str:
        """Итоговая строка PDQL без выполнения."""
        parts = []
        if self._filter is not None:
            parts.append(f"filter({self._filter.to_pdql()})")
        columns = self._columns()
        if columns:
            parts.append(f"select({', '.join(columns)})")
        if self._sort:
            keys = ", ".join(f"{f.pdql} {'DESC' if desc else 'ASC'}" for f, desc in self._sort)
            parts.append(f"sort({keys})")
        if self._limit is not None:
            parts.append(f"limit({self._limit})")
        return " | ".join(parts)

    def _selected_fields(self) -> Tuple[Field, ...]:
        """Поля для ``select``; наследники могут подставлять поля по умолчанию."""
        return self._select

    def _columns(self) -> Tuple[str, ...]:
        columns = list(self.base_select)
        seen = {c.lower() for c in columns}
        fields = self._selected_fields() + tuple(f for f, _ in self._sort)
        for field in fields:
            key = field.pdql.lower()
            if key not in seen:
                seen.add(key)
                columns.append(field.pdql)
        return tuple(columns)

    def _copy(self: Q) -> Q:
        return copy.copy(self)

    def __str__(self) -> str:
        return self.to_pdql()

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.to_pdql()!r}>"


def _as_field(value: FieldLike) -> Field:
    if isinstance(value, Field):
        return value
    if isinstance(value, str):
        return Field(value)
    raise TypeError(f"Ожидалось поле PDQL, получено {type(value).__name__}")
