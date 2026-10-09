# Отчёт для review Codex

**TASK:** TASK-003 — Correction 02.
**Статус:** READY_FOR_REVIEW.

## Исправление

В `_parse_response` (client.py) к проверке типов добавлена строковость `code` (`isinstance(data['code'], str)`) **до** membership-проверки `data['code'] not in HELPER_CODES`. Теперь `code: []`, `{}` (unhashable), `null`, число и bool дают структурированный отказ `transport_error` с «результат операции неизвестен — перечитай состояние», а не TypeError из frozenset-проверки. Сообщение об отказе схемы — «некорректные поля ok/code/message».

Не тронуто (по требованиям correction): согласованность ok/code/exit из Correction 01 (`ok:true`+`code:'ok'`+exit 0, `ok:false`+error-код+exit 1), различение транспортов direct/sudo/pkexec для 126/127, отсутствие автоповтора. Общего `except Exception` вокруг операции нет — схема проверяется до использования значений; TypeError больше невозможен, потому что unhashable-значения отсекаются isinstance-проверкой.

## Тесты

`test_wrong_typed_code_is_transport_error_without_exception` (tests/test_client.py): матрица `code` = `[]`, `{}`, `None`, `5`, `True` — для каждого на уровне публичного `client.request(..., mode='terminal')` с подменой subprocess.run (exit 1, stdout с этим code):
- результат `transport_error`, `ok:false`, сообщение содержит «перечитай»;
- `run_mock.assert_called_once()` — без повтора subprocess.

Существующие проверки контракта остались: `test_terminal_mode_uses_fixed_sudo_argv_once` (валидный ok + exit 0), `test_valid_helper_errors_pass_through_with_exit_one` (все пять helper-error-кодов только с exit 1), `test_unclear_output_is_transport_error` (противоречия ok/code/exit), auth-маппинг pkexec и root-ветки — без изменений.

## Проверено (фактически запущено)

- `python3 -m unittest discover -s tests -q` — **110 тестов, OK** (109 + 1 новый);
- `python3 -m compileall -q src` — OK;
- `git diff --check` — чисто;
- прямой repro из correction (все пять недопустимых типов `code` через подмену subprocess.run) — каждый возвращает `transport_error`, исключений нет.

Staging-установка и bash -n не повторялись — изменения локальные в Python-модуле и тестах, как указано в correction (shell-скрипты и состав модулей не менялись).

## Не проверено

Реальные sudo/pkexec-диалоги — по-прежнему вне scope (mocked-контракты).

## Известные ограничения

Нет. Изменение полностью локально в `_parse_response`; контракт протокола v1 не менялся.

## Git

- Baseline: HEAD `20ef65f`; рабочее дерево содержит изменения TASK-003, Correction 01, документы Codex (`TASKS.md`, `tasks/TASK-003-correction-0*.md`, `reports/TASK-003-review-0*.md`) — все сохранены, из них в этой итерации менялись только `src/zapret_console/client.py` и `tests/test_client.py`.
- **Commit и push не выполнялись**, история не менялась, реальная система не затронута.
