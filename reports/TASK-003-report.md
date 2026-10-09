# Отчёт для review Codex

**TASK:** TASK-003 — Общий клиент операций и защита от устаревших данных.
**Статус:** READY_FOR_REVIEW.

## Реализовано

**core.py — snapshot и revision.** `snapshot(ctx)` — read-only: конфигурация (или `config` + `config_error`), `service_state`/`autostart` (systemctl is-active/is-enabled, вне revision), профили (список `{name, config, error}`, отсортирован) и непрозрачная `revision` — SHA-256 детерминированного представления: идентичность backend (root/unit) + исходные байты conf.env, known-good.json, previous.json и всех допустимых именованных `<name>.json`. Отсутствие файла/каталога кодируется явно (`absent`), symlink каталога profiles или профиля — маркером без открытия (`symlink`); .lock, временные файлы, mtime и состояние systemd в revision не входят. Каждый файл читается ровно один раз — байты идут и в hash, и в разбор данных (есть тест-счётчик чтений). Повреждённый JSON учитывается байтами в revision и помечается недоступным в данных, не ломая snapshot. Чтение не требует root и не пишет файлов.

**Защита от устаревших данных.** `BusyError`/`ConflictError` — подклассы RuntimeError (старые обработчики работают). В `_admin_locked` после доверенности и до любых записей (profiles, previous.json, conf.env) и до restart пересчитывается revision и сравнивается с `expected_revision`; несовпадение → `ConflictError`, ничего не меняется. Проверка и действие — под одной блокировкой, второго flock внутри dispatch нет. `admin_command` получил параметр `expected_revision`; старый `--admin` (без него) сохраняет прежний контракт. `start/stop/restart/enable/disable` — явно, без toggle, под общим lock; runtime остался lock-free и без revision.

**app.py — машинный endpoint.** Скрытый `--request-json <JSON>`: не совмещается с другими режимами; ответ — ровно один JSON-объект `{protocol, ok, code, message, data}` в stdout, exit 0 только для ok. Коды: ok, busy, conflict, invalid_request, permission_denied, operation_failed. `parse_request` строг: размер ≤ 64 KiB, ровно четыре поля, `protocol` — строго целое 1 (`True` отвергается через `type() is int`), action из фиксированного списка, value — строка только для value-действий и null для остальных, `expected_revision` обязателен (непустая строка) для файловых действий и null для остальных; неизвестные поля/action/типы отклоняются до dispatch. Ошибки чтения settings и любые исключения endpoint дают чистый JSON без traceback; argparse-поведение остальных режимов не тронуто.

**client.py — новый UI-независимый клиент** (без print/input/whiptail, без Qt/Textual, без автоповторов): `snapshot()` — прямое чтение core без root; `make_request()`/`request(body, mode)` — выполнение через установленный launcher. Перед вызовом проверяются наличие, отсутствие symlink и доверенность launcher (реальный `trusted`); отсутствие утилиты — явный transport_error, без fallback на root-python из репозитория. Режим terminal: `sudo -- <launcher> --request-json <JSON>` списком аргументов, stdin/stderr наследуются, stdout захвачен; TTY проверяется явно, без TTY — `auth_failed` без запуска helper. Режим gui: `pkexec --disable-internal-agent <launcher> --request-json <JSON>`, stdin DEVNULL, stdout/stderr захвачены; уже-root вызывает launcher без повышения. Ответ валидируется по структуре (protocol/ok/code/message); 126 без валидного ответа → auth_cancelled, 127 → auth_failed; невалидный stdout, несовместимая версия, ошибка запуска → transport_error; timeout → transport_error с «результат неизвестен, перечитай состояние». DISPLAY нигде не читается. Протокол v1 описан в docstring модуля.

## Изменённые файлы

- `src/zapret_console/core.py` — BusyError/ConflictError, REVISION_ACTIONS, snapshot/_read_file_state/_config_from_bytes/_profile_from_bytes, проверка revision в `_admin_locked`, параметр `admin_command`;
- `src/zapret_console/app.py` — `parse_request`, `request_endpoint`, `_response`, режим `--request-json` в `main()`;
- `src/zapret_console/client.py` — новый клиент (snapshot + terminal/gui транспорт);
- `tests/test_core.py` — +`SnapshotTests` (7) и `RevisionConflictTests` (5);
- `tests/test_client.py` — новый: `ParseRequestTests` (3), `RequestEndpointTests` (6), `ClientTransportTests` (12).

## Тесты (32 новых, всего 101)

