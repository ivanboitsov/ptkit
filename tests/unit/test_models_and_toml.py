from datetime import datetime, timedelta, timezone

import pytest

from ptkit import _toml
from ptkit.vm._models import parse_datetime


class TestParseDatetime:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("2026-10-12T21:04:05Z", datetime(2026, 10, 12, 21, 4, 5, tzinfo=timezone.utc)),
            ("2026-10-12T21:04:05.1234567Z", datetime(2026, 10, 12, 21, 4, 5, 123456, tzinfo=timezone.utc)),
            ("2026-10-12T21:04:05.1Z", datetime(2026, 10, 12, 21, 4, 5, 100000, tzinfo=timezone.utc)),
            ("2026-10-12T21:04:05", datetime(2026, 10, 12, 21, 4, 5, tzinfo=timezone.utc)),
            (
                "2026-10-12T21:04:05+03:00",
                datetime(2026, 10, 12, 21, 4, 5, tzinfo=timezone(timedelta(hours=3))),
            ),
        ],
    )
    def test_formats(self, value: str, expected: datetime) -> None:
        assert parse_datetime(value) == expected

    @pytest.mark.parametrize("value", [None, "", "not a date", 12345, {"a": 1}])
    def test_unparsable(self, value: object) -> None:
        assert parse_datetime(value) is None


class TestFlatToml:
    """Разборщик для Python 3.9–3.10 (в 3.11+ используется tomllib)."""

    def test_values(self) -> None:
        text = (
            "# комментарий\n"
            'url = "https://mp.example.local"  # адрес\n'
            "verify = '/etc/ssl/corp-ca.pem'\n"
            "timeout = 30\n"
            "backoff = 1.5\n"
            "retries = 1_0\n"
            "check = false\n"
            'token = "a\\"b\\\\c\\u0041"\n'
        )
        assert _toml._loads_flat(text) == {
            "url": "https://mp.example.local",
            "verify": "/etc/ssl/corp-ca.pem",
            "timeout": 30,
            "backoff": 1.5,
            "retries": 10,
            "check": False,
            "token": 'a"b\\cA',
        }

    def test_same_result_as_tomllib(self) -> None:
        tomllib = pytest.importorskip("tomllib")
        text = 'url = "https://x"\ntimeout = 2.5\nverify = true\n'
        assert _toml._loads_flat(text) == tomllib.loads(text)

    @pytest.mark.parametrize(
        "text",
        ["[section]\n", "url\n", 'url = "open\n', "url = https://x\n", 'a = 1\na = 2\n', "a = 1 2\n"],
    )
    def test_errors(self, text: str) -> None:
        with pytest.raises(ValueError):
            _toml._loads_flat(text)
