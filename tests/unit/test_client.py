import logging
from pathlib import Path

import pytest

from ptkit import AuthError, PDQLError
from ptkit._http import PasswordAuth, TokenAuth
from ptkit.vm import Client, Host, _compat

from .conftest import BASE_URL, TOKEN, FakeAdapter, attach, load

PDQL_CREATE = "/api/assets_temporal_readmodel/v1/assets_grid"
PDQL_DATA = "/api/assets_temporal_readmodel/v1/assets_grid/data"
SYSTEM_INFO = "/api/deployment_configuration/v1/system_info"


class TestConstruction:
    def test_no_requests_on_init(self) -> None:
        mp = Client(BASE_URL + "/", token=TOKEN)
        api = attach(mp)
        assert mp.base_url == BASE_URL
        assert api.calls == []

    @pytest.mark.parametrize("url", ["mp.example.local", "ftp://mp", "https://", "https://mp?x=1"])
    def test_bad_url(self, url: str) -> None:
        with pytest.raises(ValueError):
            Client(url, token=TOKEN)

    def test_missing_url(self) -> None:
        with pytest.raises(ValueError, match="PTKIT_URL"):
            Client(token=TOKEN)

    def test_missing_credentials(self) -> None:
        with pytest.raises(ValueError, match="PTKIT_TOKEN"):
            Client(BASE_URL)

    def test_token_and_password_conflict(self) -> None:
        with pytest.raises(ValueError):
            Client(BASE_URL, token=TOKEN, username="u", password="p", client_secret="s")

    def test_password_without_client_secret(self) -> None:
        with pytest.raises(ValueError, match="client_secret"):
            Client(BASE_URL, username="u", password="p")

    def test_env_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PTKIT_URL", BASE_URL)
        monkeypatch.setenv("PTKIT_TOKEN", TOKEN)
        mp = Client()
        assert mp.base_url == BASE_URL
        assert isinstance(mp._http.auth, TokenAuth)

    def test_from_env_with_credentials(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PTKIT_URL", "https://[2001:db8::1]")
        monkeypatch.setenv("PTKIT_USERNAME", "svc")
        monkeypatch.setenv("PTKIT_PASSWORD", "p")
        monkeypatch.setenv("PTKIT_CLIENT_SECRET", "s")
        mp = Client.from_env(verify="/etc/ssl/corp-ca.pem", timeout=10)
        auth = mp._http.auth
        assert isinstance(auth, PasswordAuth)
        assert auth.token_url == "https://[2001:db8::1]:3334/connect/token"
        assert mp._http.session.verify == "/etc/ssl/corp-ca.pem"
        assert mp._http.timeout == 10

    def test_from_env_requires_url(self) -> None:
        with pytest.raises(ValueError, match="PTKIT_URL"):
            Client.from_env()

    def test_from_env_rejects_explicit_credentials(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PTKIT_URL", BASE_URL)
        with pytest.raises(TypeError):
            Client.from_env(token=TOKEN)

    def test_from_config(self, tmp_path: Path) -> None:
        path = tmp_path / "ptkit.toml"
        path.write_text(
            '# настройки\nurl = "https://mp.example.local"\ntoken = "abc"\n'
            'verify = "/etc/ssl/corp-ca.pem"\ntimeout = 15\nretries = 0\n',
            encoding="utf-8",
        )
        mp = Client.from_config(path, timeout=20)
        assert mp.base_url == BASE_URL
        assert mp._http.session.verify == "/etc/ssl/corp-ca.pem"
        assert mp._http.timeout == 20
        assert mp._http.retries == 0

    def test_from_config_unknown_key(self, tmp_path: Path) -> None:
        path = tmp_path / "ptkit.toml"
        path.write_text('url = "https://mp.example.local"\ntokn = "abc"\n', encoding="utf-8")
        with pytest.raises(ValueError, match="tokn"):
            Client.from_config(path)

    def test_verify_false_warns(self, caplog: pytest.LogCaptureFixture) -> None:
        caplog.set_level(logging.WARNING, logger="ptkit")
        Client(BASE_URL, token=TOKEN, verify=False)
        assert "verify=False" in caplog.text

    def test_context_manager_closes(self) -> None:
        closed = []
        with Client(BASE_URL, token=TOKEN) as mp:
            mp._http.session.close = lambda: closed.append(True)  # type: ignore[method-assign]
        assert closed == [True]


class TestVersion:
    def test_version_cached(self, mp: Client, api: FakeAdapter) -> None:
        assert mp.version() == "27.2.0"
        assert mp.version() == "27.2.0"
        assert len(api.calls_to(SYSTEM_INFO)) == 1

    def test_untested_version_warns_once(
        self, mp: Client, api: FakeAdapter, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.WARNING, logger="ptkit")
        api.add("GET", "/api/assets_temporal_readmodel/v2/groups/hierarchy", [])
        mp.groups.list()
        mp.groups.list()
        warnings = [r for r in caplog.records if "не проверялась" in r.getMessage()]
        assert len(warnings) == 1
        assert len(api.calls_to(SYSTEM_INFO)) == 1

    def test_tested_version_no_warning(
        self,
        mp: Client,
        api: FakeAdapter,
        caplog: pytest.LogCaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(_compat, "TESTED_VERSIONS", ("27.2",))
        caplog.set_level(logging.WARNING, logger="ptkit")
        mp.version()
        assert "не проверялась" not in caplog.text

    def test_version_failure_does_not_block_requests(self) -> None:
        mp = Client(BASE_URL, token=TOKEN)
        api = attach(mp)
        api.add("GET", SYSTEM_INFO, status=404, text="")
        api.add("GET", "/api/assets_temporal_readmodel/v2/groups/hierarchy", [])
        assert mp.groups.list() == []

    def test_auth_error_during_version_check_propagates(self) -> None:
        mp = Client(BASE_URL, token=TOKEN)
        api = attach(mp)
        api.add("GET", SYSTEM_INFO, status=401, text="")
        with pytest.raises(AuthError):
            mp.groups.list()
        assert len(api.calls) == 1


class TestPdql:
    def test_lazy_until_first_row(self, mp: Client, api: FakeAdapter) -> None:
        api.add("POST", PDQL_CREATE, load("pdql_create.json"))
        api.add("GET", PDQL_DATA, load("pdql_data_hosts.json"))
        rows = mp.pdql("select(@Host, Host.OsName) | limit(10)")
        assert api.calls == []
        first = next(rows)
        assert first["Host.OsName"] == "Windows Server 2019"

    def test_request_body_and_paging(self, mp: Client, api: FakeAdapter) -> None:
        records = load("pdql_data_hosts.json")["records"]
        api.add("POST", PDQL_CREATE, load("pdql_create.json"))
        api.add("GET", PDQL_DATA, {"records": records})
        api.add("GET", PDQL_DATA, {"records": records})
        api.add("GET", PDQL_DATA, {"records": records[:1]})
        rows = list(mp.pdql("select(@Host)", page_size=2))
        assert len(rows) == 5

        body = api.calls_to(PDQL_CREATE)[0].json()
        assert body == {"pdql": "select(@Host)", "includeNestedGroups": True, "utcOffset": "+00:00"}
        pages = api.calls_to(PDQL_DATA)
        token = load("pdql_create.json")["token"]
        assert [p.params for p in pages] == [
            {"pdqlToken": token, "offset": "0", "limit": "2"},
            {"pdqlToken": token, "offset": "2", "limit": "2"},
            {"pdqlToken": token, "offset": "4", "limit": "2"},
        ]

    def test_exact_page_boundary_stops_on_empty_page(self, mp: Client, api: FakeAdapter) -> None:
        records = load("pdql_data_hosts.json")["records"]
        api.add("POST", PDQL_CREATE, load("pdql_create.json"))
        api.add("GET", PDQL_DATA, {"records": records})
        api.add("GET", PDQL_DATA, {"records": []})
        assert len(list(mp.pdql("select(@Host)", page_size=2))) == 2
        assert len(api.calls_to(PDQL_DATA)) == 2

    def test_group_restriction(self, mp: Client, api: FakeAdapter) -> None:
        api.add("POST", PDQL_CREATE, load("pdql_create.json"))
        api.add("GET", PDQL_DATA, {"records": []})
        list(mp.pdql("select(@Host)", group_id="1685cf07-70c0-0001-0000-000000000009"))
        body = api.calls_to(PDQL_CREATE)[0].json()
        assert body["additionalFilterParameters"] == {
            "groupIds": ["1685cf07-70c0-0001-0000-000000000009"],
            "assetIds": [],
        }

    def test_accepts_builder(self, mp: Client, api: FakeAdapter) -> None:
        api.add("POST", PDQL_CREATE, load("pdql_create.json"))
        api.add("GET", PDQL_DATA, {"records": []})
        query = mp.assets.query().select(Host.os_name).limit(5)
        list(mp.pdql(query))
        assert api.calls_to(PDQL_CREATE)[0].json()["pdql"] == query.to_pdql()

    def test_rejected_query(self, mp: Client, api: FakeAdapter) -> None:
        api.add("POST", PDQL_CREATE, load("pdql_error.json"), status=400)
        with pytest.raises(PDQLError) as info:
            list(mp.pdql("select(@Host, Host.OsNam)"))
        assert info.value.message == "Unknown field 'Host.OsNam'"

    def test_missing_token(self, mp: Client, api: FakeAdapter) -> None:
        api.add("POST", PDQL_CREATE, {"isPotentiallySlow": False})
        with pytest.raises(PDQLError):
            list(mp.pdql("select(@Host)"))

    @pytest.mark.parametrize("query", ["", "   "])
    def test_empty_query(self, mp: Client, query: str) -> None:
        with pytest.raises(ValueError):
            mp.pdql(query)

    def test_bad_page_size_fails_immediately(self, mp: Client) -> None:
        with pytest.raises(ValueError):
            mp.pdql("select(@Host)", page_size=0)
