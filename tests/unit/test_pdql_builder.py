from datetime import datetime, timezone

import pytest

from ptkit.pdql import Field, Query
from ptkit.vm import Host


class TestConditions:
    def test_comparison_operators(self) -> None:
        f = Field("Host.@CumulativeVulnerability")
        assert (f == 1).to_pdql() == "Host.@CumulativeVulnerability = 1"
        assert (f != 1).to_pdql() == "Host.@CumulativeVulnerability != 1"
        assert (f < 1).to_pdql() == "Host.@CumulativeVulnerability < 1"
        assert (f <= 1).to_pdql() == "Host.@CumulativeVulnerability <= 1"
        assert (f > 1).to_pdql() == "Host.@CumulativeVulnerability > 1"
        assert (f >= 1).to_pdql() == "Host.@CumulativeVulnerability >= 1"

    def test_null(self) -> None:
        assert (Host.fqdn == None).to_pdql() == "Host.FQDN = null"  # noqa: E711
        assert (Host.fqdn != None).to_pdql() == "Host.FQDN != null"  # noqa: E711

    def test_and_or_not_with_parentheses(self) -> None:
        a = Host.os_name == "a"
        b = Host.os_name == "b"
        c = Host.os_name == "c"
        assert (a & b & c).to_pdql() == "Host.OsName = 'a' and Host.OsName = 'b' and Host.OsName = 'c'"
        assert ((a | b) & c).to_pdql() == "(Host.OsName = 'a' or Host.OsName = 'b') and Host.OsName = 'c'"
        assert (a | (b & c)).to_pdql() == "Host.OsName = 'a' or (Host.OsName = 'b' and Host.OsName = 'c')"
        assert (~a).to_pdql() == "not (Host.OsName = 'a')"
        assert (~(a | b)).to_pdql() == "not (Host.OsName = 'a' or Host.OsName = 'b')"

    def test_condition_is_not_bool(self) -> None:
        with pytest.raises(TypeError, match="&"):
            bool(Host.os_name == "a")

    def test_combining_with_non_condition_fails(self) -> None:
        with pytest.raises(TypeError):
            (Host.os_name == "a") & True  # type: ignore[operator]

    def test_string_contains_and_startswith(self) -> None:
        assert Host.os_name.contains("Windows").to_pdql() == "Host.OsName like '%Windows%'"
        assert Host.fqdn.startswith("srv-").to_pdql() == "Host.FQDN like 'srv-%'"
        assert Host.fqdn.like("srv-__.%").to_pdql() == "Host.FQDN like 'srv-__.%'"
        assert Host.os_name.match("^win.*").to_pdql() == "Host.OsName match '^win.*'"

    def test_list_contains_uses_ip_literal(self) -> None:
        cond = Host.ip_addresses.contains("192.0.2.10")
        assert cond.to_pdql() == "Host.@IpAddresses contains 192.0.2.10"

    def test_list_contains_rejects_non_ip(self) -> None:
        with pytest.raises(ValueError):
            Host.ip_addresses.contains("192.0.2.10' or 1=1")

    def test_in_list_and_network(self) -> None:
        assert Host.os_name.in_(["a", "b"]).to_pdql() == "Host.OsName in ['a', 'b']"
        assert Host.ip_address.in_("192.0.2.0/24").to_pdql() == "Host.IpAddress in 192.0.2.0/24"
        assert Host.ip_address.in_(["192.0.2.1"]).to_pdql() == "Host.IpAddress in [192.0.2.1]"

    def test_in_rejects_plain_string_for_non_ip(self) -> None:
        with pytest.raises(TypeError):
            Host.os_name.in_("abc")

    def test_importance_synonyms(self) -> None:
        assert (Host.importance == "high").to_pdql() == "Host.@Importance = 'H'"
        assert Host.importance.in_(["high", "low", "M"]).to_pdql() == "Host.@Importance in ['H', 'L', 'M']"

    def test_uuid_field_validates_value(self) -> None:
        cond = Host.id == "1685CE7C-E440-0001-0000-000000000011"
        assert cond.to_pdql() == "Host.@Id = 1685ce7c-e440-0001-0000-000000000011"
        with pytest.raises(ValueError):
            Host.id == "x or 1=1"  # noqa: B015

    def test_datetime_field(self) -> None:
        moment = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
        assert (Host.updated_at >= moment).to_pdql() == "Host.@UpdateTime >= 2026-10-01T12:00:00"
        assert (Host.updated_at >= "2026-10-01").to_pdql() == "Host.@UpdateTime >= 2026-10-01T00:00:00"
        with pytest.raises(ValueError):
            Host.updated_at >= "Now() - 7d"  # noqa: B015
        with pytest.raises(TypeError):
            Host.updated_at >= 5  # noqa: B015

    def test_field_comparison_with_field_rejected(self) -> None:
        with pytest.raises(TypeError):
            Host.os_name == Host.os_version  # noqa: B015

    def test_field_is_hashable(self) -> None:
        assert len({Host.os_name, Host.os_name, Host.fqdn}) == 2


