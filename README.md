# ptkit

ptkit — неофициальная Python-библиотека для работы с API продуктов Positive Technologies.
Первая цель — MaxPatrol VM: подключение, выполнение PDQL-запросов, построитель запросов и
чтение активов, групп и задач сканирования. Только чтение.

ptkit не связан с Positive Technologies. Проектная документация лежит в
[docs/design.md](docs/design.md), решения по API — в [docs/adr/](docs/adr/).

> **Статус 0.1.0:** библиотека написана по справке MaxPatrol VM 2.7 и протестирована на
> ответах, собранных по этой справке. На живом сервере она ещё не проверялась. Часть
> функций использует недокументированные эндпоинты веб-интерфейса
> ([ADR 0001](docs/adr/0001-api-sources.md)). Перед использованием в работе
> прогоните `pytest tests/live`.

## Установка

Python 3.9+, единственная зависимость — `requests`.

```bash
pip install .            # из каталога репозитория
pip install -e ".[dev]"  # для разработки: pytest, ruff, mypy
```

## Подключение

Используйте сервисную учётную запись MaxPatrol с правами только на чтение.

**Токен доступа** — основной способ. Администратор выпускает токен для сервисной
учётной записи в интерфейсе PT MC и задаёт срок его действия, например год. Клиент
передаёт токен в каждом запросе и срок не проверяет: после отзыва или истечения
токена запросы завершатся ошибкой `AuthError`.

```python
from ptkit.vm import Client

with Client("https://mp.example.local", token="<токен>", verify="/etc/ssl/corp-ca.pem") as mp:
    print(mp.version())
```

**Вход по логину и паролю** — запасной способ, если в инсталляции нельзя выпустить
долгоживущий токен. Клиент сам получает токен в PT MC (`<адрес>:3334/connect/token`) и
запрашивает новый, когда истекает срок действия старого. Для этого интеграции нужны пароль
сервисной учётной записи и `client_secret` — ключ приложения `mpx`, общий для всего ядра.
Его выдаёт администратор MaxPatrol:

```bash
sudo grep ClientSecret /var/lib/deployer/role_instances/core*/params.yaml
```

```python
mp = Client(
    "https://mp.example.local",
    username="svc-ptkit",
    password="...",
    client_secret="...",
    verify="/etc/ssl/corp-ca.pem",
)
```

Неверный пароль даёт одну попытку входа, без повторов, чтобы не приближать блокировку
учётной записи.

**Переменные окружения и файл настроек:**

```python
mp = Client.from_env(verify="/etc/ssl/corp-ca.pem")
# PTKIT_URL + PTKIT_TOKEN или PTKIT_USERNAME / PTKIT_PASSWORD / PTKIT_CLIENT_SECRET

mp = Client.from_config("ptkit.toml")
```

```toml
# ptkit.toml (chmod 600)
url = "https://mp.example.local"
username = "svc-ptkit"
password = "..."
client_secret = "..."
verify = "/etc/ssl/corp-ca.pem"
timeout = 30
```

Параметры клиента: `verify` (по умолчанию `True`; строка — путь к корневому сертификату),
`timeout` (30 с), `retries` (3 повтора при сетевой ошибке и 5xx), `backoff` (1 с, удваивается),
`auth_url` (сервер авторизации, по умолчанию тот же хост, порт 3334).

## PDQL

Сырой запрос возвращает ленивый итератор словарей. Запрос уходит на сервер при чтении
первой строки, строки загружаются страницами по 1000.

```python
for row in mp.pdql("select(@Host, Host.OsName) | limit(100)", group_id="<id группы>"):
    print(row["@Host"]["name"], row["Host.OsName"])
```

Построитель собирает тот же запрос из типизированных полей:

```python
from ptkit.vm import Host

query = (
    mp.assets.query()
    .select(Host.id, Host.name, Host.os_name)
    .filter(Host.os_name.contains("Windows") & (Host.importance == "high"))
    .sort(Host.name)
    .limit(500)
)
print(query.to_pdql())
# filter(Host.OsName like '%Windows%' and Host.@Importance = 'H')
#   | select(@Host, Host.@Id, Host.@Name, Host.OsName) | sort(Host.@Name ASC) | limit(500)

for host in query:          # объекты Asset
    print(host.id, host.name, host.os_name)
```

