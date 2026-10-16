from datetime import datetime, timezone

import pytest

from ptkit import NotFoundError
from ptkit.vm import Asset, Client, Field, Group, Host, Ref, ScanTask, TaskRun

from .conftest import FakeAdapter, load

PDQL_CREATE = "/api/assets_temporal_readmodel/v1/assets_grid"
PDQL_DATA = "/api/assets_temporal_readmodel/v1/assets_grid/data"
GROUPS = "/api/assets_temporal_readmodel/v2/groups/hierarchy"
TASKS = "/api/scanning/v3/scanner_tasks"
TASK_ID = "19170911-c100-0001-0000-000000000002"


class TestAssets:
    def test_query_iterates_assets(self, mp: Client, api: FakeAdapter) -> None:
        api.add("POST", PDQL_CREATE, load("pdql_create.json"))
        api.add("GET", PDQL_DATA, load("pdql_data_hosts.json"))
        query = (
            mp.assets.query()
            .filter(Host.os_name.contains("Windows"))
            .in_group("1685cf07-70c0-0001-0000-000000000009")
            .limit(500)
        )
        hosts = list(query)
        assert [h.name for h in hosts] == ["srv-01.example.local", "srv-02.example.local"]

        first = hosts[0]
        assert isinstance(first, Asset)
        assert first.id == "1685ce7c-e440-0001-0000-000000000011"
        assert first.os_name == "Windows Server 2019"
        assert first.ip_address == "192.0.2.11"
        assert first.importance == "H"
        assert first.created_at == datetime(2026, 3, 1, 8, 15, 30, 123456, tzinfo=timezone.utc)
        assert hosts[1].updated_at is None
        assert first.raw["@Host"]["deviceType"] == "Server"
        assert first["host.osname"] == "Windows Server 2019"
        assert first[Host.fqdn] == "srv-01.example.local"
        with pytest.raises(KeyError):
            first[Field("Host.Softs.Name")]

        body = api.calls_to(PDQL_CREATE)[0].json()
        assert body["pdql"] == (
            "filter(Host.OsName like '%Windows%') | select(@Host, Host.OsName, Host.OsVersion, "
            "Host.FQDN, Host.IpAddress, Host.@Importance, Host.@CreationTime, Host.@UpdateTime) "
            "| limit(500)"
        )
        assert body["additionalFilterParameters"]["groupIds"] == [
            "1685cf07-70c0-0001-0000-000000000009"
        ]

    def test_query_with_select_replaces_defaults(self, mp: Client) -> None:
        query = mp.assets.query().select(Host.id, Host.name, Host.os_name).sort(Host.name)
        assert query.to_pdql() == (
            "select(@Host, Host.@Id, Host.@Name, Host.OsName) | sort(Host.@Name ASC)"
        )

    def test_rows_returns_dicts(self, mp: Client, api: FakeAdapter) -> None:
        api.add("POST", PDQL_CREATE, load("pdql_create.json"))
        api.add("GET", PDQL_DATA, load("pdql_data_hosts.json"))
        rows = list(mp.assets.query().rows())
        assert rows[0]["Host.FQDN"] == "srv-01.example.local"

    def test_unbound_query_cannot_run(self) -> None:
        from ptkit.vm.assets import AssetQuery

        with pytest.raises(RuntimeError):
            list(AssetQuery())

    def test_get(self, mp: Client, api: FakeAdapter) -> None:
        record = load("pdql_data_hosts.json")["records"][0]
        api.add("POST", PDQL_CREATE, load("pdql_create.json"))
        api.add("GET", PDQL_DATA, {"records": [record]})
        asset = mp.assets.get("1685CE7C-E440-0001-0000-000000000011")
        assert asset.name == "srv-01.example.local"
        assert asset.os_name == "Windows Server 2019"
        pdql = api.calls_to(PDQL_CREATE)[0].json()["pdql"]
        assert pdql.startswith("filter(Host.@Id = 1685ce7c-e440-0001-0000-000000000011) | select(")
        assert "Host.@Id" in pdql.split("select(")[1]
        assert pdql.endswith("| limit(1)")

    def test_get_not_found(self, mp: Client, api: FakeAdapter) -> None:
        api.add("POST", PDQL_CREATE, load("pdql_create.json"))
        api.add("GET", PDQL_DATA, {"records": []})
        with pytest.raises(NotFoundError):
            mp.assets.get("1685ce7c-e440-0001-0000-0000000000ff")

    def test_get_ignores_other_asset(self, mp: Client, api: FakeAdapter) -> None:
        record = load("pdql_data_hosts.json")["records"][1]
        api.add("POST", PDQL_CREATE, load("pdql_create.json"))
        api.add("GET", PDQL_DATA, {"records": [record]})
        with pytest.raises(NotFoundError):
            mp.assets.get("1685ce7c-e440-0001-0000-000000000011")

    def test_get_validates_id(self, mp: Client) -> None:
        with pytest.raises(ValueError):
            mp.assets.get("' or 1=1")


