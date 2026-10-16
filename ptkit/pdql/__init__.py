"""PDQL: поля, условия, построитель запросов и экранирование значений.

Модуль не зависит от продукта: поля конкретной модели (например, ``Host``)
описаны в модуле продукта.
"""

from .builder import Query
from .escape import literal, quote_string
from .fields import And, Comparison, Condition, Field, Not, Or

__all__ = [
    "Query",
    "Field",
    "Condition",
    "Comparison",
    "And",
    "Or",
    "Not",
    "literal",
    "quote_string",
]
