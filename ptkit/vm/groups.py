"""Группы активов: ``Group`` и ресурс ``mp.groups``."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Iterator, List, Optional

from ..errors import NotFoundError, PtkitError
from . import _compat
from ._models import RawDict, as_bool, as_str

if TYPE_CHECKING:
    from .client import Client

__all__ = ["Group", "Groups"]


@dataclass
class Group:
    """Группа активов.

    ``raw`` — исходный объект группы из ответа, включая вложенные группы.
    """

    id: str
    name: Optional[str]
    type: Optional[str] = None
    tree_path: Optional[str] = None
    is_root: bool = False
    is_read_only: bool = False
    is_removable: bool = False
    parent_id: Optional[str] = None
    children: List[Group] = field(default_factory=list, repr=False)
    raw: RawDict = field(default_factory=dict, repr=False)

    @classmethod
    def from_raw(cls, raw: RawDict, parent_id: Optional[str] = None) -> Group:
        f = _compat.GROUP_FIELDS
        group_id = as_str(_compat.pick(raw, f, "id"))
        if not group_id:
            raise PtkitError("В ответе MaxPatrol группа без идентификатора")
        group = cls(
            id=group_id,
            name=as_str(_compat.pick(raw, f, "name")),
            type=as_str(_compat.pick(raw, f, "type")),
            tree_path=as_str(_compat.pick(raw, f, "tree_path")),
            is_root=as_bool(_compat.pick(raw, f, "is_root")),
            is_read_only=as_bool(_compat.pick(raw, f, "is_read_only")),
            is_removable=as_bool(_compat.pick(raw, f, "is_removable")),
            parent_id=parent_id,
            raw=raw,
        )
        children = raw.get(_compat.GROUP_CHILDREN)
        if isinstance(children, list):
            group.children = [cls.from_raw(c, group_id) for c in children if isinstance(c, dict)]
        return group

    def walk(self) -> Iterator[Group]:
        """Эта группа и все вложенные, в глубину."""
        yield self
        for child in self.children:
            yield from child.walk()


class Groups:
    """Ресурс ``mp.groups``: дерево групп активов."""

    def __init__(self, client: Client) -> None:
        self._client = client

    def tree(self) -> List[Group]:
        """Корневые группы; вложенные доступны через ``children``."""
        data: Any = self._client._get_json(_compat.GROUPS_HIERARCHY)
        items = data if isinstance(data, list) else [data] if isinstance(data, dict) else []
        return [Group.from_raw(item) for item in items if isinstance(item, dict)]

    def list(self) -> List[Group]:
        """Все группы плоским списком, в порядке обхода дерева в глубину."""
        return [group for root in self.tree() for group in root.walk()]

    def get(self, group_id: str) -> Group:
        """Группа по идентификатору, с вложенными группами.

        Raises:
            NotFoundError: Группы нет или она недоступна учётной записи.
        """
        wanted = group_id.lower()
        for group in self.list():
            if group.id.lower() == wanted:
                return group
        raise NotFoundError(f"Группа {group_id} не найдена")
