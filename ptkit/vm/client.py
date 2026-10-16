"""Клиент MaxPatrol VM — единственная точка входа в API."""

from __future__ import annotations

import logging
import os
import stat
import sys
from types import TracebackType
from typing import Any, Dict, Iterator, Mapping, Optional, Sequence, Type, Union
from urllib.parse import urlsplit, urlunsplit

from .. import _toml
from .._http import Auth, HTTPTransport, PasswordAuth, TokenAuth, Verify
from .._version import __version__
from ..errors import AuthError, PDQLError, PtkitError
from ..pdql.builder import Query
from . import _compat
from .assets import Assets
from .groups import Groups
from .tasks import Tasks

__all__ = ["Client"]

log = logging.getLogger("ptkit")

_ENV_URL = "PTKIT_URL"
_ENV_TOKEN = "PTKIT_TOKEN"
_ENV_USERNAME = "PTKIT_USERNAME"
_ENV_PASSWORD = "PTKIT_PASSWORD"
_ENV_CLIENT_SECRET = "PTKIT_CLIENT_SECRET"

_CONFIG_KEYS = {
    "url": "base_url",
    "token": "token",
    "username": "username",
    "password": "password",
    "client_secret": "client_secret",
    "auth_url": "auth_url",
    "verify": "verify",
    "timeout": "timeout",
    "retries": "retries",
    "backoff": "backoff",
}
_SECRET_KEYS = ("token", "password", "client_secret")

# Ошибки 400 при работе с PDQL означают, что сервер отклонил запрос.
_PDQL_ERRORS = {400: PDQLError}


