# Отчёт для review Codex

**TASK:** TASK-004 — Correction 01.
**Статус:** READY_FOR_REVIEW.

## Исправление 1 — QML вызывает отсутствующий метод закрытия

`request_close()` переименован в `requestClose` и экспортирован как `@Slot(result=bool)` — имя совпадает с вызовом в `Main.qml onClosing`. Каскад «of null»/TypeError устранён (см. пункт 2 и тесты).

Новые тесты настоящего окна (`QmlWindowTests`, реальный Main.qml + FakeBackend):
- `test_window_close_during_slow_mutation_waits_without_errors` — `window.close()` (настоящий путь onClosing) во время мутации, удержанной `threading.Event`: нет TypeError/предупреждений QML, окно остаётся видимым, `closing=True`, запрос «в полёте» ровно один, повтора нет; после освобождения события — `quit_calls == [1]`, worker реально завершён (`isRunning() == False`), системный stop вне пользовательского действия не отправлялся;
- `test_idle_close_via_window_close_quits_after_worker_finished` — idle-close через тот же путь `window.close()`; повторный close не дублирует quit.

## Исправление 2 — lifecycle завершения worker

- `requestClose()`: закрытие идемпотентно — останавливает таймер (новые refresh после close невозможны), запрещает `refresh()`/`_run_operation()` (guard `self._closing`), ставит sentinel worker'у **ровно один раз** (`OperationWorker.begin_shutdown()`, флаг `_shutdown_requested`), возвращает False. Повторный запрос не добавляет sentinel/jobs.
- Никаких блокирующих ожиданий в GUI-потоке: `stop()` остался только тестовым cleanup; production-путь — сигнал `QThread.finished` → `_on_worker_finished()` → quit-колбэк. Для уже идущей мутации сохраняется ограниченное ожидание client timeout; отмена не обещается; диалоги во время closing подавляются, `lastEvent` фиксирует результат.
- Quit происходит исключительно из `_on_worker_finished` (флаг `_close_finished` против двойного вызова) — worker гарантированно завершён.
- `run_gui`: после `app.exec()` QML-объекты уничтожаются раньше моста (`del engine` → `bridge.stop()`); путь ошибки загрузки QML не оставляет запущенного worker (start() не вызывался).
- Тесты закрытия при: медленной мутации (gate + замер, что `requestClose` не блокирует GUI-поток — дедлайн 2 с), медленном snapshot (результат применяется, затем quit), простое; таймер неактивен после close; `refresh()` не создаёт заданий; повторные операции отклоняются. Воркер не остаётся вечным после закрытия.

## Исправление 3 — count, валидация формы и тексты

- `ProfilesModel`/`StrategiesModel`: экспортировано свойство `count` (Property + `countChanged`, эмит в `set_rows`).
- SaveDialog: `standardButtons` заменён на кастомный футер `DialogButtonBox` — «Сохранить» активно только при непустом валидном вводе (`length > 0 && acceptableInput`) и при `!busy && !closing && canMutateFiles`; мост повторно валидирует имя по `core.PROFILE_NAME` до отправки (без авторизации/helper), некорректное имя — сообщение с правилами; baseRevision диалога не подменяется.
- Пустое состояние: Label получил `visible`-binding и `objectName: "profilesEmptyLabel"`; навигационная кнопка «Профили» — `objectName: "navProfiles"`; диалоги и кнопки получили objectNames для UI-тестов.
- Тексты без внутреннего жаргона: «Настройки применяются сразу; закрытие окна не останавливает сервис.», «Для изменения настроек может потребоваться пароль — подтверждение в системном окне.», «Изменение профилей сейчас недоступно: …», «Ожидание изменения настроек; повторные действия заблокированы.»
- Попутно устранён реальный QML warning «Binding loop … implicitWidth» у диалогов замены/удаления (явная `width: 460`, Label по `parent.width`) — его поймал строгий тест предупреждений.

## Тесты