| Метод | Что делает |
| --- | --- |
| `select(*fields)` | Колонки. Без `select` выбираются ОС, FQDN, IP, значимость, время создания и обновления |
| `filter(condition)` | Отбор; несколько вызовов объединяются через «и» |
| `sort(field, desc=False)` | Сортировка; поле добавляется в `select`, если его там нет |
| `limit(n)` | Ограничение числа строк |
| `in_group(group_id)` | Только активы группы (вложенные группы входят) |
| `to_pdql()` | Строка PDQL без выполнения |
| `rows()` | Выполнить и вернуть словари вместо `Asset` |

Условия: `==`, `!=`, `<`, `<=`, `>`, `>=`, объединение через `&`, `|`, `~`. Методы полей:

- `contains(x)`: для строки — подстрока (`like '%x%'`), для списка — элемент (`contains`);
- `startswith(x)`, `like(pattern)`, `match(regex)`;
- `in_([...])`, для IP-поля — подсеть: `Host.ip_address.in_("10.0.0.0/8")`.

Поля `Host`: `id`, `name`, `os_name`, `os_version`, `fqdn`, `ip_address`, `ip_addresses`,
`importance` (`"high"`/`"medium"`/`"low"` или `"H"`/`"M"`/`"L"`), `description`,
`created_at`, `updated_at`, `audited_at`. Любое другое поле модели задаётся явно:
`Field("Host.Softs.Name")`. Значение колонки читается через `asset[поле]`.

Значения всегда экранируются. Для полей UUID, IP и даты значение проверяется по типу.
Строку с обоими видами кавычек или с управляющими символами построитель отклонит
(`ValueError`): записать её в PDQL безопасно нельзя.

## Ресурсы

| Ресурс | Методы | Возвращает |
| --- | --- | --- |
| `mp.assets` | `query()`, `get(asset_id)` | `Asset` |
| `mp.groups` | `list()`, `tree()`, `get(group_id)` | `Group` |
| `mp.tasks` | `list()`, `get(task_id)`, `runs(task_id, time_from=, time_to=, with_errors=)` | `ScanTask`, `TaskRun` |

```python
asset = mp.assets.get("1685ce7c-e440-0001-0000-000000000011")
for group in mp.groups.list():
    print(group.tree_path, group.type)
for run in mp.tasks.runs("<id задачи>"):
    print(run.started_at, run.status, run.started_by)
print(asset.raw)   # исходный ответ сервера, включая поля, которых нет в классе
```

## Ошибки и журнал

Все исключения наследуются от `ptkit.PtkitError` (`message`, `status_code`, `path`):
`AuthError` (401/403, неверный логин или пароль), `NotFoundError` (404),
`PDQLError` (сервер отклонил запрос), `TimeoutError`, `ServerError` (5xx после повторов),
`UnsupportedVersionError`.

Журнал пишется в логгер `ptkit`. На уровне `DEBUG` в него попадают метод, путь, код
ответа, время и размер ответа. Токен, пароль и `client_secret` не попадают ни в журнал,
ни в исключения, ни в `repr`.

## Совместимость

API MaxPatrol меняется вместе с продуктом. Всё, что зависит от версии (адреса, имена
полей, форматы ответов), собрано в [ptkit/vm/_compat.py](ptkit/vm/_compat.py).
При первом запросе клиент узнаёт версию сервера. Если версия не проверялась с этой
версией ptkit, он пишет предупреждение в журнал и продолжает работу.

| ptkit | Написан по справке | Проверен на сервере |
| --- | --- | --- |
| 0.1 | MaxPatrol VM 2.7 | ещё нет |

## Разработка

```bash
pytest tests/unit            # без сервера
pytest tests/live            # нужен MaxPatrol: PTKIT_URL + учётные данные, PTKIT_VERIFY
ruff check . && mypy ptkit
```

Ответы API для тестов лежат в [tests/fixtures/](tests/fixtures/). Перед добавлением
очищайте их от реальных имён, адресов и идентификаторов. Лицензия — MIT.
