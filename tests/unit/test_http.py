import logging

import pytest
import requests

from ptkit import AuthError, NotFoundError, PtkitError, ServerError, TimeoutError
from ptkit.vm import Client

from .conftest import BASE_URL, TOKEN, FakeAdapter, attach, load

GROUPS = "/api/assets_temporal_readmodel/v2/groups/hierarchy"
SYSTEM_INFO = "/api/deployment_configuration/v1/system_info"
CONNECT = "/connect/token"


def test_bearer_token_and_user_agent_sent(mp: Client, api: FakeAdapter) -> None:
    api.add("GET", GROUPS, load("groups_hierarchy.json"))
    mp.groups.tree()
    call = api.calls_to(GROUPS)[0]
    assert call.headers["Authorization"] == f"Bearer {TOKEN}"
    assert call.headers["User-Agent"].startswith("ptkit/")
    assert call.netloc == "mp.example.local"


def test_retries_5xx_with_doubling_backoff(mp: Client, api: FakeAdapter) -> None:
    delays = []
    mp._http._sleep = delays.append
    api.add("GET", GROUPS, status=503, text="busy")
    api.add("GET", GROUPS, status=502, text="busy")
    api.add("GET", GROUPS, load("groups_hierarchy.json"))
    assert len(mp.groups.list()) == 4
    assert len(api.calls_to(GROUPS)) == 3
    assert delays == [1.0, 2.0]


def test_server_error_after_all_retries(mp: Client, api: FakeAdapter) -> None:
    api.add("GET", GROUPS, status=500, json={"message": "Internal failure"})
    with pytest.raises(ServerError) as info:
        mp.groups.list()
    assert info.value.status_code == 500
    assert info.value.message == "Internal failure"
    assert info.value.path == GROUPS
    assert len(api.calls_to(GROUPS)) == 4  # 1 + retries=3


def test_timeout_after_all_retries() -> None:
    mp = Client(BASE_URL, token=TOKEN, retries=1, timeout=5)
    api = attach(mp)
    api.add("GET", SYSTEM_INFO, load("system_info.json"))
    api.add_error("GET", GROUPS, requests.ReadTimeout("read timed out"))
    with pytest.raises(TimeoutError):
        mp.groups.list()
    assert len(api.calls_to(GROUPS)) == 2


def test_connection_error_is_ptkit_error() -> None:
    mp = Client(BASE_URL, token=TOKEN, retries=0)
    api = attach(mp)
    api.add_error("GET", SYSTEM_INFO, requests.ConnectionError("refused"))
    api.add_error("GET", GROUPS, requests.ConnectionError("refused"))
    with pytest.raises(PtkitError, match="Не удалось подключиться к mp.example.local") as info:
        mp.groups.list()
    assert info.value.__cause__ is None
    assert info.value.__suppress_context__


def test_ssl_error_not_retried_and_hints_verify(mp: Client, api: FakeAdapter) -> None:
    api.add_error("GET", GROUPS, requests.exceptions.SSLError("CERTIFICATE_VERIFY_FAILED"))
    with pytest.raises(PtkitError, match="verify"):
        mp.groups.list()
    assert len(api.calls_to(GROUPS)) == 1


@pytest.mark.parametrize(("status", "error"), [(401, AuthError), (403, AuthError), (404, NotFoundError)])
def test_status_mapping_without_retries(
    mp: Client, api: FakeAdapter, status: int, error: type
) -> None:
    api.add("GET", GROUPS, status=status, json={"title": "Denied"})
    with pytest.raises(error) as info:
        mp.groups.list()
    assert info.value.status_code == status
    assert len(api.calls_to(GROUPS)) == 1


def test_other_4xx_is_base_error_with_text_message(mp: Client, api: FakeAdapter) -> None:
    api.add("GET", GROUPS, status=409, text="Conflict happened")
    with pytest.raises(PtkitError) as info:
        mp.groups.list()
    assert type(info.value) is PtkitError
    assert str(info.value) == "Conflict happened (HTTP 409)"


def test_errors_field_is_flattened(mp: Client, api: FakeAdapter) -> None:
    api.add("GET", GROUPS, status=422, json={"errors": {"type": ["bad value", "required"]}})
    with pytest.raises(PtkitError, match="type: bad value; required"):
        mp.groups.list()


