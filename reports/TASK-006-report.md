# TASK-006 — Установка GUI/TUI: отчёт Codex

Дата: 2026-10-09. Baseline: 4ddc6cc. Версия: 0.3.0 (локально, без GitHub release/push).

**Статус:** реализация и staging-проверки завершены. Обновление настоящей системы ожидает ввода sudo пользователем. Агент не изменял `/usr/local`, APT или настоящий адаптер.

## Реализовано

- scripts/install.py и shell wrappers: полный пакет core/client, GUI, QML и Textual; два desktop-ярлыка и собственная SVG-иконка. GUI entry Terminal=false, TUI entry Terminal=true; рабочая команда остаётся zapret-console.
- all (по умолчанию), tui без Qt и none для CLI/whiptail. Мастер setup передаёт выбранный режим, проверяет venv, pkexec/polkit и нативные Qt/XCB/EGL библиотеки через APT.
- UI-зависимости берутся из точных pins pyproject.toml через безопасный literal parser, без дублирования версий. Pip работает в отдельном venv, в изолированном режиме; системные Python пакеты не меняются.
- Выпуск под releases/<id> создаётся по окончательному пути. venv после создания не переносится. После импорта зависимостей, проверки CLI и публикации артефактов current атомарно переключается на новый выпуск; launcher --version проверяется ещё раз. При ошибке возвращаются предыдущие current, launcher, settings и ярлыки, новый выпуск удаляется.
- Старые выпуски сохраняются для уже открытых клиентов. Это увеличивает расход диска; автоматическая очистка не добавлялась. Uninstall удаляет выпуски/launcher/ярлыки/иконку, оставляет settings, state и inode установочной блокировки.
- Отдельный flock сериализует install/uninstall. Ссылки вместо путей/файлов, current вне releases, чужая запись и неподходящий root-владелец отклоняются. Root-owned sticky ancestor /tmp допускает безопасный staging.
- Launcher root-helper использует системный Python -I, проверяет весь пакет и родителей до импорта; root не импортирует окружение UI. Обычный UI через exec запускает фиксированный venv/python -I и bootstrap. Скриптовый CLI работает без UI зависимостей. PYTHONPATH/PYTHONHOME не подменяют код.
- Существующая установка 0.2.0 поддерживается. settings без изменения root/unit сохраняются байт-в-байт даже при явной передаче тех же параметров; дополнительные поля сохраняются при смене root/unit. Обновление интерфейса не пишет conf.env и не вызывает start/stop/restart существующего сервиса.
- Desktop identity и иконка окна подключены через QGuiApplication.

## Найденная и исправленная ошибка GUI

При настоящем app.exec окно после завершения QThread продолжало отвергать событие закрытия: QCoreApplication.quit мог быть отменён Qt, и процесс оставался работать. Старые тесты с подменённым quit callback этого не проверяли.

requestClose теперь разрешает окончательный close event после _close_finished. До завершения worker закрытие по-прежнему отклоняется, новые задачи запрещены, сервис не останавливается. Новый subprocess-тест запускает настоящее окно и app.exec для простоя и операции в полёте: нормальный код 0 вместо fallback 73, worker завершён, запросов ровно ожидаемое количество, stderr чистый.

## Фактические проверки

- Полная среда Python 3.14.4, PySide6 6.12.0 и Textual 8.2.8: **193 unittest OK, skipped=1** (тест отсутствия установленного PySide6). stderr только итог unittest; нет QML, QThread, TypeError или binding-loop предупреждений.
- Базовая среда без UI: **193 OK, skipped=47**.
- 17 новых установочных тестов: содержимое/QML/TUI/права/ярлыки, staged CLI, custom settings/profiles, сохранение старого выпуска, ошибки зависимостей и публикации с rollback, первый сбой, busy lock обоих действий, symlink родителей/файлов/current, writable destination, uninstall, переход с legacy дерева, exact pins, изоляция окружения, проверка root helper импортируемого writable модуля, сохранение settings байт-в-байт и дополнительных полей.
- Три теста APT dependencies: минимальный tui, недостающие нативные зависимости и отсутствие вызова APT при установленном наборе.
- Один новый GUI тест с двумя настоящими app.exec сценариями.
- Настоящие install и upgrade в `/tmp/zapret-task006-runtime` с `--with-deps`: отдельный venv создан установщиком, PySide6/Textual скачаны/установлены, импорт QtQml и CLI выполнены. До uninstall были сохранены оба выпуска, без перемещения venv. Источники, root settings и адаптер не заменялись.
- Launcher staging --version/--help работают; --status --json прочитал реальный активный сервис, enp9s0 и general_alt11.bat. Немутирующий --request-json runtime обычным пользователем вернул ожидаемый permission_denied (exit 1), без авторизации.
- Установленный TUI запущен настоящим launcher в PTY и закрыт Ctrl+Q с exit 0; никаких операций управления не отправлялось.
- GUI из установленного дерева запущен в настоящей Wayland сессии с реальным read-only backend: окно 1040×720, screenshot просмотрен, штатное закрытие exit 0. Проверены обычный renderer и software renderer. Qt выдал две platform-подсказки о portal app ID/textinput в окружении запуска Codex; QML/worker ошибок нет. Это не headless fixture и не установка ярлыков в настоящее меню.
- Повторный staged install и uninstall shell wrappers завершились успешно; tmp runtime удалён через новый uninstall, настройки/state staging сохранены. Настоящий сервис после проверок active, стратегия general_alt11.bat; SHA-256 настоящего conf.env — 33bfea91ebadef9117c93a2f3de54bbd3ba340969791e1824d0c4009f6838ae4.
- compileall src/scripts/launcher, bash -n всех shell scripts, --help/--version, setup --dry-run (all и tui), desktop-file-validate обоих ярлыков, git diff --check — OK. Wheel со всеми QML/TUI ресурсами проверен полным unittest.
- CI дополнен full GUI/TUI regression и установкой настоящих зависимостей в staging. Удалённый CI не запускался, push не выполнялся.

## Остался системный шаг

sudo -n true вернул «interactive authentication is required». Для применения готовой версии пользователь выполняет в своём терминале:

```bash
sudo bash /home/atlkhnv/Zapret-discord-linux/scripts/setup.sh --yes
```

Мастер обнаружит существующий адаптер и обновит приложение, сохранив сервис и подключение. После этого нужно проверить настоящий launcher 0.3.0, владельцев installed code/venv, появление ярлыков и GUI/TUI из /usr/local. Реальный polkit/sudo пароль и привилегированные действия в этой задаче не выполнялись; автоматический рабочий обход/голос не утверждается.

## Артефакты и Git

Снимок: TASK-006-installed-gui.png. Он содержит read-only состояние настоящего сервиса, снят из staged release.

Подготовлен локальный commit, без push. Существовавший reports/TASK-002-report.md не изменялся и не включается.

## Источники контрактов

- [Python venv: непереносимость окружений](https://docs.python.org/3/library/venv.html)
- [Desktop Entry Specification](https://specifications.freedesktop.org/desktop-entry/latest-single/)
- [Qt Linux Requirements](https://doc.qt.io/qt-6/linux-requirements.html)
- [QCoreApplication.quit: окно может отменить завершение](https://doc.qt.io/qt-6/qcoreapplication.html#quit)
