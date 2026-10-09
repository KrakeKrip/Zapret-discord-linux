# TASK-003 — Review Codex 01

Результат: не принят, требуются исправления по `tasks/TASK-003-correction-01.md`. HEAD `20ef65f`; implementation commit отсутствует.

## Независимо проверено Codex

- Изучены git status/diff/stat/staged diff, новый client.py, tests/test_client.py, изменения tests/test_core.py и отчёт GLM.
- `python3 -m unittest discover -s tests -v`: 101 тест OK.
- compileall, bash -n трёх скриптов, CLI --help, setup --dry-run, git diff --check: успешно.
- Staging install/import app+core+client/uninstall: успешно, settings сохранены.
- Общая блокировка, сравнение revision до dispatch, неизменность legacy CLI, отсутствие UI-зависимостей и автоматических повторов подтверждены по diff и тестам.

## Находки

1. client._run принимает ok:true/code:conflict, неизвестный code и ok:true/code:ok при exit 1. Все три случая воспроизведены с подменой subprocess.run; результат ошибочно передаётся как успешный. Также 126/127 распознаются по capture_stderr, который используется не только для pkexec, но и при прямом root-запуске.
2. Непрочитанный known-good.json хешируется без отображения ошибки: воспроизведён snapshot с config_error=None, profiles_error=None и строковой revision при status error legacy-файла. Неполный snapshot должен явно обозначать невозможность безопасного сравнения; детали решения и тестов закреплены в correction TASK.

Реальные sudo/pkexec-диалоги, GUI/TUI и системные мутации Codex не проверял. Прохождение 101 теста не закрывает найденные сценарии. Код вместо GLM не исправлялся; commit/push не выполнялись.
