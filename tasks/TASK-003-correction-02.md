# TASK-003 — Correction 02

Рабочая папка: `/home/atlkhnv/Zapret-discord-linux`. Correction 01 закрыт по diff и проверкам Codex; оба его исправления сохранить. Перед приёмкой требуется одно локальное исправление в client.py.

## Проблема

В `_parse_response` выполняется `data['code'] not in HELPER_CODES` без проверки типа code. HELPER_CODES — frozenset: ответ с `code: []` или `code: {}` вызывает TypeError (unhashable type). Исключение выходит из _run/request, вместо обещанного transport_error; будущий UI может потерять обработку результата операции.

Codex воспроизвёл оба случая с подменой subprocess.run: stdout — JSON `{protocol:1, ok:false, code:[] (или {}), message:'', data:null}`, exit 1. Получен TypeError, а не структурированный отказ.

## Исправление и приёмка

- Перед проверкой membership явно проверять, что code — строка. Не менять согласованность ok/code/exit и различение pkexec/direct/sudo.
- Добавить матрицу недопустимых типов code: массив, объект, null, число и bool. На уровне публичного client.request каждый случай возвращает transport_error с указанием неизвестного результата/необходимости обновить данные, без исключения и без повтора subprocess.
- Корректные ok и все пять helper-error-кодов по-прежнему принимаются только с согласованным exit code.
- Не маскировать проблему общим `except Exception` вокруг всей операции: проверять схему до использования значений.

## Scope

Только client.py и tests/test_client.py. Остальную реализацию, документы Codex и предыдущие отчёты сохранить. Не делать commit/push, системные изменения или реальные парольные диалоги.

## Проверки и отчёт

Запустить `python3 -m unittest discover -s tests -q`, `python3 -m compileall -q src`, `git diff --check`. Изменения локальные: повторная staging-установка и проверки неизменённых shell-скриптов не требуются.

Полный отчёт сохранить в `reports/TASK-003-correction-02-report.md`; в чат — READY_FOR_REVIEW/BLOCKED, краткий итог, результат проверок и абсолютный путь отчёта.