Ключевые: воспроизводимость и read-only snapshot; revision меняется при изменении конфигурации/профилей и known-good/previous, игнорирует .lock/временные файлы/перезапись тех же байтов; возврат к идентичным байтам после create+delete даёт ту же revision; повреждённый профиль — байты в revision, пометка в данных; одиночное чтение каждого файла; symlink каталога profiles в snapshot. Конфликт двух клиентов: первый сохраняет по актуальной revision, второй со старой получает ConflictError — без создания файла, без изменения conf.env, без вызова systemctl; restore-good при конфликте не пишет previous.json; совпадающая revision проходит;BusyError/ConflictError — подклассы RuntimeError; сервис-действия без revision. Endpoint: матрица parse_request (включая `protocol: true`, размер 70 KiB, лишние поля), ok/operation_failed, busy под удержанным lock, conflict без изменений, permission_denied, runtime без lock и без ревизии, ошибки settings, ровно один JSON в stdout через настоящий `main()` с SystemExit, отклонение совмещения режимов. Транспорт: точные argv/stdin/stdout/stderr для sudo и pkexec, root без повышения, 126/127 → auth_cancelled/auth_failed, мусор/чужой protocol/не-bool ok → transport_error, timeout с «результат неизвестен» и ровно один вызов, отказ launcher (отсутствует/ссылка/не доверенный — реальный trusted) без запуска, нет TTY → auth_failed, пустой environ без DISPLAY не влияет на sudo-путь, чистый импорт client (забойные subprocess.run/Popen + отсутствие Qt/Textual в sys.modules), `--help` CLI без DISPLAY.

## Проверено (фактически запущено)

- `python3 -m unittest discover -s tests -v` — **101 тест, OK** (69 принятых + 32 новых; поведенческие утверждения прежних сохранены);
- `python3 -m compileall -q src`, `bash -n` трёх скриптов, `PYTHONPATH=src python3 -m zapret_console --help`, `bash scripts/setup.sh --dry-run`, `git diff --check`, хвостовые пробелы — OK;
- **DESTDIR**: install кладёт client.py в staging; staged `--help` и staged-импорт `app, client, core` — OK; uninstall удаляет lib/launcher, оставляя settings и var/lib;
- вручную (немутирующие пробы на реальной системе): `--request-json` не-root → `permission_denied` (одна JSON-строка, exit 1, без traceback); `--request-json 'garbage'` → `invalid_request`; `--request-json '{}' --status` → `invalid_request`; `--status` — прежний человекочитаемый вывод;
- read-only snapshot на реальной системе: service active, revision воспроизводима, config без ошибок, файлы не менялись.

В ходе отладки исправлял собственные тесты: сценарий конфликта изначально не содержал изменения между snapshot и запросом (конфликт корректно не срабатывал — сценарий переписан «первый клиент мутирует, второй со старой revision»); `response` в трёх транспортных тестах использовался до создания; в фикстуре не хватало второй стратегии. В core улучшено сообщение о повреждённом JSON профиля (теперь содержит «повреждён» вместо сырого текста json-парсера); поведение `read_profile` сохранено.

## Сопутствующие изменения

Не требовались: setup.py и diagnostics.py не тронуты, установщик не менялся (launcher передаёт `--request-json` как обычный скрытый аргумент argparse), whiptail-меню по scope не мигрировано на клиент. Файл `reports/TASK-002-report.md` лежал в дереве untracked от прошлой итерации — не трогал.

## Не проверено

Реальные sudo/pkexec-диалоги и polkit-агент (по заданию — mocked-проверки argv/stdin/stdout/exit; системная интеграция отдельных этапом); реальный запуск двух GUI/TUI-процессов (интерфейсов ещё нет; конкуренция покрыта тестами core/endpoint/транспорта); таймаут 120 с подобран без измерений реальных операций; pip-консольный скрипт не исполнялся (только `-m` и staged-путь).

## Известные ограничения

- Для не-файловых действий (start/stop/…/runtime) `expected_revision` строго должен быть null — упрощает протокол, но будущих расширений версий это коснётся через protocol bump.
- Revision не защищает от ручных изменений root в обход lock в момент между проверкой и записью (в пределах одного dispatch под flock окно минимально) — это соответствует заявленной семантике «сравнение содержимого, а не журнал событий».
- Клиент требует установленный launcher; работа из исходников без установки для мутаций не предусмотрена (по решению Codex).

## Git

- Baseline: HEAD `20ef65f` («docs: prepare TASK-003…»), дерево чистое, кроме untracked `reports/TASK-002-report.md` от прошлой итерации (не тронут); TASK-002 принят в `8720081`.
- Итог: изменены `src/zapret_console/app.py`, `src/zapret_console/core.py`, `tests/test_core.py`; новые untracked `src/zapret_console/client.py`, `tests/test_client.py`, `reports/TASK-003-report.md`. Ключевые документы, README, скрипты — не тронуты.
- **Commit и push не выполнялись**, история не менялась, реальная установка/сервис/firewall не затронуты (все пробы — read-only или в temp/mocks).
