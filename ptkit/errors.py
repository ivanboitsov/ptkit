"""Исключения ptkit.

Все исключения библиотеки наследуются от :class:`PtkitError`. Сообщения
никогда не содержат токен доступа, пароль или ключ приложения.
"""

from __future__ import annotations

from typing import Optional

__all__ = [
    "PtkitError",
    "AuthError",
    "NotFoundError",
    "PDQLError",
    "TimeoutError",
    "ServerError",
    "UnsupportedVersionError",
]


class PtkitError(Exception):
    """Базовое исключение ptkit.

    Attributes:
        message: Текст ошибки (для ошибок API — сообщение сервера, если оно есть).
        status_code: HTTP-код ответа или ``None``, если ответа не было.
        path: Путь запроса без строки параметров или ``None``.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: Optional[int] = None,
        path: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.path = path

    def __str__(self) -> str:
        if self.status_code is None:
            return self.message
        return f"{self.message} (HTTP {self.status_code})"


class AuthError(PtkitError):
    """Токен неверный, отозван или истёк, либо у учётной записи нет прав (HTTP 401, 403)."""


class NotFoundError(PtkitError):
    """Объект с таким идентификатором не существует (HTTP 404)."""


class PDQLError(PtkitError):
    """MaxPatrol отклонил PDQL-запрос: синтаксис, неизвестное поле."""


class TimeoutError(PtkitError):
    """Сервер не ответил за отведённое время после всех повторов."""


class ServerError(PtkitError):
    """Ошибка на стороне MaxPatrol (HTTP 5xx) после всех повторов."""


class UnsupportedVersionError(PtkitError):
    """Функция недоступна в версии MaxPatrol на сервере."""
