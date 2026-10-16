"""Задачи сканирования: ``ScanTask``, ``TaskRun`` и ресурс ``mp.tasks``."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Iterator, List, Optional, Union
from urllib.parse import quote

from ..errors import PtkitError
from ..pdql.escape import format_datetime
from . import _compat
from ._models import RawDict, Ref, as_int, as_str, parse_datetime

if TYPE_CHECKING:
    from .client import Client

__all__ = ["ScanTask", "TaskRun", "Tasks"]


@dataclass
class ScanTask:
    """Задача сканирования."""

    id: str
    name: Optional[str]
    description: Optional[str] = None
    #: new, preparing, waiting, running, finishing, finished, suspending, suspended, imported.
    status: Optional[str] = None
    created_at: Optional[datetime] = None
    last_run_at: Optional[datetime] = None
    next_run_at: Optional[datetime] = None
    #: green, yellow, red.
    last_run_error_level: Optional[str] = None
    #: valid, invalid.
    validation_state: Optional[str] = None
    profile: Optional[Ref] = None
    scope: Optional[Ref] = None
    raw: RawDict = field(default_factory=dict, repr=False)

    @classmethod
    def from_raw(cls, raw: RawDict) -> ScanTask:
        f = _compat.SCAN_TASK_FIELDS

        def get(attr: str) -> Any:
            return _compat.pick(raw, f, attr)

        task_id = as_str(get("id"))
        if not task_id:
            raise PtkitError("В ответе MaxPatrol задача без идентификатора")
        return cls(
            id=task_id,
            name=as_str(get("name")),
            description=as_str(get("description")),
            status=as_str(get("status")),
            created_at=parse_datetime(get("created_at")),
            last_run_at=parse_datetime(get("last_run_at")),
            next_run_at=parse_datetime(get("next_run_at")),
            last_run_error_level=as_str(get("last_run_error_level")),
            validation_state=as_str(get("validation_state")),
            profile=Ref.parse(get("profile")),
            scope=Ref.parse(get("scope")),
            raw=raw,
        )


@dataclass
class TaskRun:
    """Запуск задачи сканирования."""

    id: str
    task_id: str
    status: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    job_count: Optional[int] = None
    #: Способ запуска: вручную или по расписанию.
    trigger_type: Optional[str] = None
    error_status: Optional[str] = None
    #: Логин пользователя, запустившего задачу.
    started_by: Optional[str] = None
    #: Логин пользователя, остановившего задачу.
    stopped_by: Optional[str] = None
    raw: RawDict = field(default_factory=dict, repr=False)

    @classmethod
    def from_raw(cls, raw: RawDict, task_id: str) -> TaskRun:
        f = _compat.TASK_RUN_FIELDS

        def get(attr: str) -> Any:
            return _compat.pick(raw, f, attr)

        def login(value: Any) -> Optional[str]:
            return as_str(value.get(_compat.USER_LOGIN)) if isinstance(value, dict) else None

        run_id = as_str(get("id"))
        if not run_id:
            raise PtkitError("В ответе MaxPatrol запуск без идентификатора")
        return cls(
            id=run_id,
            task_id=task_id,
            status=as_str(get("status")),
            started_at=parse_datetime(get("started_at")),
            finished_at=parse_datetime(get("finished_at")),
            job_count=as_int(get("job_count")),
            trigger_type=as_str(get("trigger_type")),
            error_status=as_str(get("error_status")),
            started_by=login(get("started_by")),
            stopped_by=login(get("stopped_by")),
            raw=raw,
        )


TimeArg = Union[datetime, str, None]


class Tasks:
    """Ресурс ``mp.tasks``: задачи сканирования и история их запусков."""

    def __init__(self, client: Client) -> None:
        self._client = client

    def list(self) -> List[ScanTask]:
        """Все задачи сканирования, доступные учётной записи."""
        data = self._client._get_json(_compat.SCANNER_TASKS)
        return [ScanTask.from_raw(item) for item in _compat.page_items(data)]

    def get(self, task_id: str) -> ScanTask:
        """Задача по идентификатору.

        Raises:
            NotFoundError: Задачи нет или она недоступна учётной записи.
        """
        data = self._client._get_json(_compat.SCANNER_TASK.format(task_id=_segment(task_id)))
        if not isinstance(data, dict):
            raise PtkitError("Неожиданный ответ MaxPatrol на запрос задачи")
        return ScanTask.from_raw(data)

    def runs(
        self,
        task_id: str,
        *,
        time_from: TimeArg = None,
        time_to: TimeArg = None,
        with_errors: Optional[bool] = None,
        page_size: int = _compat.TASK_RUNS_PAGE_SIZE,
    ) -> Iterator[TaskRun]:
        """История запусков задачи; страницы запрашиваются по мере чтения.

        Args:
            time_from: Начало периода (``datetime`` или строка ISO 8601).
            time_to: Конец периода.
            with_errors: Только запуски с ошибками (``True``) или без фильтра.
            page_size: Размер страницы при запросе к серверу.
        """
        if page_size <= 0:
            raise ValueError("page_size должен быть положительным")
        path = _compat.TASK_RUNS.format(task_id=_segment(task_id))
        start, end = _time_param(time_from), _time_param(time_to)
        return self._iter_runs(path, task_id, start, end, with_errors, page_size)

    def _iter_runs(
        self,
        path: str,
        task_id: str,
        time_from: Optional[str],
        time_to: Optional[str],
        with_errors: Optional[bool],
        page_size: int,
    ) -> Iterator[TaskRun]:
        offset = 0
        while True:
            params = _compat.task_runs_params(offset, page_size, time_from, time_to, with_errors)
            data = self._client._get_json(path, params=params)
            items = _compat.page_items(data)
            for item in items:
                yield TaskRun.from_raw(item, task_id)
            offset += len(items)
            total = _compat.page_total(data)
            if len(items) < page_size or (total is not None and offset >= total):
                return


def _segment(value: str) -> str:
    """Идентификатор как сегмент пути: ``/`` и прочие спецсимволы экранируются."""
    if not isinstance(value, str) or not value:
        raise ValueError("Ожидался непустой идентификатор")
    return quote(value, safe="")


def _time_param(value: TimeArg) -> Optional[str]:
    if value is None or isinstance(value, str):
        return value
    return format_datetime(value) + "Z"
