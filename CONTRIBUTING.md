# Разработка Zapret Manager

Начните с [HANDOFF.md](HANDOFF.md) и [AGENTS.md](AGENTS.md). Требуется Python 3.10+; для полного GUI-прогона используйте Python 3.14, как в release CI. Основной интерфейс — PySide6/QML, терминальный — whiptail. Textual в проекте больше нет.

## Окружение и проверки

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[gui]' build
QT_QPA_PLATFORM=offscreen QT_QUICK_BACKEND=software .venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m compileall -q src scripts packaging/launcher.py
bash -n scripts/install.sh scripts/uninstall.sh scripts/setup.sh
PYTHONPATH=src .venv/bin/python -m zapret_console --help
bash scripts/setup.sh --dry-run
git diff --check
```

Без графических зависимостей установите `-e .`: обычные unittest работают без Qt, GUI-тесты будут пропущены. Полный результат нельзя подменять прогоном с пропусками. QML package data проверяется сборкой wheel и загрузкой без предупреждений.

Тесты подменяют системные операции и используют временные каталоги. Не меняйте настоящий сервис/firewall ради unit-тестов. Проверка реальной сети и голоса Discord выполняется отдельно с разрешённой настройкой сервиса.

## Запуск и установка

```bash
PYTHONPATH=src .venv/bin/python -m zapret_console --gui
PYTHONPATH=src python3 -m zapret_console
```

GUI требует графической сессии; меню — TTY и whiptail. Системные действия используют установленный root launcher и sudo/pkexec. Не запускайте GUI целиком под sudo.

```bash
DESTDIR=/tmp/zapret-stage bash scripts/install.sh
/tmp/zapret-stage/usr/local/bin/zapret-console --help
DESTDIR=/tmp/zapret-stage bash scripts/uninstall.sh
```

DESTDIR по умолчанию не загружает зависимости. `--with-deps` включает настоящий GUI-runtime в staging. Для обновления только интерфейса на host: `sudo bash scripts/install.sh`. `setup.sh` может установить сторонний движок; это другая операция.

## Сборка и выпуск

```bash
.venv/bin/python scripts/build-release.py
```

Результат в dist/: wheel, sdist, zapret-manager-<version>-linux.tar.gz с полным Git-снимком проекта и SHA256SUMS. Версии pyproject.toml и __init__.py должны совпасть. Полный архив создаётся из Git HEAD; сначала commit, затем сборка. В архив не входят .venv, локальные изменения, ключи и untracked-файлы. Wheel предназначен для Python-разработчиков; системный launcher и установщики берутся из полного архива.

После явного разрешения публикации:

```bash
git push origin main
git tag -a v0.3.2 -m 'Zapret Manager 0.3.2'
git push origin v0.3.2
```

Для следующего выпуска используйте его номер; существующие теги не перемещайте. `.github/workflows/release.yml` проверяет совпадение тега и версии, запускает полный headless regression и сборку, публикует GHCR и Release через GITHUB_TOKEN. Packages содержит OCI-образ с файлами в /packages; приложение на host устанавливается из release-архива. Образ не запускает GUI, systemd или nfqws. При первой публикации видимость GHCR по умолчанию private; владелец может сделать пакет public в настройках Packages.

Проверяйте Actions и фактические ссылки на assets/package после публикации. Не сообщайте об успешном релизе только по результату git push.

## Изменения и отчёты

Обновляйте README, ARCHITECTURE, PRODUCT, DECISIONS и HANDOFF при изменении поведения. Указывайте в reports/ что изменено, команды и реальные результаты, а также что не проверялось. В чат выводите короткий итог. Не переписывайте исторические отчёты под новое поведение.

В issue укажите ОС, версию, шаги, ожидаемый результат и `zapret-console --doctor`. Диагностические отчёты могут содержать локальные адреса: не включайте приватные данные, ключи или токены в commit.
