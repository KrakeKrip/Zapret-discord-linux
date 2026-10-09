# Отчёт для review Codex

**TASK:** TASK-004D — Реализация дизайна GUI Codex.
**Статус:** READY_FOR_REVIEW.

## Реализовано

**Визуальная система** (`Theme.qml` переписан по токенам SPEC): background #0d1318, sidebar/input #10191f, card #162129, secondary #1d2b34, border #293943, text/muted, accent #73e2c2 (+hover #8bebd0, press #59cdae), active nav #213731, active strategy #182c28, chip #1c302e, warning #f0bd72, danger #ee9191, цвета диалогов. Радиусы: карточки 14, кнопки/поля 9. Без внешних шрифтов/CDN/emoji.

**Новые QML-компоненты** (в `gui/qml/`, попадают в package data по существующему glob, wheel-тест проверяет):
- `GuiIcon.qml` — локальные линейные иконки (home, folder, tune, power, search, check) на Canvas, 24-сетка, линия 1.8, цвет — свойство;
- `AppButton.qml` — кнопки primary (мятная заливка, тёмный текст; hover #8bebd0, press #59cdae), secondary (графит+бордер, hover на ступень), danger (secondary с красным текстом); disabled приглушены; явная контрастная рамка фокуса с отступом 2 px; ColorAnimation 120 мс.

**Main.qml полностью переработан по макетам** (сохранены все objectNames и вызовы существующего bridge):
- sidebar 208 px (184 при <960) с Z-знаком, меткой «УПРАВЛЕНИЕ», тремя разделами с иконками, активным состоянием (#213731 + акцентная полоса) и подсказкой;
- header: заголовок 26 px + подзаголовок раздела + «Обновить»; разделитель; footer: цветной индикатор + последнее событие (elide + tooltip) слева, статус сервиса справа нейтральным цветом;
- «Главная»: карточка статуса (иконка power, «СОСТОЯНИЕ СЕРВИСА», статус 27 px, chip «Запущен/Остановлен/Неизвестно», примечание о том, что доступность Discord проверяется отдельно, Остановить/Запустить primary, Перезапустить secondary), ниже карточки «Текущая настройка» (интерфейс, стратегия, «Выбрать стратегию» → переключение вкладки без мутации) и «Автозапуск» (chip + явные enable/disable); при ширине <960 карточки ставятся вертикально, контент прокручивается;
- «Профили»: «Профилей: N», primary «Сохранить текущую настройку», карточки (имя, стратегия · интерфейс, Восстановить справа, Заменить/Удалить снизу — Удалить красным текстом), повреждённый профиль: warning-бордер, chip «Повреждён», причина, Восстановить disabled, заменить/удалить доступны; пустое состояние с иконкой, «Пока нет профилей» и ровно одной primary-кнопкой; warning-плашка при `revision=None`;
- «Стратегии»: поиск (иконка внутри поля), отдельная карточка текущей стратегии (акцентный фон, check; chip «Не установлена» при отсутствии в списке), список с «Применить» и chip «Текущая» (текущая строка не отправляет повторное применение), состояния «Ничего не найдено…»/«Установленные стратегии не найдены», поиск не прячет карточку текущей;
- диалоги сохранения/замены/удаления и сообщений: панель #18232c, radius 16, ширина min(456, window−48), фокус на безопасной «Отмене», для удаления — «Удалить профиль», правила имени в подсказке, Escape/Enter по стандарту Dialog; предупреждение при revision=None блокирует файловые действия; сервисные команды следуют прежнему контракту;
- busy/closing: оверлей с индикатором, «Ожидание изменения настроек…»/«Завершаем текущую операцию…»; первое чтение — «Читаем состояние…» без фиктивных данных.

**bridge.py — только read-only свойства отображения** (+79 строк): `loading`, `eventTone` (цвет индикатора footer: accent/ok/warn/error/muted), `strategyInstalled`, `serviceChip`; тексты состояний из SPEC («Сервис работает»/«Сервис остановлен»/«Состояние неизвестно»), «Настройки прочитаны.» после чтения, «Состояние прочитано не полностью.» (warn) при revision=None, конфликт — «Настройки изменились в другом окне. Обновите данные и повторите действие.» Транспорт, worker lifecycle, generation, валидация, захваченная revision, busy/closing — не переписывались.

## Изменённые файлы

- `src/zapret_console/gui/qml/Theme.qml` — токены дизайна;
- `src/zapret_console/gui/qml/GuiIcon.qml`, `AppButton.qml` — новые компоненты;
- `src/zapret_console/gui/qml/Main.qml` — компоновка по макетам (три экрана, диалоги, узкий режим, objectNames сохранены + новые: sidebar, navMain/navStrategies, selectStrategyButton, currentStrategyCard, strategySearch, saveCurrentButton/saveCurrentEmptyButton);
- `src/zapret_console/gui/bridge.py` — read-only свойства и тексты;
- `tests/test_gui.py` — обновлены текстовые утверждения; новые проверки;
- `reports/TASK-004D-preview/*.png` — 11 снимков.

## Тесты (146 → 140 не менялось по числу принятых: 140, из них +4 новых, 4 обновлены)

Новые: `test_strategy_not_installed_is_reported` (стратегия вне списка → предупреждение); `test_select_strategy_button_switches_tab_without_mutation` (переход вкладки без единого запроса); `test_search_does_not_hide_current_strategy_card` (фильтр опустошает список, карточка текущей видна); `test_narrow_window_uses_narrow_sidebar` (800 px → sidebar 184, 1040 → 208, минимум окна 800); в `test_refresh_applies...` — loading/eventTone/strategyInstalled. Обновлены текстовые ожидания («Сервис работает», «Состояние неизвестно», конфликт «Настройки изменились»). Все проверки Correction 01 (закрытие через window.close при мутации/чтении/простое, count, invalid-name до auth, отмены, захваченная revision, поколения, отсутствие автоповторов) остались и проходят; Qt warnings не подавляются — тесты требуют их отсутствия.

## Проверено (фактически запущено)

- Базовая среда: `python3 -m unittest discover -s tests -q` — **140 OK (skipped=27)**; `python3 -m compileall -q src` — OK; `git diff --check` — OK; `bash -n`, `--help`, `setup --dry-run` — OK (CLI/скрипты не менялись);
- venv (PySide6 6.12.0, offscreen+software): `PYTHONPATH=src ... .venv/bin/python -m unittest discover -s tests -q` — **140 OK (skipped=1)**; **stderr прогона проверен по маске** `cannot read property|QThread|of null|TypeError|binding loop|Unable to assign|ReferenceError|Syntax error` — 0 совпадений;
- wheel: PackageDataTests собирает wheel и проверяет все runtime-QML ресурсы (Main, Theme, GuiIcon, AppButton, qmldir) — OK;
- **снимки (headless, FakeBackend — не реальные данные)**: `reports/TASK-004D-preview/`: main-1040, main-800, main-unknown, main-busy, profiles-1040, profiles-empty, profiles-warning, strategies-1040, strategies-800, strategies-search-empty, save-dialog. Все просмотрены: обрезаний, перекрытий и горизонтального переполнения нет; карточки содержат кнопки; узкий режим — вертикальная укладка и прокрутка; скриншоты сняты на FakeBackend;
- реальная графическая сессия (Wayland/:0): окно запускалось read-only (только чтение snapshot) и закрывалось корректно; мутации и парольные диалоги не выполнялись.

В ходе реализации исправлено по собственным строгим проверкам: «Detected anchors on an item managed by a layout» (Card-обёртки), «Binding loop implicitWidth» диалогов (явная ширина 456/460), дубли `spacing`, неверные `parent.*` биндинги в NavButton, отсутствие `iconName`, лишний `component DialogFooter`, скобочный дисбаланс после реструктуризации — всё покрыто тестом предупреждений QML.

## Отклонения от макета (с причинами)

- Абсолютные координаты SVG заменены на Layout/implicitHeight по указанию SPEC; отступы сохранены в логике (sidebar 208/184, поля 24–28, разделители).
- Шрифт — системный sans-serif (DejaVu в снимках) вместо отрисованного в SVG, по SPEC.
- Footer-индикатор после успешного чтения — «Настройки прочитаны.» (в макете — снимок состояния); при revision=None — «Состояние прочитано не полностью.» с warning-индикатором.

## Не проверено

Реальные polkit-диалоги и системные мутации; физические мышь/клавиатура (Tab/Enter/Esc реализованы стандартом Controls + явный фокус, но живых нажатий не было); HiDPI-физический экран; другие темы Qt/окружения. Снимки — FakeBackend/headless, что указано и в их названии каталога и здесь.

## Известные ограничения

- `loading`/`eventTone`/`strategyInstalled`/`serviceChip` — новые read-only свойства моста, разрешённые TASK; приёмка «новых backend-полей» не потребовалось.
- Диалоги используют Qt Quick Controls (не нативные) — как и в базовой реализации TASK-004.

## Git

- Baseline: HEAD `c5d0881` («docs: define GUI design and TASK-004D»); дерево было чистым, кроме untracked `reports/TASK-002-report.md` (не тронут).
- Итог: изменены `gui/qml/Main.qml`, `gui/qml/Theme.qml`, `gui/bridge.py` (только display-свойства), `tests/test_gui.py`; новые `gui/qml/GuiIcon.qml`, `gui/qml/AppButton.qml`, `reports/TASK-004D-preview/*.png` (11), `reports/TASK-004D-report.md`. app.py (CLI), core, client, installer, README, ключевые документы и design/gui-v1 — не менялись.
- **Commit и push не выполнялись**, история не менялась, реальная система не затронута.
