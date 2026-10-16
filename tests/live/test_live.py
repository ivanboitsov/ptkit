"""Тесты на живом MaxPatrol VM. Только чтение.

Запускаются, если заданы ``PTKIT_URL`` и ``PTKIT_TOKEN`` (или ``PTKIT_USERNAME``,
``PTKIT_PASSWORD``, ``PTKIT_CLIENT_SECRET``). Путь к корневому сертификату —
``PTKIT_VERIFY`` (по умолчанию системное хранилище).

    pytest tests/live -v

Первый прогон на новой версии MaxPatrol проверяет недокументированные эндпоинты
(``system_info``, ``assets_grid/data``); результат запишите в ``ptkit/vm/_compat.py``
(``TESTED_VERSIONS``) и в таблицу совместимости.
"""

from __future__ import annotations

import os
from typing import Iterator

import pytest

from ptkit.vm import Client, Host

has_credentials = bool(os.environ.get("PTKIT_TOKEN")) or bool(
    os.environ.get("PTKIT_USERNAME") and os.environ.get("PTKIT_PASSWORD")
)
pytestmark = pytest.mark.skipif(
    not (os.environ.get("PTKIT_URL") and has_credentials),
    reason="нужны PTKIT_URL и PTKIT_TOKEN (или PTKIT_USERNAME/PTKIT_PASSWORD/PTKIT_CLIENT_SECRET)",
)


@pytest.fixture(scope="module")
def mp() -> Iterator[Client]:
    verify: bool | str = os.environ.get("PTKIT_VERIFY") or True
    with Client.from_env(verify=verify) as client:
        yield client


def test_version(mp: Client) -> None:
    version = mp.version()
    print(f"productVersion: {version}")
    assert version


def test_raw_pdql(mp: Client) -> None:
    rows = list(mp.pdql("select(@Host, Host.OsName) | limit(3)"))
    assert len(rows) <= 3
    for row in rows:
        assert "@Host" in row or "@host" in {k.lower() for k in row}


def test_builder_and_get(mp: Client) -> None:
    hosts = list(mp.assets.query().select(Host.id, Host.name, Host.os_name).sort(Host.name).limit(2))
    if not hosts:
        pytest.skip("в MaxPatrol нет активов")
    first = hosts[0]
    assert first.id
    again = mp.assets.get(first.id)
    assert again.id == first.id


def test_paging(mp: Client) -> None:
    rows = list(mp.pdql("select(@Host) | limit(5)", page_size=2))
    assert len(rows) <= 5


def test_groups(mp: Client) -> None:
    groups = mp.groups.list()
    assert groups, "в MaxPatrol всегда есть корневая группа"
    assert mp.groups.get(groups[0].id).id == groups[0].id


def test_group_restriction(mp: Client) -> None:
    group = mp.groups.list()[0]
    list(mp.assets.query().in_group(group.id).limit(1))


def test_tasks(mp: Client) -> None:
    tasks = mp.tasks.list()
    if not tasks:
        pytest.skip("в MaxPatrol нет задач сканирования")
    task = mp.tasks.get(tasks[0].id)
    assert task.id == tasks[0].id
    for run in mp.tasks.runs(task.id, page_size=5):
        assert run.task_id == task.id
        break
