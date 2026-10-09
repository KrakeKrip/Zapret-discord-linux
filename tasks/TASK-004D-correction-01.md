# TASK-004D — Correction 01

Рабочая папка: /home/atlkhnv/Zapret-discord-linux. TASK-004D НЕ ПРИНЯТ. Читать reports/TASK-004D-review-01.md, исходный TASK-004D и design/gui-v1/SPEC.md. Baseline HEAD c5d0881, реализация в текущем diff; сохранить её и чужой reports/TASK-002-report.md.

## 1. Восстановить UI-guards (блокирующая регрессия)

При выделении AppButton исчезли условия enabled. Вернуть условия в QML по назначению действия, не глобально выключая навигацию и отмену диалогов:
- start/stop/restart/enable/disable: !busy && !closing;
- saveCurrentButton/saveCurrentEmptyButton, заменить/удалить в карточках: !busy && !closing && canMutateFiles;
- restore: эти же условия + !damaged; apply: эти же условия + !current;
- Accept всех файловых диалогов: !busy && !closing && canMutateFiles, имя при save остаётся валидным;
- навигация, поиск, скролл и безопасная отмена остаются доступны согласно SPEC; не позволять кликами создавать запросы после closing.

Не подменять baseRevision свежей при poll и не менять transport/core. Когда форму открыли при валидной revision, затем пришла revision=None, confirm должен стать disabled и не отправить backend.request. Когда пришла другая валидная revision, старый token остаётся старым — conflict, без повтора.

Добавить настоящие QML-тесты доступности/кликов при revision=None, busy и closing. Проверять все названные действия, а не только restore. FakeBackend: попытки недоступных save/replace/delete не создают запрос/авторизацию. Сервисные операции с revision=None остаются доступны, когда не busy/closing. Не включать в реальные тесты pkexec.

## 2. Исправить визуальную реализацию

- AppButton измеряет тот же шрифт/вес/размер, которым рисует текст. Корректные implicitWidth/padding, высота интерактивной области >=40. Не фиксировать width под конкретную строку. Надпись сохранения должна помещаться целиком на 1040 и 800 либо область должна корректно перестраиваться.
- AppTextField placeholderTextColor=Theme.muted; согласованная читаемость и фокус.
- Dialog: полноценные отступы около 28 px, контент и header в одной тёмной теме, без дефолтной белой полосы messageDialog. Сохранение: поле получает фокус; справа primary «Сохранить», слева «Отмена». Replace/delete: безопасная отмена default/focus, справа действие; удаления primary-destructive в подтверждении согласно SPEC. Не зависеть от неожиданного platform-order DialogButtonBox. Диалоги закрываются Escape; Enter не подтверждает disabled action. Без binding loop.
- NavButton: видимая keyboard focus рамка независимо от checked/hover. При необходимости проверить реальными синтетическими Tab/Enter/Esc через QtTest на FakeBackend.
- Нижние карточки главной: верхние границы согласованы, на широком окне текущая настройка шире автозапуска (ориентир 480/268 для доступных 768 с gap20), на узком — одна колонка. Все кнопки достигаются вертикальным скроллом.
- Длинное имя профиля (48 символов), длинная установленная стратегия и damaged/error: строки реально ограничены доступной шириной, elide+tooltip или перенос; узкий верхний ряд не выталкивает restore за край — переносить/перестраивать. Вторичные подписи/empty-состояния и header также не переполняют окно.

## 3. Сохранить результат операции в footer

_on_snapshot_ready сейчас безусловно затирает результат на «Настройки прочитаны.». Вернуть разделение событий чтения и результата: первая загрузка и явное ручное обновление могут показывать сообщение чтения; автоматический poll/refresh после результата не стирают result lastEvent/eventTone. Переход к реальной ошибке/неполноте чтения отображается честно, без ложного success. auth_cancelled — нейтральное/спокойное уведомление, не красная ошибка. busy/conflict — предупреждение; auth_failed/operation_failed/transport_error — ошибка. Не менять сигнатуры запроса, generation guards, lock или порядок shutdown.

Тесты: success, conflict и auth_cancelled/operation_failed сохраняются в footer после post-operation refresh и последующего poll, запрос отправлен ровно один раз. Проверить явный ручной refresh и реальную read error. Документировать правила приоритетов событий, если нужен маленький display-only флаг в bridge.

## 4. Проверки и достоверные снимки

Независимый unittest Codex: 140 OK, но stderr содержит два `DelegateModel::cancel: index out range 1 0`. Найти воспроизводящий сценарий, устранить корректным lifecycle/model updating; не подавлять сообщения и не ограничиваться regex из отчёта или engine.warnings, который не ловит все предупреждения Qt. Если доказан дефект самого Qt без разумного исправления в scope, вернуть минимальный repro и blocker, не объявлять stderr чистым.

Снимки strategies-1040/800 сняты до отрисовки строк. Собственный screenshot Codex после ожидания показывает их корректно: ListView count=3, height=355, contentHeight=188. Поэтому не переписывать работающий список вслепую. Capture должен ждать данные, layout и готовый кадр; проверять не только count, но ненулевую геометрию и реальное наличие строк на изображении.

Сохранить обновлённые FakeBackend-снимки трёх экранов на 1040×720 И 800×560, диалогов save/replace/delete/message, пустого/warning/unknown/busy и длинных имён. Для главной в узком режиме дополнительно скролл вниз с видимыми автозапуском и всеми кнопками. Просмотреть изображения, нельзя заявлять «нет обрезаний», когда надпись видимо обрезана. Снимки не являются проверкой реальной системы.

## Scope / отчёт

Только текущие QML-компоненты, при необходимости display-only флаги/события bridge.py, tests/test_gui.py и отчёт/снимки. Core/client/CLI/installer/dependencies, дизайн и ключевые документы не менять. Не делать commit/push, системные мутации и реальные авторизации.

```bash
python3 -m unittest discover -s tests -q
PYTHONPATH=src QT_QPA_PLATFORM=offscreen QT_QUICK_BACKEND=software .venv/bin/python -m unittest discover -s tests -q
python3 -m compileall -q src
git diff --check
```

Полностью проверить stderr. Все существующие 140 тестов сохраняются; дополнительные — существенные сценарии выше. Полный отчёт: reports/TASK-004D-correction-01-report.md. В чат максимум 5–7 строк: статус, итог, проверки и абсолютный путь отчёта. Ждать review Codex.