`tests/test_gui.py`: 18 → 27 тестов (+9): в `BridgeTests` — закрытие при мутации (не блокирует GUI-поток, таймер остановлен, новые операции/refresh отклонены, quit после реального завершения worker), закрытие при чтении snapshot (результат применяется, затем quit), валидация имени `saveProfile` до launcher (5 некорректных имён — ни одного запроса, сообщение; валидное — проходит). Новые `QmlWindowTests` (5) — см. пункт 1/3: close во время мутации и idle-close через настоящий `window.close()`, переходы пустое→непустое→пустое с проверкой видимости пустого состояния в настоящем QML, блокировка пустого/невалидного имени в диалоге (кнопка неактивна, клик не отправляет ничего), отмена replace/delete не отправляет ничего, подтверждение через QML уходит с базовой revision диалога. `FakeBackend` получил gate-события (`snapshot_gate`/`request_gate`) вместо sleep-задержек; запрос фиксируется как отправленный до блокировки; все gate освобождаются в `finally`.

Порядок teardown исправлен по всей иерархии: `bridge.stop()` → синхронное удаление engine (`del engine`; `deleteLater()` вне работающего цикла событий не выполнялся и оставлял QML до выхода процесса — источник каскада «of null» и SIGABRT) → processEvents.

## Проверено (фактически запущено)

- `PYTHONPATH=src QT_QPA_PLATFORM=offscreen QT_QUICK_BACKEND=software .venv/bin/python -m unittest discover -s tests -q` — **136 тестов, OK (skipped=1)**; три прогона подряд rc=0 (проверка стабильности/гонок);
- **stderr venv-прогона проверен отдельно**: 0 строк «Cannot read property … of null», 0 QThread-сообщений, 0 binding loop, 0 TypeError (по маске `cannot read property|QThread|of null|TypeError|binding loop`);
- базовая среда: `python3 -m unittest discover -s tests -q` — OK (skipped=23: PySide-тесты пропущены явно, CLI/wheel-тесты выполнены);
- `python3 -m compileall -q src`, `bash -n` трёх скриптов, `PYTHONPATH=src python3 -m zapret_console --help`, `bash scripts/setup.sh --dry-run`, `git diff --check` — OK;
- окно перезапущено в графической сессии (Wayland, :0) в режиме чтения: 1040×720, обновлённый скриншот `reports/TASK-004-preview.png` (новые тексты, пустой футер после чтения).

## Сопутствующие изменения

- `Theme.qml`, `README.md`, `CONTRIBUTING.md`, `pyproject.toml`, установщик — не менялись (в границах scope). app.py не менялся.
- Попутное исправление в Main.qml вне трёх пунктов: binding loop implicitWidth у двух диалогов — оставлять задокументированный QML-warning было нельзя по требованию «прогон без QML warnings»; изменение минимальное (явная ширина диалогов).

## Не проверено

Реальные polkit-диалоги и мутации на живой системе (по-прежнему вне TASK); интерактивная мышь/клавиатура (Tab/Enter/Esc проверены лишь частично — фокус задан в QML, реальных нажатий не было); HiDPI-экран.

## Известные ограничения

- `requestClose()` теперь всегда возвращает False (закрытие разрешается асинхронно после `worker.finished`): окно на мгновение показывает состояние закрытия даже на idle — осознанный трейдофф контракта «quit только после завершения worker».
- Сообщение о некорректном имени при закрытом окне подавляется (как и все диалоги в фазе closing), но фиксируется в `lastEvent`.

## Git

- Baseline: HEAD `685a775`; рабочее дерево содержит изменения TASK-004, correction-документ и review Codex — сохранены; отчёты прошлых итераций не тронуты.
- Итог итерации: изменены `src/zapret_console/gui/bridge.py`, `src/zapret_console/gui/app.py`, `src/zapret_console/gui/qml/Main.qml`, `tests/test_gui.py`; обновлён `reports/TASK-004-preview.png`. app.py (CLI), core/client, установщик, ключевые документы — без изменений.
- **Commit и push не выполнялись**, история не менялась, реальная система не затронута.
