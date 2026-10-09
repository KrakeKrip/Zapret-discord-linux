# Отчёт для review Codex

**TASK:** TASK-003 — Correction 01.
**Статус:** READY_FOR_REVIEW.

## Исправление 1 — строгая проверка ответов helper (client.py)

- `_parse_response` теперь возвращает `(ответ, причина_отказа)` и проверяет полный контракт v1: допустимые коды только `ok, busy, conflict, invalid_request, permission_denied, operation_failed` (константа `HELPER_CODES`); `ok/code` должны быть согласованы (`ok:true` ⇔ code `ok`, `ok:false` ⇔ один из пяти error-кодов) — противоречия и неизвестные коды дают отказ с причиной. `protocol` по-прежнему строго целое 1.
- `_run` принимает явный признак транспорта (`'direct' | 'sudo' | 'pkexec'`) вместо `capture_stderr`. Ответ проводится только при совпадающем коде выхода: `ok:true` + exit 0 — успех; `ok:false` + exit 1 — структурированная ошибка helper. Любое противоречие (в т.ч. `ok:true/code:ok` при exit 1, `ok:true/code:conflict` при exit 0, `ok:false/code:busy` при exit 0) → `transport_error` с «результат операции неизвестен — перечитай состояние»; повтор не выполняется.
- Маппинг 126 → `auth_cancelled` и 127 → `auth_failed` выполняется **только** для транспорта `pkexec`. Root-ветка вызывает helper с транспортом `'direct'` (без захвата stderr): её 126/127 без корректного ответа дают `transport_error`, а не отмену авторизации. sudo-ветка — `'sudo'`. Валидные busy/conflict/error-ответы остались различимыми, поведение pkexec-отмены сохранено.
- Docstring модуля обновлён под контракт. Никаких повторов запроса не появилось (тесты фиксируют один вызов subprocess).

## Исправление 2 — неполный snapshot (core.py)

- `snapshot()` получил поле `revision_error` (null при полном чтении). Если какие-то исходные байты недоступны для сравнения — `revision` равен `None`, а `revision_error` содержит понятный перечень причин («Состояние прочитано не полностью: …» с путями/именами). Непригодны: отсутствующий/непрочитанный conf.env, конфигурация, не прошедшая validate, ошибка чтения known-good.json/previous.json, symlink вместо каталога profiles или именованного файла, объект вместо каталога, ошибка перечисления каталога (теперь перехватывается с сохранением причины — `profiles_error` + `revision_error`), нечитаемый именованный профиль. Существующие `config_error`/`profiles_error`/ошибки отдельных профилей сохранены.
- Повреждённый, но прочитанный JSON именованного профиля по-прежнему даёт валидную revision (байты известны, профиль можно удалить/заменить); отсутствующие legacy-файлы и profiles — нормальный полный snapshot.
- `_admin_locked` при revision-проверке: если `revision is None` — мутация отклоняется plain `RuntimeError` («Мутация отклонена: Состояние прочитано не полностью: …») **до** любых записей и restart; это не ConflictError и не сравнение маркеров ошибки. Через endpoint это даёт `operation_failed`. app.py не менялся — маппинг уже корректный.
- Чтение осталось без root и без записи; real files в тестах не затрагиваются (chmod-исправления — на временных файлах с восстановлением в finally).

## Тесты (8 новых + расширения, всего 109)

Новые в `test_core.py`:
- `test_missing_or_invalid_config_disables_revision` — отсутствие и невалидность conf.env дают `revision=None` + `revision_error`, восстановление возвращает валидную revision;
- `test_unreadable_legacy_file_disables_revision` — по очереди known-good.json и previous.json с chmod 000: точный repro Codex — `config_error=None`, но `revision=None` и ошибка с путём; после восстановления всё валидно;
- `test_unreadable_profile_file_disables_revision`, `test_profiles_listing_error_disables_revision` (патч `Path.iterdir` с PermissionError);
- `test_unusable_snapshot_refuses_mutation_as_operation_error` — под lock мутация со stale revision при нечитаемом known-good отклоняется как RuntimeError (не ConflictError), без записи профиля, без systemctl, conf.env не изменён; после восстановления доступа тот же поток по той же revision выполняется;
- расширены `test_snapshot_reports_corrupt_profiles_without_breaking` (повреждённый JSON сохраняет валидную revision и `revision_error=None`) и `test_profiles_dir_absent_and_symlink_in_snapshot` (symlink каталога → `revision=None`).

Новые в `tests/test_client.py`:
- `test_unclear_output_is_transport_error` расширен репродукциями Codex: `ok:true/code:conflict` + exit 0, `ok:true/code:'future_unknown'`, `ok:false/code:'ok'`, `ok:true/code:ok` + exit 1, `ok:false/code:busy` + exit 0 — все дают `transport_error` с «перечитай»;
- `test_valid_helper_errors_pass_through_with_exit_one` — все пять error-кодов с exit 1 проходят как есть (busy/conflict различимы);
- `test_root_branch_exit_126_127_is_transport_error` — root-ветка с 126/127 без JSON больше не маскируется под отмену авторизации;
- `test_unusable_snapshot_is_operation_failed_not_conflict` (endpoint) — нечитаемый known-good даёт `operation_failed` с «прочитано не полностью», без записи файла.

Все существующие тесты прежних TASK прошли без ослабления утверждений (1 → 1: единственное изменение поведения — новые поля snapshot и более строгий отказ клиента, покрытые новыми тестами).

## Проверено (фактически запущено)

- `python3 -m unittest discover -s tests -v` — **109 тестов, OK** (101 + 8);
- `python3 -m compileall -q src` — OK;
- `bash -n scripts/install.sh scripts/uninstall.sh scripts/setup.sh` — OK;
- `PYTHONPATH=src python3 -m zapret_console --help` — OK;
- `bash scripts/setup.sh --dry-run` — OK;
- `git diff --check`, хвостовые пробелы — чисто;
- DESTDIR: staging install → staged-импорт `app, client, core` → uninstall — OK.

В ходе отладки исправлены два собственных теста: в сценарии отказа мутации baseline revision вычислялся до создания known-good (после восстановления доступа получил бы conflict вместо успеха — переписан), и в тесте отсутствующего conf.env не удалялся сам файл. Также удалена случайная мусорная строка, попавшая при первой правке этого теста.

## Не проверено

Реальные sudo/pkexec/polkit-диалоги (mocked-контракты argv/кодов — по-прежнему системная интеграция отдельным этапом); поведение под root-запуском тестов (chmod-тесты неприменимы для root, предполагается обычный запуск как в CI); длительные timeout-сценарии на реальных сервисных операциях.

## Известные ограничения

- Строгое правило «ok:false только с exit 1» и «ok:true только с exit 0» зафиксировано как контракт v1: будущие версии helper обязаны соблюдать его или поднимать protocol.
- `revision_error` агрегирует причины строкой; машиночитаемого списка причин нет — по формату отчёта достаточно для UI-сообщения.

## Git

- Baseline: HEAD `20ef65f`, как и при основном TASK-003; рабочее дерево содержит изменения TASK-003 + документы Codex (`TASKS.md`, `tasks/TASK-003-correction-01.md`, `reports/TASK-003-review-01.md`) — их не трогал.
- Итог: изменены `src/zapret_console/core.py`, `src/zapret_console/client.py`, `tests/test_core.py`, `tests/test_client.py` (в границах scope; app.py не менялся). Отчёты прошлых итераций не тронуты.
- **Commit и push не выполнялись**, история не менялась, реальная система не затронута.
