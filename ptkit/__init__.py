"""ptkit — неофициальная Python-библиотека для API продуктов Positive Technologies.

Точка входа для MaxPatrol VM — :class:`ptkit.vm.Client`.
"""

import logging

from ._version import __version__
from .errors import (
    AuthError,
    NotFoundError,
    PDQLError,
    PtkitError,
    ServerError,
    TimeoutError,
    UnsupportedVersionError,
)

# Библиотека не настраивает журналирование: это решает приложение.
logging.getLogger("ptkit").addHandler(logging.NullHandler())

__all__ = [
    "__version__",
    "PtkitError",
    "AuthError",
    "NotFoundError",
    "PDQLError",
    "TimeoutError",
    "ServerError",
    "UnsupportedVersionError",
]
