"""Общие фикстуры unit-тестов: поддельный HTTP-адаптер и клиент без сети."""

from __future__ import annotations

import json
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Tuple, Union
from urllib.parse import parse_qs, urlsplit

import pytest
import requests
from requests.adapters import BaseAdapter

from ptkit.vm import Client

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "2.7"
TOKEN = "test-access-token-1f2e3d"
BASE_URL = "https://mp.example.local"


def load(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


Reply = Union["FakeResponse", BaseException]


class FakeResponse:
    def __init__(
        self,
        status: int = 200,
        json_body: Any = None,
        text: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> None:
        self.status = status
        self.json_body = json_body
        self.text = text
        self.headers = headers or {}


class Call:
    def __init__(self, request: requests.PreparedRequest) -> None:
        parts = urlsplit(request.url or "")
        self.method = request.method
        self.url = request.url
        self.netloc = parts.netloc
        self.path = parts.path
        self.params = {k: v[0] for k, v in parse_qs(parts.query).items()}
        self.headers = dict(request.headers)
        body = request.body
        self.body: Any = body.decode() if isinstance(body, bytes) else body

    def json(self) -> Any:
        return json.loads(self.body)

    def form(self) -> Dict[str, str]:
        return {k: v[0] for k, v in parse_qs(self.body).items()}


class FakeAdapter(BaseAdapter):
    """Отвечает заранее заданными ответами по (метод, путь) и записывает запросы.

    Если для маршрута задано несколько ответов, они выдаются по очереди,
    последний повторяется.
    """

    def __init__(self) -> None:
        super().__init__()
        self.routes: Dict[Tuple[str, str], Deque[Reply]] = defaultdict(deque)
        self.calls: List[Call] = []

    def add(
        self,
        method: str,
        path: str,
        json: Any = None,
        status: int = 200,
        text: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> None:
        self.routes[(method, path)].append(FakeResponse(status, json, text, headers))

    def add_error(self, method: str, path: str, exc: BaseException) -> None:
        self.routes[(method, path)].append(exc)

    def calls_to(self, path: str) -> List[Call]:
        return [c for c in self.calls if c.path == path]

    def send(self, request: requests.PreparedRequest, **kwargs: Any) -> requests.Response:
        call = Call(request)
        self.calls.append(call)
        queue = self.routes.get((call.method or "", call.path))
        if not queue:
            raise AssertionError(f"Неожиданный запрос: {call.method} {call.path}")
        reply = queue.popleft() if len(queue) > 1 else queue[0]
        if isinstance(reply, BaseException):
            raise reply
        response = requests.Response()
        response.status_code = reply.status
        response.url = request.url or ""
        response.request = request
        response.reason = {200: "OK", 400: "Bad Request", 401: "Unauthorized",
                           403: "Forbidden", 404: "Not Found", 500: "Internal Server Error",
                           503: "Service Unavailable"}.get(reply.status, "")
        if reply.json_body is not None:
            content = json.dumps(reply.json_body).encode()
            response.headers["Content-Type"] = "application/json; charset=utf-8"
        else:
            content = (reply.text or "").encode()
        response.headers.update(reply.headers)
        response._content = content
        response.encoding = "utf-8"
        return response

    def close(self) -> None:
        pass


def attach(client: Client) -> FakeAdapter:
    adapter = FakeAdapter()
    client._http.session.mount("https://", adapter)
    client._http.session.mount("http://", adapter)
    client._http._sleep = lambda _: None
    return adapter


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("PTKIT_URL", "PTKIT_TOKEN", "PTKIT_USERNAME", "PTKIT_PASSWORD",
                 "PTKIT_CLIENT_SECRET"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def mp() -> Client:
    return Client(BASE_URL, token=TOKEN)


@pytest.fixture
def api(mp: Client) -> FakeAdapter:
    adapter = attach(mp)
    adapter.add("GET", "/api/deployment_configuration/v1/system_info", load("system_info.json"))
    return adapter
