# TASK-004B — отчёт Codex

Статус: ЗАВЕРШЁН. Baseline 85219bd. Самостоятельная разработка по указанию пользователя; режим сохранён в TASKS.md до явного возврата к Codex + GLM.

## Результат

В QML добавлены законченные разделы «Диагностика» и «Журнал», сохранены адаптивность, тема, фокус и навигация. Проверки запускаются вручную, результаты читаются/выделяются/копируются. По умолчанию без авторизации; расширенное чтение runtime — явный checkbox через существующий client/helper/runtime. Отмена сохраняет предыдущий отчёт и нейтральный статус, без автоматического повтора. Журнал показывает подсказки доступа даже при exit 0; ограничения и ошибки не превращаются в сообщение о полном доступе.

Общий diagnostics.collect_diagnostics содержит страницу Discord, API, WebSocket, маршрут, снимки сервиса/nfqws/firewall/NFQUEUE до и после проверки, различает успех сети и доказательство участия zapret. GUI/client и CLI используют эту же функцию. CLI продолжает сохранять diagnostics.txt. gateway_probe перенесён в общий модуль, app сохраняет совместимый wrapper. Общий journal_snapshot используется GUI и прежним меню (100 и 60 записей соответственно), фиксирует unit, ограничивает лимит, использует argv без shell и timeout 15 секунд. Report/log — PlainText, не HTML.

GUI использует существующий worker и signals, inspection busy исключает локальные повторные чтения/мутации, прогресс отображается в footer. Навигация остаётся доступна. Closing останавливает приём заданий и дожидается QThread.finished; не останавливает сервис и не прерывает helper. Старый завершённый результат явно помечен и остаётся видимым при новом чтении/ошибке.

Дополнительно устранены неверные выводы runtime при отсутствующих systemctl/нечитаемых proc и недоступном iptables после отсутствия nft-таблицы: остаётся unknown. Интерфейсы с обычными именами туннелей дают предупреждение об отсутствии подтверждения zapret даже при configured_interface=any; это эвристика имени интерфейса, не полное определение всех VPN. Графические сетевые результаты не объявляют успех голоса/трансляции или обхода через обычное подключение.

## Проверки

- Qt venv: 160 unittest OK, skipped=1. Stderr содержит только итог unittest — без QML/DelegateModel/binding loop/TypeError/QThread warnings.
- Базовая среда: 160 OK, skipped=37 — опциональные Qt-сценарии.
- 14 новых тестов: общий pipeline/частичные сетевые ошибки/VPN+any/unknown tools/unknown permissions/default no auth/auth cancellation/fixed journal+hint/limit validation, worker/duplicate/mutation exclusion, close during inspection, сохранение отчёта при auth_cancelled, реальные кнопки двух страниц/PlainText/clipboard/узкая геометрия.
- Все прежние проверки проходят, включая CAS/поколения/формы/window.close и wheel с QML-ресурсами.
- compileall, bash -n, CLI --help, setup --dry-run, git diff --check — OK.
- Четыре снимка новых разделов 1040×720 и 800×560 сохранены в reports/TASK-004B-preview/, данные FakeBackend. Диагностика двух размеров и журнал узкого окна просмотрены; custom checkbox после правки просмотрен повторно.
- Реальная система, только обычное read-only чтение: journal_snapshot успешен; runtime — service=active, engine=running, firewall/queue=unknown. Журнал не публиковался; сеть/авторизация/мутации не запускались.

## Ограничения

Сетевая часть и polkit проверены через mocks; физическая мышь/HiDPI и реальная расширенная авторизация не проверены. Пробы используют обычное подключение, без Discord-аккаунта. Никаких обещаний поддержки голоса/трансляции из HTTP-успеха. Старый системный launcher и installed GUI не обновлялись; desktop/системная установка остаются TASK-006. Textual — TASK-005.

## Git

Изменения: diagnostics.py, client.py, app.py (CLI-адаптация общего чтения), gui/bridge.py, Main.qml/GuiIcon.qml, test_gui.py, новый test_inspections.py, документация/задача/снимки. Core, helper-схема, installer, зависимости и сервис/firewall не изменены. Локальный commit TASK-004B, push не выполняется. Несвязанный reports/TASK-002-report.md сохранён вне commit.
