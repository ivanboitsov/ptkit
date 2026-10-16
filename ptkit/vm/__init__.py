"""MaxPatrol VM: клиент, поля для построителя запросов и объекты ответа.

Пример::

    from ptkit.vm import Client, Host

    with Client("https://mp.example.local", token="...") as mp:
        for host in mp.assets.query().filter(Host.os_name.contains("Windows")).limit(10):
            print(host.name, host.os_name)
"""

from ..pdql.fields import Field
from ._models import Ref
from .assets import Asset, AssetQuery, Host
from .client import Client
from .groups import Group
from .tasks import ScanTask, TaskRun

__all__ = [
    "Client",
    "Host",
    "Field",
    "Asset",
    "AssetQuery",
    "Group",
    "ScanTask",
    "TaskRun",
    "Ref",
]
