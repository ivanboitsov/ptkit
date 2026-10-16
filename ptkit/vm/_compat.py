"""Всё, что зависит от версии MaxPatrol VM: адреса запросов, имена полей, форматы.

Поддержка новой версии MaxPatrol — это правка этого модуля и записанных
ответов в ``tests/fixtures/``, а не всей библиотеки.

Источник — справка MaxPatrol VM 2.7, «Справочник разработчика -> Виды запросов
к API» и «Справочник по языку запросов PDQL»:
https://help.ptsecurity.com/ru-RU/projects/vm/2.7/help/2697413643

Эндпоинты с пометкой «не документирован» в справке 2.7 не описаны. Их использует
веб-интерфейс MaxPatrol, и они показаны в открытых материалах (вебинар PT
«How to use MaxPatrol VM API», Positive CLI). Без них не выполнить требования
библиотеки (постраничное чтение результатов PDQL, версия сервера). Решение и
риски описаны в docs/adr/0001-api-sources.md.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

# --- Совместимость -----------------------------------------------------------

#: Значения ``productVersion`` (или их префиксы), с которыми проверена эта версия
#: ptkit. Сервер возвращает версию ядра MaxPatrol 10 (вида ``27.2.12345``), а не
#: номер выпуска MaxPatrol VM.
#: TODO: заполнить после первого прогона tests/live на MaxPatrol VM 2.7 —
#: соответствие «VM 2.7 -> версия ядра» в справке не указано.
TESTED_VERSIONS: Tuple[str, ...] = ()


def is_tested(version: str) -> bool:
    return any(version == v or version.startswith(v + ".") for v in TESTED_VERSIONS)


# --- Авторизация (PT Management and Configuration) ---------------------------
# «Получение токена доступа»: POST <адрес>:3334/connect/token,
# application/x-www-form-urlencoded, ответ access_token / expires_in (86400 с).

AUTH_PORT = 3334
AUTH_TOKEN_PATH = "/connect/token"
AUTH_CLIENT_ID = "mpx"
AUTH_SCOPE = "authorization offline_access mpx.api"
AUTH_RESPONSE_TYPE = "code id_token"

# --- Версия сервера ----------------------------------------------------------

#: Не документирован.
SYSTEM_INFO = "/api/deployment_configuration/v1/system_info"


def product_version(data: Any) -> Optional[str]:
    value = data.get("productVersion") if isinstance(data, dict) else None
    return str(value) if value else None


# --- PDQL --------------------------------------------------------------------
# «Получение токена PDQL-запросов»: POST .../assets_grid возвращает token
# (действует 30 минут). Строки результата читаются по токену постранично.

PDQL_CREATE = "/api/assets_temporal_readmodel/v1/assets_grid"
#: Не документирован. GET ?pdqlToken=&offset=&limit=, ответ {"records": [...]}.
PDQL_DATA = "/api/assets_temporal_readmodel/v1/assets_grid/data"
PDQL_PAGE_SIZE = 1000
#: Время в MaxPatrol хранится в UTC; так время в запросе и в ответе не зависит
#: от часового пояса машины, где запущен скрипт.
PDQL_UTC_OFFSET = "+00:00"


def pdql_request(
    pdql: str,
    group_ids: Sequence[str] = (),
    asset_ids: Sequence[str] = (),
) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "pdql": pdql,
        "includeNestedGroups": True,
        "utcOffset": PDQL_UTC_OFFSET,
    }
    if group_ids or asset_ids:
        # «Дополнительные параметры фильтра»: groupIds — группы, в которых идёт
        # выборка; assetIds — активы, по которым выполняется запрос.
        body["additionalFilterParameters"] = {
            "groupIds": list(group_ids),
            "assetIds": list(asset_ids),
        }
    return body


def pdql_token(data: Any) -> Optional[str]:
    value = data.get("token") if isinstance(data, dict) else None
    return value if isinstance(value, str) and value else None


def pdql_data_params(token: str, offset: int, limit: int) -> Dict[str, Any]:
    return {"pdqlToken": token, "offset": offset, "limit": limit}


def pdql_records(data: Any) -> List[Dict[str, Any]]:
    records = data.get("records") if isinstance(data, dict) else data
    return [r for r in records if isinstance(r, dict)] if isinstance(records, list) else []


# --- Активы: поля модели Host в PDQL -----------------------------------------
# «Объекты модели активов» и «Общие псевдонимы активов». Атрибуты модели
# регистронезависимы; псевдонимы записываются как Host.@Alias.

#: Колонка с объектом актива ({"id": ..., "name": ...}); всегда первая в select.
ASSET_COLUMN = "@Host"
ASSET_COLUMN_ID = "id"
ASSET_COLUMN_NAME = "name"

HOST_FIELDS: Mapping[str, str] = {
    "id": "Host.@Id",
    "name": "Host.@Name",
    "os_name": "Host.OsName",
    "os_version": "Host.OsVersion",
    "fqdn": "Host.FQDN",
    "ip_address": "Host.IpAddress",
    "ip_addresses": "Host.@IpAddresses",
    "importance": "Host.@Importance",
    "description": "Host.@Description",
    "created_at": "Host.@CreationTime",
    "updated_at": "Host.@UpdateTime",
    "audited_at": "Host.@AuditTime",
}

#: Поля, которые выбираются, если в запросе не вызван select().
DEFAULT_HOST_FIELDS: Tuple[str, ...] = (
    "os_name",
    "os_version",
    "fqdn",
    "ip_address",
    "importance",
    "created_at",
    "updated_at",
)

#: Значимость актива в PDQL записывается кодом: Host.@Importance in ['H', 'M'].
IMPORTANCE_CODES: Mapping[str, str] = {"high": "H", "medium": "M", "low": "L"}

# --- Группы активов ----------------------------------------------------------
# «Получение идентификатора группы активов»: GET .../groups/hierarchy,
# ответ — дерево групп от корневой.

GROUPS_HIERARCHY = "/api/assets_temporal_readmodel/v2/groups/hierarchy"

GROUP_FIELDS: Mapping[str, str] = {
    "id": "id",
    "name": "name",
    "type": "groupType",
    "tree_path": "treePath",
    "is_root": "isRoot",
    "is_read_only": "isReadOnly",
    "is_removable": "isRemovable",
}
GROUP_CHILDREN = "children"

# --- Задачи сканирования -----------------------------------------------------
# Используется контракт v3: только у него список задач читается запросом GET
# («Запрос отчета обо всех задачах»); список v4 — POST с телом-фильтром.

SCANNER_TASKS = "/api/scanning/v3/scanner_tasks"
SCANNER_TASK = "/api/scanning/v3/scanner_tasks/{task_id}"

SCAN_TASK_FIELDS: Mapping[str, str] = {
    "id": "id",
    "name": "name",
    "description": "description",
    "status": "status",
    "created_at": "created",
    "last_run_at": "lastRun",
    "next_run_at": "nextRun",
    "last_run_error_level": "lastRunErrorLevel",
    "validation_state": "validationState",
    "profile": "profile",
    "scope": "scope",
}

# «Получение истории запусков задачи»: GET .../runs, ответ {items, totalItems}.
TASK_RUNS = "/api/scanning/v2/scanner_tasks/{task_id}/runs"
TASK_RUNS_PAGE_SIZE = 100

TASK_RUN_FIELDS: Mapping[str, str] = {
    "id": "id",
    "status": "status",
    "started_at": "startedAt",
    "finished_at": "finishedAt",
    "job_count": "jobCount",
    "trigger_type": "triggerType",
    "error_status": "errorStatus",
    "started_by": "startedBy",
    "stopped_by": "stoppedBy",
}
USER_LOGIN = "login"


def task_runs_params(
    offset: int,
    limit: int,
    time_from: Optional[str],
    time_to: Optional[str],
    with_errors: Optional[bool],
) -> Dict[str, Any]:
    params: Dict[str, Any] = {"offset": offset, "limit": limit}
    if time_from is not None:
        params["timeFrom"] = time_from
    if time_to is not None:
        params["timeTo"] = time_to
    if with_errors is not None:
        params["withErrors"] = "true" if with_errors else "false"
    return params


def page_items(data: Any) -> List[Dict[str, Any]]:
    """Элементы списка: ответ — массив или объект с полем ``items``."""
    items = data.get("items") if isinstance(data, dict) else data
    return [i for i in items if isinstance(i, dict)] if isinstance(items, list) else []


def page_total(data: Any) -> Optional[int]:
    total = data.get("totalItems") if isinstance(data, dict) else None
    return total if isinstance(total, int) else None


# --- Общие помощники для моделей ---------------------------------------------


def pick(raw: Mapping[str, Any], fields: Mapping[str, str], attr: str) -> Any:
    return raw.get(fields[attr])


def lower_keys(row: Mapping[str, Any]) -> Dict[str, Any]:
    """Ключи строки PDQL без учёта регистра: атрибуты модели регистронезависимы."""
    return {k.lower(): v for k, v in row.items()}
