# TASK-004 — Review Codex 01

Результат: не принят; подготовлен `tasks/TASK-004-correction-01.md`. Baseline HEAD 685a775, implementation commit отсутствует.

## Независимо проверено

- Изучены status/stat/diff, новые gui/*.py, Main.qml, GUI-тесты и отчёт GLM. Скриншот просмотрен: главное окно показывает состояние, интерфейс и стратегию, соответствует тёмной палитре и размеру.
- Базовый unittest: 128 тестов OK, skipped=15.
- Venv PySide6 headless: 128 тестов OK, skipped=1. В stderr появились QML ошибки обращения к null bridge при teardown; считать это чистым GUI-прогоном нельзя.
- compileall, bash -n, CLI --help, setup --dry-run, diff --check: успешно. Wheel/package-data проверка прошла в GUI-прогоне.

## Подтверждённые проблемы

1. Настоящий window.close вызывает отсутствующий QML method bridge.requestClose. MetaObject не содержит slot, QML выдаёт TypeError, окно закрывается с ещё работающим worker. Существующий тест проверяет только Python request_close, не wiring окна.
2. Закрытие во время чтения snapshot (Event в FakeBackend) блокирует вызывающий поток 5 секунд, возвращает True при worker.isRunning()==True. Код не гарантирует завершения потока и корректного уничтожения QML перед bridge.
3. ProfilesModel не экспортирует count, используемый для пустого состояния. SaveDialog разрешает пустой ввод до privileged request; UI-тестов самих подтверждений/отмен QML нет. Локальные требования и сценарии закреплены в correction.

## Не проверено

Реальные мутации, password dialog, мышь/клавиатура физической сессии и HiDPI не проверялись. Репродукции выполнялись headless на FakeBackend; worker вручную безопасно завершён после репродукции. Код вместо GLM не исправлялся, commit/push не выполнялись.
