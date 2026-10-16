"""Активы: поля ``Host`` для построителя, ``Asset`` и ресурс ``mp.assets``."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Iterator, List, Optional, Tuple, Union

from ..errors import NotFoundError
from ..pdql.builder import Query
from ..pdql.fields import DATETIME, IP, LIST, STRING, UUID, Field
from . import _compat
from ._models import RawDict, as_str, parse_datetime

if TYPE_CHECKING:
    from .client import Client

__all__ = ["Host", "Asset", "AssetQuery", "Assets"]


def _host_field(name: str, **kwargs: Any) -> Field:
    return Field(_compat.HOST_FIELDS[name], name, **kwargs)


class Host:
    """Поля узла (актива типа Host) для построителя запросов.

    Поля, которых здесь нет, задаются явно: ``Field("Host.Softs.Name")``.
    """

    id = _host_field("id", kind=UUID)
    name = _host_field("name", kind=STRING)
    os_name = _host_field("os_name", kind=STRING)
    os_version = _host_field("os_version", kind=STRING)
    fqdn = _host_field("fqdn", kind=STRING)
    ip_address = _host_field("ip_address", kind=IP)
    ip_addresses = _host_field("ip_addresses", kind=LIST, item=IP)
    #: Принимает "high", "medium", "low" или код значимости ("H", "M", "L").
    importance = _host_field("importance", kind=STRING, values=_compat.IMPORTANCE_CODES)
    description = _host_field("description", kind=STRING)
    created_at = _host_field("created_at", kind=DATETIME)
    updated_at = _host_field("updated_at", kind=DATETIME)
    audited_at = _host_field("audited_at", kind=DATETIME)


_DEFAULT_FIELDS: Tuple[Field, ...] = tuple(getattr(Host, a) for a in _compat.DEFAULT_HOST_FIELDS)


@dataclass
class Asset:
    """Актив из результата PDQL-запроса.

    Поля, которые не были выбраны в запросе, равны ``None``. Строка результата
    целиком доступна в ``raw``, значение любой колонки — через ``asset[поле]``.
    """

    id: Optional[str]
    name: Optional[str]
    os_name: Optional[str] = None
    os_version: Optional[str] = None
    fqdn: Optional[str] = None
    ip_address: Optional[str] = None
    ip_addresses: Optional[List[Any]] = None
    importance: Optional[str] = None
    description: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    audited_at: Optional[datetime] = None
    raw: RawDict = field(default_factory=dict, repr=False)

    @classmethod
    def from_row(cls, row: RawDict) -> Asset:
        values = _compat.lower_keys(row)

        def col(attr: str) -> Any:
            return values.get(_compat.HOST_FIELDS[attr].lower())

        asset = values.get(_compat.ASSET_COLUMN.lower())
        if isinstance(asset, dict):
            asset_id = as_str(asset.get(_compat.ASSET_COLUMN_ID))
            name = as_str(asset.get(_compat.ASSET_COLUMN_NAME))
        else:
            asset_id, name = None, as_str(asset)
        ip_addresses = col("ip_addresses")
        return cls(
            id=asset_id or as_str(col("id")),
            name=name or as_str(col("name")),
            os_name=as_str(col("os_name")),
            os_version=as_str(col("os_version")),
            fqdn=as_str(col("fqdn")),
            ip_address=as_str(col("ip_address")),
            ip_addresses=ip_addresses if isinstance(ip_addresses, list) else None,
            importance=as_str(col("importance")),
            description=as_str(col("description")),
            created_at=parse_datetime(col("created_at")),
            updated_at=parse_datetime(col("updated_at")),
            audited_at=parse_datetime(col("audited_at")),
            raw=dict(row),
        )

    def __getitem__(self, key: Union[Field, str]) -> Any:
        """Значение колонки по полю или имени колонки, без учёта регистра."""
        name = key.pdql if isinstance(key, Field) else key
        wanted = name.lower()
        for column, value in self.raw.items():
            if column.lower() == wanted:
                return value
        raise KeyError(name)


class AssetQuery(Query):
    """Запрос активов: построитель PDQL, привязанный к клиенту.

    Запрос выполняется при итерации; каждая итерация — новый запрос к серверу.
    Если ``select()`` не вызван, выбираются поля по умолчанию (ОС, FQDN, IP,
    значимость, время создания и обновления).
    """

    base_select = (_compat.ASSET_COLUMN,)

    def __init__(self, client: Optional[Client] = None) -> None:
        super().__init__()
        self._client = client
        self._group_ids: Tuple[str, ...] = ()

    def in_group(self, group_id: str) -> AssetQuery:
        """Ограничить запрос группой активов (вложенные группы входят)."""
        if not isinstance(group_id, str) or not group_id:
            raise ValueError("in_group() ожидает идентификатор группы")
        query = self._copy()
        query._group_ids = self._group_ids + (group_id,)
        return query

    def rows(self) -> Iterator[RawDict]:
        """Выполнить запрос и вернуть строки как словари, без разбора в ``Asset``."""
        if self._client is None:
            raise RuntimeError("Запрос не привязан к клиенту: создайте его через mp.assets.query()")
        return self._client._pdql_rows(self.to_pdql(), group_ids=self._group_ids)

    def __iter__(self) -> Iterator[Asset]:
        for row in self.rows():
            yield Asset.from_row(row)

    def _selected_fields(self) -> Tuple[Field, ...]:
        return self._select or _DEFAULT_FIELDS


class Assets:
    """Ресурс ``mp.assets``: запросы к активам и чтение актива по идентификатору."""

    def __init__(self, client: Client) -> None:
        self._client = client

    def query(self) -> AssetQuery:
        """Новый запрос активов для построителя."""
        return AssetQuery(self._client)

    def get(self, asset_id: str) -> Asset:
        """Актив по идентификатору.

        Raises:
            ValueError: Идентификатор не в формате UUID.
            NotFoundError: Актива нет или он недоступен учётной записи.
        """
        query = self.query().filter(Host.id == asset_id).select(*_DEFAULT_FIELDS, Host.id).limit(1)
        wanted = asset_id.lower()
        for asset in query:
            if asset.id is not None and asset.id.lower() == wanted:
                return asset
        raise NotFoundError(f"Актив {asset_id} не найден")