class Client:
    """Подключение к MaxPatrol VM.

    Конструктор только проверяет параметры: запросы к серверу уходят при первом
    обращении к данным.

    Способы авторизации (по приоритету):

    1. ``token`` — токен доступа (Bearer), выпущенный в интерфейсе PT MC. Срок
       действия задаёт администратор; клиент токен не обновляет.
    2. ``username`` + ``password`` + ``client_secret`` — клиент сам получает
       токен в PT MC (``<адрес>:3334/connect/token``) и запрашивает новый, когда
       срок действия истекает.
    3. Переменные окружения ``PTKIT_TOKEN`` или ``PTKIT_USERNAME``,
       ``PTKIT_PASSWORD``, ``PTKIT_CLIENT_SECRET``.

    Args:
        base_url: Адрес MaxPatrol Core, например ``https://mp.example.local``.
            По умолчанию — переменная окружения ``PTKIT_URL``.
        token: Токен доступа.
        username: Логин учётной записи MaxPatrol (лучше — сервисной, только на чтение).
        password: Пароль учётной записи.
        client_secret: Ключ приложения ``mpx`` (``ClientSecret`` в
            ``/var/lib/deployer/role_instances/core*/params.yaml``).
        auth_url: Адрес сервера авторизации; по умолчанию тот же хост, порт 3334.
        verify: Проверка сертификата; строка — путь к корневому сертификату организации.
        timeout: Таймаут одного HTTP-запроса, секунды.
        retries: Число повторов при сетевой ошибке и ответах 5xx.
        backoff: Начальная пауза между повторами, удваивается с каждой попыткой.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        token: Optional[str] = None,
        *,
        username: Optional[str] = None,
        password: Optional[str] = None,
        client_secret: Optional[str] = None,
        auth_url: Optional[str] = None,
        verify: Verify = True,
        timeout: float = 30.0,
        retries: int = 3,
        backoff: float = 1.0,
    ) -> None:
        url = base_url or os.environ.get(_ENV_URL)
        if not url:
            raise ValueError(
                f"Не указан адрес MaxPatrol: передайте base_url или задайте {_ENV_URL}"
            )
        self.base_url = _normalize_url(url)
        auth = _make_auth(self.base_url, token, username, password, client_secret, auth_url)
        self._http = HTTPTransport(
            self.base_url, auth, verify=verify, timeout=timeout, retries=retries, backoff=backoff
        )
        if verify is False:
            log.warning(
                "Проверка TLS-сертификата MaxPatrol отключена (verify=False). "
                "Не используйте это в рабочих системах: укажите путь к корневому сертификату"
            )
        self._version: Optional[str] = None
        self._version_checked = False
        self.assets = Assets(self)
        self.groups = Groups(self)
        self.tasks = Tasks(self)

    # --- Создание из окружения и файла ---------------------------------------

    @classmethod
    def from_env(cls, **kwargs: Any) -> Client:
        """Клиент с адресом и учётными данными из переменных окружения.

        Адрес — ``PTKIT_URL``; токен — ``PTKIT_TOKEN`` или учётные данные
        ``PTKIT_USERNAME``, ``PTKIT_PASSWORD``, ``PTKIT_CLIENT_SECRET``.
        Остальные параметры (``verify``, ``timeout``…) передаются как аргументы.
        """
        for name in ("base_url", "token", "username", "password", "client_secret"):
            if name in kwargs:
                raise TypeError(f"from_env() берёт {name} из окружения; используйте Client()")
        if not os.environ.get(_ENV_URL):
            raise ValueError(f"Переменная окружения {_ENV_URL} не задана")
        return cls(**kwargs)

    @classmethod
    def from_config(cls, path: Union[str, os.PathLike[str]], **overrides: Any) -> Client:
        """Клиент с настройками из TOML-файла.

        Ключи файла: ``url``, ``token`` или ``username``/``password``/``client_secret``,
        ``auth_url``, ``verify``, ``timeout``, ``retries``, ``backoff``.
        Аргументы ``overrides`` имеют приоритет над файлом.
        """
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        try:
            config = _toml.loads(text)
        except ValueError as exc:
            raise ValueError(f"Ошибка в файле настроек {os.fspath(path)}: {exc}") from None
        unknown = sorted(set(config) - set(_CONFIG_KEYS))
        if unknown:
            raise ValueError(f"Неизвестные ключи в {os.fspath(path)}: {', '.join(unknown)}")
        if any(key in config for key in _SECRET_KEYS):
            _warn_if_readable_by_others(path)
        kwargs: Dict[str, Any] = {_CONFIG_KEYS[k]: v for k, v in config.items()}
        kwargs.update(overrides)
        return cls(**kwargs)

    # --- Публичные методы ----------------------------------------------------

    def version(self) -> str:
        """Версия MaxPatrol на сервере (``productVersion``, версия ядра MaxPatrol 10).

        Значение запрашивается один раз и кэшируется.
        """
        if self._version is None:
            self._version_checked = True
            data = self._http.request_json("GET", _compat.SYSTEM_INFO)
            version = _compat.product_version(data)
            if not version:
                raise PtkitError("Сервер не сообщил версию MaxPatrol")
            self._version = version
            self._warn_if_untested(version)
        return self._version

    def pdql(
        self,
        query: Union[str, Query],
        group_id: Optional[str] = None,
        *,
        page_size: int = _compat.PDQL_PAGE_SIZE,
    ) -> Iterator[Dict[str, Any]]:
        """Выполнить PDQL-запрос и вернуть строки как словари.

        Возвращает ленивый итератор: запрос уходит на сервер, когда запрошена
        первая строка; строки читаются страницами по ``page_size``.

        Args:
            query: Строка PDQL или построитель.
            group_id: Ограничить запрос группой активов (вложенные группы входят).
            page_size: Сколько строк запрашивать за один HTTP-запрос.

        Raises:
            PDQLError: MaxPatrol отклонил запрос.
        """
        text = query.to_pdql() if isinstance(query, Query) else query
        if not isinstance(text, str) or not text.strip():
            raise ValueError("PDQL-запрос пустой")
        groups = (group_id,) if group_id else ()
        return self._pdql_rows(text, group_ids=groups, page_size=page_size)

    def close(self) -> None:
        """Закрыть HTTP-соединения."""
        self._http.close()

    def __enter__(self) -> Client:
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"Client(base_url={self.base_url!r}, auth={self._http.auth!r})"

    # --- Внутреннее: используется ресурсами ----------------------------------

    def _get_json(self, path: str, *, params: Optional[Mapping[str, Any]] = None) -> Any:
        self._check_version_once()
        return self._http.request_json("GET", path, params=params)

    def _pdql_rows(
        self,
        pdql: str,
        *,
        group_ids: Sequence[str] = (),
        asset_ids: Sequence[str] = (),
        page_size: int = _compat.PDQL_PAGE_SIZE,
    ) -> Iterator[Dict[str, Any]]:
        """Проверить параметры сразу и вернуть ленивый итератор строк."""
        if page_size <= 0:
            raise ValueError("page_size должен быть положительным")
        return self._iter_pdql(pdql, group_ids, asset_ids, page_size)

    def _iter_pdql(
        self,
        pdql: str,
        group_ids: Sequence[str],
        asset_ids: Sequence[str],
        page_size: int,
    ) -> Iterator[Dict[str, Any]]:
        self._check_version_once()
        log.debug("PDQL: %s", pdql)
        created = self._http.request_json(
            "POST",
            _compat.PDQL_CREATE,
            json=_compat.pdql_request(pdql, group_ids, asset_ids),
            error_map=_PDQL_ERRORS,
        )
        token = _compat.pdql_token(created)
        if token is None:
            raise PDQLError("MaxPatrol не вернул токен PDQL-запроса")
        offset = 0
        while True:
            data = self._http.request_json(
                "GET",
                _compat.PDQL_DATA,
                params=_compat.pdql_data_params(token, offset, page_size),
                error_map=_PDQL_ERRORS,
            )
            records = _compat.pdql_records(data)
            yield from records
            if len(records) < page_size:
                return
            offset += len(records)

    def _check_version_once(self) -> None:
        """При первом обращении узнать версию сервера и предупредить, если она не проверялась."""
        if self._version_checked:
            return
        self._version_checked = True
        try:
            self.version()
        except AuthError:
            # Основной запрос тоже не пройдёт; повторная попытка входа с неверным
            # паролем только приблизит блокировку учётной записи.
            raise
        except PtkitError as exc:
            log.debug("Не удалось узнать версию MaxPatrol: %s", exc)

    @staticmethod
    def _warn_if_untested(version: str) -> None:
        if not _compat.is_tested(version):
            log.warning(
                "Версия MaxPatrol %s не проверялась с ptkit %s; работа продолжится. "
                "Если всё работает, сообщите об этом в issue",
                version,
                __version__,
            )


def _normalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    if parts.scheme not in ("https", "http") or not parts.hostname:
        raise ValueError(
            f"Адрес MaxPatrol должен быть вида https://mp.example.local, получено {url!r}"
        )
    if parts.query or parts.fragment:
        raise ValueError("Адрес MaxPatrol не должен содержать параметры запроса")
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))


def _default_auth_url(base_url: str) -> str:
    parts = urlsplit(base_url)
    host = parts.hostname or ""
    if ":" in host:  # IPv6
        host = f"[{host}]"
    return urlunsplit((parts.scheme, f"{host}:{_compat.AUTH_PORT}", "", "", ""))


def _make_auth(
    base_url: str,
    token: Optional[str],
    username: Optional[str],
    password: Optional[str],
    client_secret: Optional[str],
    auth_url: Optional[str],
) -> Auth:
    if token and (username or password):
        raise ValueError("Укажите либо token, либо username и password, но не всё сразу")
    if token:
        return TokenAuth(token)
    if username or password:
        return _password_auth(base_url, username, password, client_secret, auth_url)
    env_token = os.environ.get(_ENV_TOKEN)
    if env_token:
        return TokenAuth(env_token)
    env_user, env_password = os.environ.get(_ENV_USERNAME), os.environ.get(_ENV_PASSWORD)
    if env_user or env_password:
        return _password_auth(base_url, env_user, env_password, client_secret, auth_url)
    raise ValueError(
        "Не указаны учётные данные: передайте token или username/password/client_secret, "
        f"либо задайте {_ENV_TOKEN}"
    )


def _password_auth(
    base_url: str,
    username: Optional[str],
    password: Optional[str],
    client_secret: Optional[str],
    auth_url: Optional[str],
) -> PasswordAuth:
    secret = client_secret or os.environ.get(_ENV_CLIENT_SECRET)
    if not secret:
        raise ValueError(
            f"Для входа по логину и паролю нужен client_secret (или {_ENV_CLIENT_SECRET})"
        )
    root = _normalize_url(auth_url) if auth_url else _default_auth_url(base_url)
    return PasswordAuth(
        root + _compat.AUTH_TOKEN_PATH,
        username=username or "",
        password=password or "",
        client_secret=secret,
        client_id=_compat.AUTH_CLIENT_ID,
        scope=_compat.AUTH_SCOPE,
        response_type=_compat.AUTH_RESPONSE_TYPE,
    )


def _warn_if_readable_by_others(path: Union[str, os.PathLike[str]]) -> None:
    if sys.platform == "win32":
        return
    try:
        mode = os.stat(path).st_mode
    except OSError:
        return
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        log.warning(
            "Файл %s с учётными данными доступен не только владельцу; выполните chmod 600",
            os.fspath(path),
        )