def test_non_json_success_response(mp: Client, api: FakeAdapter) -> None:
    api.add("GET", GROUPS, text="<html>login</html>")
    with pytest.raises(PtkitError, match="не в формате JSON"):
        mp.groups.list()


class TestPasswordAuth:
    def make(self) -> "tuple[Client, FakeAdapter]":
        mp = Client(BASE_URL, username="svc-ptkit", password="S3cret!", client_secret="app-secret")
        api = attach(mp)
        api.add("GET", SYSTEM_INFO, load("system_info.json"))
        return mp, api

    def test_token_requested_once_and_used(self) -> None:
        mp, api = self.make()
        api.add("POST", CONNECT, load("connect_token.json"))
        api.add("GET", GROUPS, load("groups_hierarchy.json"))
        mp.groups.list()
        mp.groups.list()
        logins = api.calls_to(CONNECT)
        assert len(logins) == 1
        login = logins[0]
        assert login.netloc == "mp.example.local:3334"
        assert login.headers.get("Authorization") is None
        assert login.form() == {
            "grant_type": "password",
            "client_id": "mpx",
            "client_secret": "app-secret",
            "scope": "authorization offline_access mpx.api",
            "response_type": "code id_token",
            "username": "svc-ptkit",
            "password": "S3cret!",
        }
        token = load("connect_token.json")["access_token"]
        assert api.calls_to(GROUPS)[0].headers["Authorization"] == f"Bearer {token}"

    def test_relogin_once_on_401(self) -> None:
        mp, api = self.make()
        api.add("POST", CONNECT, load("connect_token.json"))
        api.add("GET", GROUPS, status=401, text="expired")
        api.add("GET", GROUPS, load("groups_hierarchy.json"))
        assert len(mp.groups.list()) == 4
        assert len(api.calls_to(CONNECT)) == 2

    def test_second_401_raises(self) -> None:
        mp, api = self.make()
        api.add("POST", CONNECT, load("connect_token.json"))
        api.add("GET", GROUPS, status=401, text="no")
        with pytest.raises(AuthError):
            mp.groups.list()
        assert len(api.calls_to(CONNECT)) == 2

    def test_wrong_password_single_attempt(self) -> None:
        mp, api = self.make()
        api.add("POST", CONNECT, load("connect_token_invalid_grant.json"), status=400)
        with pytest.raises(AuthError, match="invalid_username_or_password"):
            mp.groups.list()
        assert len(api.calls_to(CONNECT)) == 1
        assert api.calls_to(GROUPS) == []

    def test_custom_auth_url(self) -> None:
        mp = Client(
            BASE_URL,
            username="u",
            password="p",
            client_secret="s",
            auth_url="https://sso.example.local:8443",
        )
        api = attach(mp)
        api.add("GET", SYSTEM_INFO, load("system_info.json"))
        api.add("POST", CONNECT, load("connect_token.json"))
        api.add("GET", GROUPS, [])
        mp.groups.list()
        assert api.calls_to(CONNECT)[0].netloc == "sso.example.local:8443"


def test_secrets_never_logged_or_shown(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="ptkit")
    mp = Client(BASE_URL, username="svc", password="P@ssw0rd-xyz", client_secret="secret-abc",
                retries=1)
    api = attach(mp)
    api.add("GET", SYSTEM_INFO, load("system_info.json"))
    api.add("POST", CONNECT, load("connect_token.json"))
    api.add("GET", GROUPS, status=500, text="fail")
    with pytest.raises(ServerError) as info:
        mp.groups.list()
    access_token = load("connect_token.json")["access_token"]
    shown = " ".join([caplog.text, str(info.value), repr(info.value), repr(mp)])
    for secret in (access_token, "P@ssw0rd-xyz", "secret-abc"):
        assert secret not in shown
    assert "GET /api/assets_temporal_readmodel/v2/groups/hierarchy -> 500" in caplog.text


def test_static_token_not_in_repr_or_logs(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="ptkit")
    mp = Client(BASE_URL, token=TOKEN)
    api = attach(mp)
    api.add("GET", SYSTEM_INFO, load("system_info.json"))
    api.add("GET", GROUPS, status=401, json={"message": "Unauthorized"})
    with pytest.raises(AuthError) as info:
        mp.groups.list()
    assert TOKEN not in repr(mp)
    assert TOKEN not in caplog.text
    assert TOKEN not in str(info.value)