class TestGroups:
    def test_tree(self, mp: Client, api: FakeAdapter) -> None:
        api.add("GET", GROUPS, load("groups_hierarchy.json"))
        roots = mp.groups.tree()
        assert len(roots) == 1
        root = roots[0]
        assert isinstance(root, Group)
        assert root.name == "Root"
        assert root.is_root and root.is_read_only and not root.is_removable
        assert [c.name for c in root.children] == ["Import", "Windows", "Unmanaged hosts"]
        assert root.children[1].type == "dynamic"
        assert root.children[1].parent_id == root.id
        assert root.raw["isSlow"] is False

    def test_list_flat_depth_first(self, mp: Client, api: FakeAdapter) -> None:
        api.add("GET", GROUPS, load("groups_hierarchy.json"))
        groups = mp.groups.list()
        assert [(g.id, g.name) for g in groups][:2] == [
            ("00000000-0000-0000-0000-000000000002", "Root"),
            ("1685ce7c-e440-0001-0000-000000000005", "Import"),
        ]
        assert len(groups) == 4

    def test_get(self, mp: Client, api: FakeAdapter) -> None:
        api.add("GET", GROUPS, load("groups_hierarchy.json"))
        group = mp.groups.get("1685CF07-70C0-0001-0000-000000000009")
        assert group.name == "Windows"
        assert group.tree_path == "Windows"

    def test_get_not_found(self, mp: Client, api: FakeAdapter) -> None:
        api.add("GET", GROUPS, load("groups_hierarchy.json"))
        with pytest.raises(NotFoundError):
            mp.groups.get("00000000-0000-0000-0000-0000000000ff")


class TestTasks:
    def test_list(self, mp: Client, api: FakeAdapter) -> None:
        api.add("GET", TASKS, load("scanner_tasks.json"))
        tasks = mp.tasks.list()
        assert [t.name for t in tasks] == ["Аудит серверов Windows", "Обнаружение узлов"]
        task = tasks[0]
        assert isinstance(task, ScanTask)
        assert task.status == "finished"
        assert task.profile == Ref(id="e27ac04f-95fb-41e0-ad0e-185b6713f08c", name="WindowsAudit")
        assert task.scope is not None and task.scope.name == "Инфраструктура по умолчанию"
        assert task.next_run_at == datetime(2026, 10, 19, 2, 0, tzinfo=timezone.utc)
        assert task.last_run_error_level == "green"
        assert task.raw["include"]["targets"] == ["192.0.2.0/24"]
        assert tasks[1].last_run_at is None

    def test_get(self, mp: Client, api: FakeAdapter) -> None:
        api.add("GET", f"{TASKS}/{TASK_ID}", load("scanner_task.json"))
        task = mp.tasks.get(TASK_ID)
        assert task.id == TASK_ID
        assert task.validation_state == "valid"

    def test_get_escapes_path(self, mp: Client, api: FakeAdapter) -> None:
        api.add("GET", f"{TASKS}/..%2F..%2Fadmin", status=404, text="")
        with pytest.raises(NotFoundError):
            mp.tasks.get("../../admin")

    def test_runs_paging_and_filters(self, mp: Client, api: FakeAdapter) -> None:
        runs_path = f"/api/scanning/v2/scanner_tasks/{TASK_ID}/runs"
        page = load("task_runs.json")
        api.add("GET", runs_path, {"items": page["items"][:1], "totalItems": 2})
        api.add("GET", runs_path, {"items": page["items"][1:], "totalItems": 2})
        runs = list(
            mp.tasks.runs(
                TASK_ID,
                time_from=datetime(2026, 10, 1, tzinfo=timezone.utc),
                with_errors=False,
                page_size=1,
            )
        )
        assert [r.trigger_type for r in runs] == ["scheduled", "manual"]
        run = runs[1]
        assert isinstance(run, TaskRun)
        assert run.task_id == TASK_ID
        assert run.started_by == "analyst"
        assert run.job_count == 12
        assert run.finished_at == datetime(2026, 10, 5, 3, 1, 44, tzinfo=timezone.utc)
        calls = api.calls_to(runs_path)
        assert len(calls) == 2
        assert calls[0].params == {
            "offset": "0",
            "limit": "1",
            "timeFrom": "2026-10-01T00:00:00Z",
            "withErrors": "false",
        }
        assert calls[1].params["offset"] == "1"

    def test_runs_single_page(self, mp: Client, api: FakeAdapter) -> None:
        runs_path = f"/api/scanning/v2/scanner_tasks/{TASK_ID}/runs"
        api.add("GET", runs_path, load("task_runs.json"))
        assert len(list(mp.tasks.runs(TASK_ID))) == 2
        assert len(api.calls_to(runs_path)) == 1