class TestQuery:
    def test_design_example(self) -> None:
        query = (
            Query()
            .select(Host.id, Host.name, Host.os_name)
            .filter(Host.os_name.contains("Windows") & (Host.importance == "high"))
            .sort(Host.name)
            .limit(500)
        )
        assert query.to_pdql() == (
            "filter(Host.OsName like '%Windows%' and Host.@Importance = 'H') "
            "| select(Host.@Id, Host.@Name, Host.OsName) "
            "| sort(Host.@Name ASC) "
            "| limit(500)"
        )

    def test_empty_query(self) -> None:
        assert Query().to_pdql() == ""

    def test_several_filters_joined_with_and(self) -> None:
        query = Query().filter(Host.os_name == "a").filter(Host.fqdn == "b")
        assert query.to_pdql() == "filter(Host.OsName = 'a' and Host.FQDN = 'b')"

    def test_sort_keys_and_direction(self) -> None:
        query = Query().select(Host.os_name).sort(Host.os_name).sort(Host.os_version, desc=True)
        assert query.to_pdql() == (
            "select(Host.OsName, Host.OsVersion) | sort(Host.OsName ASC, Host.OsVersion DESC)"
        )

    def test_sort_field_added_to_select_once(self) -> None:
        query = Query().select(Host.os_name, Host.os_name).sort(Host.fqdn)
        assert query.to_pdql() == "select(Host.OsName, Host.FQDN) | sort(Host.FQDN ASC)"

    def test_builder_is_immutable(self) -> None:
        base = Query().filter(Host.os_name == "a")
        limited = base.limit(10)
        assert base.to_pdql() == "filter(Host.OsName = 'a')"
        assert limited.to_pdql() == "filter(Host.OsName = 'a') | limit(10)"

    def test_custom_field_by_string(self) -> None:
        query = Query().select("Host.Softs.Name").filter(Field("Host.Softs.Vendor") == "Microsoft")
        assert query.to_pdql() == "filter(Host.Softs.Vendor = 'Microsoft') | select(Host.Softs.Name)"

    @pytest.mark.parametrize("bad", [-1, 1.5, True, "10"])
    def test_limit_validation(self, bad: object) -> None:
        with pytest.raises(ValueError):
            Query().limit(bad)  # type: ignore[arg-type]

    def test_filter_requires_condition(self) -> None:
        with pytest.raises(TypeError):
            Query().filter("Host.OsName = 'a'")  # type: ignore[arg-type]

    def test_select_rejects_injection(self) -> None:
        with pytest.raises(ValueError):
            Query().select("Host.OsName) | limit(1")

    def test_user_input_cannot_change_structure(self) -> None:
        user_input = "x' ) | select(Host.@Id) | filter(Host.OsName = 'y"
        query = Query().filter(Host.os_name == user_input)
        assert query.to_pdql() == f'filter(Host.OsName = "{user_input}")'
