import ipaddress
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest

from ptkit.pdql.escape import check_identifier, literal, literal_list, quote_string


class TestQuoteString:
    def test_plain_string_in_single_quotes(self) -> None:
        assert quote_string("Windows") == "'Windows'"

    def test_single_quote_inside_uses_double_quotes(self) -> None:
        assert quote_string("O'Brien") == '"O\'Brien"'

    def test_double_quote_inside_uses_single_quotes(self) -> None:
        assert quote_string('say "hi"') == "'say \"hi\"'"

    def test_backslash_is_doubled(self) -> None:
        assert quote_string("C:\\ProgramData") == "'C:\\\\ProgramData'"

    def test_trailing_backslash_cannot_escape_closing_quote(self) -> None:
        assert quote_string("C:\\") == "'C:\\\\'"

    @pytest.mark.parametrize("value", ["a'b\"c", "x' or Host.OsName = \"y"])
    def test_both_quote_kinds_rejected(self, value: str) -> None:
        with pytest.raises(ValueError, match="кавычки"):
            quote_string(value)

    @pytest.mark.parametrize("value", ["line\nbreak", "tab\there", "nul\x00", "del\x7f"])
    def test_control_characters_rejected(self, value: str) -> None:
        with pytest.raises(ValueError, match="управляющие"):
            quote_string(value)

    def test_unicode_kept(self) -> None:
        assert quote_string("Сервер «Бухгалтерия»") == "'Сервер «Бухгалтерия»'"


class TestLiteral:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (None, "null"),
            (True, "true"),
            (False, "false"),
            (0, "0"),
            (-3, "-3"),
            (7.5, "7.5"),
            ("text", "'text'"),
            (uuid.UUID("123e4567-e89b-12d3-a456-426655440000"), "123e4567-e89b-12d3-a456-426655440000"),
            (ipaddress.ip_address("192.0.2.235"), "192.0.2.235"),
            (ipaddress.ip_network("192.0.2.0/24"), "192.0.2.0/24"),
            (date(2026, 1, 2), "2026-01-02"),
            (datetime(2020, 7, 22, 18, 8, 38), "2020-07-22T18:08:38"),
        ],
    )
    def test_values(self, value: object, expected: str) -> None:
        assert literal(value) == expected

    def test_aware_datetime_converted_to_utc(self) -> None:
        moscow = timezone(timedelta(hours=3))
        assert literal(datetime(2026, 1, 1, 3, 0, 0, 999, tzinfo=moscow)) == "2026-01-01T00:00:00"

    def test_list(self) -> None:
        assert literal_list(["H", "M"]) == "['H', 'M']"
        assert literal([1, None]) == "[1, null]"

    def test_infinite_float_rejected(self) -> None:
        with pytest.raises(ValueError):
            literal(float("inf"))

    def test_unsupported_type(self) -> None:
        with pytest.raises(TypeError):
            literal(object())


class TestIdentifier:
    @pytest.mark.parametrize(
        "path",
        [
            "@Host",
            "Host.OsName",
            "Host.@Id",
            "Host.@IpAddresses.Item",
            "Host.Endpoints<TransportEndpoint>.Port",
            "WindowsHost.Softs<Software:Kaspersky:KasperskySecurityCenter>.Plugins",
        ],
    )
    def test_valid(self, path: str) -> None:
        assert check_identifier(path) == path

    @pytest.mark.parametrize(
        "path",
        ["", "Host.OsName) | limit(1", "Host OsName", "Host.'x'", "Host.OsName = 1", "Host..OsName"],
    )
    def test_invalid(self, path: str) -> None:
        with pytest.raises(ValueError):
            check_identifier(path)
