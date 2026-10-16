"""HTTP-транспорт: сессия, авторизация, повторы, сертификаты, разбор ошибок.

Модуль не знает про конкретный продукт: адреса и параметры авторизации
передаёт модуль продукта (например, ``ptkit.vm``).

Токен, пароль и ключ приложения не попадают в журнал, исключения и ``repr``.
Исключения ``requests`` не присоединяются как причина (``raise ... from None``):
их объект запроса содержит заголовок ``Authorization``.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any, Callable, Dict, Mapping, Optional, Type, Union
from urllib.parse import urlsplit

import requests

from ._version import __version__
from .errors import (
    AuthError,
    NotFoundError,
    PtkitError,
    ServerError,
)
from .errors import TimeoutError as PtkitTimeoutError

log = logging.getLogger("ptkit")

Verify = Union[bool, str]
ErrorMap = Mapping[int, Type[PtkitError]]

# Ключи JSON, в которых сервисы PT обычно возвращают текст ошибки.
_MESSAGE_KEYS = ("message", "error_description", "detail", "title", "error")
_MAX_MESSAGE = 500


class Auth:
    """Источник заголовка ``Authorization``."""

    def authorization(self, http: HTTPTransport) -> str:
        raise NotImplementedError

    def invalidate(self) -> bool:
        """Сбросить текущий токен после ответа 401.

        Returns:
            ``True``, если можно получить новый токен и повторить запрос.
        """
        return False


class TokenAuth(Auth):
    """Готовый токен доступа типа Bearer."""

    __slots__ = ("_token",)

    def __init__(self, token: str) -> None:
        token = token.strip()
        if not token:
            raise ValueError("Токен доступа пустой")
        self._token = token

    def authorization(self, http: HTTPTransport) -> str:
        return f"Bearer {self._token}"

    def __repr__(self) -> str:
        return "TokenAuth(token='***')"


class PasswordAuth(Auth):
    """Токен по учётным данным: OAuth 2.0, ``grant_type=password``.

    Токен запрашивается при первом обращении и запрашивается заново, когда
    срок действия подходит к концу или сервер ответил 401.
    """

    def __init__(
        self,
        token_url: str,
        *,
        username: str,
        password: str,
        client_secret: str,
        client_id: str,
        scope: str,
        response_type: str,
        refresh_margin: float = 60.0,
    ) -> None:
        if not username or not password:
            raise ValueError("Не указаны логин или пароль")
        if not client_secret:
            raise ValueError("Не указан client_secret приложения")
        self.token_url = token_url
        self.username = username
        self._password = password
        self._client_secret = client_secret
        self._client_id = client_id
        self._scope = scope
        self._response_type = response_type
        self._refresh_margin = refresh_margin
        self._token: Optional[str] = None
        self._expires_at = 0.0

    def authorization(self, http: HTTPTransport) -> str:
        if self._token is None or time.monotonic() >= self._expires_at:
            self._login(http)
        return f"Bearer {self._token}"

    def invalidate(self) -> bool:
        self._token = None
        return True

    def _login(self, http: HTTPTransport) -> None:
        log.debug("Запрос токена доступа для %s", self.username)
        data = http.request_json(
            "POST",
            self.token_url,
            data={
                "grant_type": "password",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "scope": self._scope,
                "response_type": self._response_type,
                "username": self.username,
                "password": self._password,
            },
            authenticate=False,
            # Неверный логин, пароль или client_secret: 400 invalid_grant / invalid_client.
            error_map={400: AuthError},
        )
        token = data.get("access_token") if isinstance(data, dict) else None
        if not isinstance(token, str) or not token:
            raise AuthError("Сервер авторизации не вернул access_token")
        expires_in = data.get("expires_in")
        lifetime = float(expires_in) if isinstance(expires_in, (int, float)) else 3600.0
        self._token = token
        self._expires_at = time.monotonic() + max(lifetime - self._refresh_margin, 0.0)

    def __repr__(self) -> str:
        return f"PasswordAuth(username={self.username!r}, password='***', client_secret='***')"


class HTTPTransport:
    """Сессия ``requests`` с авторизацией, повторами и разбором ошибок.

    Объект не потокобезопасен: используйте отдельный клиент в каждом потоке.
    """

    def __init__(
        self,
        base_url: str,
        auth: Auth,
        *,
        verify: Verify = True,
        timeout: float = 30.0,
        retries: int = 3,
        backoff: float = 1.0,
    ) -> None:
        if retries < 0:
            raise ValueError("retries не может быть отрицательным")
        if timeout <= 0:
            raise ValueError("timeout должен быть положительным")
        if backoff < 0:
            raise ValueError("backoff не может быть отрицательным")
        self.base_url = base_url.rstrip("/")
        self.auth = auth
        self.timeout = timeout
        self.retries = retries
        self.backoff = backoff
        self.session = requests.Session()
        self.session.verify = verify
        self.session.headers["User-Agent"] = f"ptkit/{__version__}"
        self.session.headers["Accept"] = "application/json"
        # Подменяется в тестах, чтобы не ждать паузы между повторами.
        self._sleep: Callable[[float], None] = time.sleep

    def close(self) -> None:
        self.session.close()

    def request(
        self,
        method: str,
        url: str,
        *,
        params: Optional[Mapping[str, Any]] = None,
        json: Any = None,
        data: Optional[Mapping[str, Any]] = None,
        authenticate: bool = True,
        error_map: Optional[ErrorMap] = None,
    ) -> requests.Response:
        """Выполнить запрос и вернуть успешный ответ (2xx/3xx).

        Args:
            url: Абсолютный адрес или путь относительно ``base_url``.
            error_map: Переопределение типа исключения для HTTP-кодов.

        Raises:
            PtkitError: Или наследник, по коду ответа.
        """
        if not url.startswith(("https://", "http://")):
            url = self.base_url + url
        path = urlsplit(url).path
        attempt = 0
        reauthenticated = False
        while True:
            headers: Dict[str, str] = {}
            if authenticate:
                headers["Authorization"] = self.auth.authorization(self)
            started = time.monotonic()
            try:
                response = self.session.request(
                    method,
                    url,
                    params=params,
                    json=json,
                    data=data,
                    headers=headers,
                    timeout=self.timeout,
                )
            except requests.Timeout:
                if attempt < self.retries:
                    self._pause(attempt, f"{method} {path}: нет ответа за {self.timeout} с")
                    attempt += 1
                    continue
                raise PtkitTimeoutError(
                    f"Сервер не ответил за {self.timeout} с после {attempt + 1} попыток",
                    path=path,
                ) from None
            except requests.exceptions.SSLError as exc:
                raise PtkitError(
                    "Ошибка проверки TLS-сертификата: "
                    f"{_redact(str(exc))}. Укажите в verify путь к корневому сертификату "
                    "организации",
                    path=path,
                ) from None
            except requests.ConnectionError as exc:
                if attempt < self.retries:
                    self._pause(attempt, f"{method} {path}: ошибка соединения")
                    attempt += 1
                    continue
                raise PtkitError(
                    f"Не удалось подключиться к {urlsplit(url).netloc}: {_redact(str(exc))}",
                    path=path,
                ) from None
            except requests.RequestException as exc:
                raise PtkitError(f"Ошибка HTTP-запроса: {type(exc).__name__}", path=path) from None

            log.debug(
                "%s %s -> %s, %.0f мс, %d байт",
                method,
                path,
                response.status_code,
                (time.monotonic() - started) * 1000,
                len(response.content),
            )
            status = response.status_code
            if status >= 500 and attempt < self.retries:
                self._pause(attempt, f"{method} {path}: HTTP {status}")
                attempt += 1
                continue
            if status == 401 and authenticate and not reauthenticated and self.auth.invalidate():
                reauthenticated = True
                continue
            if status >= 400:
                raise _error_from_response(response, path, error_map)
            return response

    def request_json(self, method: str, url: str, **kwargs: Any) -> Any:
        """Как :meth:`request`, но возвращает разобранный JSON."""
        response = self.request(method, url, **kwargs)
        if not response.content:
            return None
        try:
            return response.json()
        except ValueError:
            raise PtkitError(
                "Сервер вернул ответ не в формате JSON",
                status_code=response.status_code,
                path=urlsplit(response.url).path,
            ) from None

    def _pause(self, attempt: int, reason: str) -> None:
        delay = self.backoff * (2**attempt)
        log.info("%s; повтор %d из %d через %.1f с", reason, attempt + 1, self.retries, delay)
        self._sleep(delay)


def _error_from_response(
    response: requests.Response,
    path: str,
    error_map: Optional[ErrorMap],
) -> PtkitError:
    status = response.status_code
    message = _extract_message(response) or response.reason or "Ошибка API"
    cls: Type[PtkitError]
    if error_map and status in error_map:
        cls = error_map[status]
    elif status in (401, 403):
        cls = AuthError
    elif status == 404:
        cls = NotFoundError
    elif status >= 500:
        cls = ServerError
    else:
        cls = PtkitError
    return cls(message, status_code=status, path=path)


def _extract_message(response: requests.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return _truncate(response.text.strip())
    if isinstance(payload, dict):
        for key in _MESSAGE_KEYS:
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return _truncate(value.strip())
        errors = payload.get("errors")
        if errors:
            return _truncate(_flatten_errors(errors))
    if isinstance(payload, str):
        return _truncate(payload.strip())
    return ""


def _flatten_errors(errors: Any) -> str:
    """Собрать текст из поля ``errors`` (список или словарь «поле -> сообщения»)."""
    if isinstance(errors, dict):
        parts = []
        for key, value in errors.items():
            text = "; ".join(map(str, value)) if isinstance(value, list) else str(value)
            parts.append(f"{key}: {text}")
        return "; ".join(parts)
    if isinstance(errors, list):
        parts = []
        for item in errors:
            if isinstance(item, dict):
                text = next(
                    (str(item[k]) for k in ("message", "description", "type") if item.get(k)),
                    str(item),
                )
                parts.append(text)
            else:
                parts.append(str(item))
        return "; ".join(parts)
    return str(errors)


def _truncate(text: str) -> str:
    return text if len(text) <= _MAX_MESSAGE else text[: _MAX_MESSAGE - 1] + "…"


_QUERY_STRING = re.compile(r"\?[^\s)'\"]*")


def _redact(text: str) -> str:
    """Убрать строки параметров из адресов в тексте ошибки urllib3."""
    return _QUERY_STRING.sub("", text)
