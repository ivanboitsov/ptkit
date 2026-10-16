# Changelog

Формат — [Keep a Changelog](https://keepachangelog.com/ru/1.1.0/),
версии — [Semantic Versioning](https://semver.org/lang/ru/).

## [Unreleased]

## [0.1.0] - 2026-10-14

Первая версия: чтение данных MaxPatrol VM. Написана по справке MaxPatrol VM 2.7,
на живом сервере ещё не проверялась.

### Added

- `ptkit.vm.Client`: подключение по токену доступа из PT MC или по логину и паролю
  сервисной учётной записи; `from_env()`, `from_config()`, `version()`.
- `Client.pdql()`: выполнение сырого PDQL-запроса с постраничной ленивой выгрузкой строк.
- Построитель PDQL-запросов: `select`, `filter`, `sort`, `limit`, `in_group`, `to_pdql`;
  поля `Host` и условия с экранированием значений.
- Ресурсы только для чтения: `mp.assets` (`query`, `get`), `mp.groups` (`list`, `tree`, `get`),
  `mp.tasks` (`list`, `get`, `runs`).
- Иерархия исключений от `PtkitError`; журнал в логгер `ptkit` без токенов и паролей.
- Unit-тесты на ответах, собранных по справке 2.7; живые тесты в `tests/live`.

[Unreleased]: https://github.com/ivanboitsov/ptkit/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/ivanboitsov/ptkit/releases/tag/v0.1.0
