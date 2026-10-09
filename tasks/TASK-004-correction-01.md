# TASK-004 — Correction 01

Рабочая папка: `/home/atlkhnv/Zapret-discord-linux`. TASK-004 пока не принят. Полный review — `reports/TASK-004-review-01.md`.

## 1. QML вызывает отсутствующий метод закрытия

Main.qml onClosing вызывает bridge.requestClose(), но BackendBridge имеет только обычный Python request_close(), без экспортированного Slot с таким именем. Воспроизведение Codex: открыть настоящее Main.qml на FakeBackend и вызвать window.close(). Получен QML TypeError `Property 'requestClose' ... is not a function`; окно закрывается, worker продолжает работать. MetaObject.indexOfMethod('requestClose()') == -1.

Исправить контракт: экспортировать используемый QML метод как Slot(result=bool) либо согласовать имя вызова и экспортированный слот. Сам Python-тест request_close() не доказывает wiring QML.

Добавить тест настоящего QML-окна: закрытие во время медленной mocked-мутации отклоняется без TypeError; окно остаётся до результата, повтор не отправляется, системный stop не вызывается. После завершения закрытие безопасно. Проверить idle-close через тот же путь, а не только Python-функцию.

## 2. Завершение worker не учитывает чтение и не гарантировано перед выходом

bridge.request_close проверяет только _busy (мутацию). При snapshot в worker _busy=False: stop() блокирует GUI на wait(5000), игнорирует False, затем возвращается True при ещё работающем QThread. run_gui не выполняет гарантированный cleanup после app.exec; _finish_close просто вызывает quit, не завершив worker. После мутации могут остаться запланированные чтения, а timer продолжает ставить задания при closing.

Воспроизведение Codex: backend.snapshot ждёт threading.Event, вызван refresh и затем request_close(). Через ровно 5 секунд возвращено True, worker.isRunning()==True. Для cleanup в репродукции событие освобождено отдельно; настоящие системные операции не выполнялись.

Исправить lifecycle:
- Учесть все задания (чтения, очередь, мутации), не только _busy. При close перевести мост в closing, остановить таймер и запретить новые refresh/submit/мутации. Закрытие повторно запрошено — не добавлять бесконечные sentinel/новые jobs.
- Не блокировать GUI-поток ожиданием 5 секунд. Дождаться результата текущей работы и фактического завершения worker через signals, сохраняя responsive окно. Не использовать terminate и не убивать helper.
- Quit/разрешение закрытия — только после гарантированного завершения worker. Для уже запущенной мутации сохранить ожидание ограниченного client timeout; не обещать отмену изменений.
- В run_gui обеспечить корректный порядок владения/cleanup для normal exit и ошибки загрузки QML: QML-объекты уничтожаются прежде моста, QThread не уничтожается во время run. Не оставлять idle worker вечным после закрытия.
- Тесты должны очищать engine/bridge в правильном порядке: текущий headless-прогон формально OK, но stderr содержит множество QML `Cannot read property ... of null` при teardown. Это тоже устранить; не подавлять warnings.

Приёмка: тесты закрытия во время медленного snapshot, мутации с запланированным refresh и при простое; timer не добавляет jobs после close, worker реально finished перед quit_callback, event loop остаётся responsive. Использовать события и mocks, не задержки в реальном backend. Прогон GUI-тестов без QML warnings и QThread-destroyed сообщения. stop() может оставаться специальным тестовым cleanup, но production close не должен допускать выход с живым потоком.

## 3. Пустой список и валидация формы сохранения

Main.qml проверяет `bridge.profilesModel.count === 0`, но ProfilesModel не имеет QML count Property (metaObject.indexOfProperty('count') == -1). Поэтому пустое состояние не появляется. Использовать действующий profilesList.count или добавить count Property с корректными уведомлениями; тест перехода пустой -> непустой -> пустой в реальном QML.

SaveDialog имеет always-enabled Dialog.Ok; пустое имя запускает worker и polkit/helper, затем административный слой отвергает имя. Ограничения имени должны проверяться до авторизации: выключить OK при пустом/невалидном вводе и повторно проверить имя в bridge перед отправкой. Условия busy/closing/неполной revision не должны позволять повторную отправку открытым диалогом. Сохранять baseRevision формы, не заменять свежим token.

Добавить QML/UI-тесты пустого/невалидного имени, отмены save/replace/delete: никакого backend.request. Тесты должны инициировать действия/диалоги QML, а не только напрямую вызывать bridge.deleteProfile с заранее данным token.

Убрать пользовательские тексты с внутренними `start/stop/restart`, «файловые операции» и «общий клиент» в пользу понятных «настройки», «ожидание изменения», «для изменения может потребоваться пароль». Не менять дизайн целиком.

## Scope

Только gui/app.py, gui/bridge.py, Main.qml и tests/test_gui.py. Остальную реализацию, CLI/core/client, зависимости и ключевые документы сохранить. Не менять установленную копию, сервис/firewall, не запускать реальные парольные диалоги и не делать commit/push.

## Самопроверка

```bash
python3 -m unittest discover -s tests -q
PYTHONPATH=src QT_QPA_PLATFORM=offscreen QT_QUICK_BACKEND=software .venv/bin/python -m unittest discover -s tests -q
python3 -m compileall -q src
git diff --check
```

Проверить stdout/stderr GUI-прогона: отсутствие QML ошибок не равно только exit 0. Состав пакета не меняется: wheel/shell-checks повторять только если изменятся соответствующие файлы.

Полный отчёт — `reports/TASK-004-correction-01-report.md`: исправления по пунктам, реально выполненные команды, результаты, ограничения, состояние Git. В чат — короткий итог и путь. После отчёта ждать review.
