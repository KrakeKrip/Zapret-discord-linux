# TASK-009 — Публикация 0.3.2 и продолжение с другого устройства

Дата: 2026-10-09. Пользователь явно разрешил push, версию в GitHub Packages и обновление документов для агентов/разработчиков.

## Подготовлено

- README: версия 0.3.2, установка из release-архива, явное разделение интерфейса и nfqws, обновление только интерфейса через install.sh, GitHub Packages и ссылки на инструкции продолжения.
- AGENTS.md, HANDOFF.md: начало работы на новом устройстве, режим Codex без GLM, текущая архитектура, история удаления Textual, границы root-операций, фактическое состояние прежней машины и непроверенные сценарии.
- CONTRIBUTING, ARCHITECTURE, PRODUCT, DECISIONS, CHANGELOG, TASKS приведены к действующей версии. Исторические отчёты не переписаны; чужой untracked reports/TASK-002-report.md не включён.
- scripts/build-release.py проверяет обе версии и отсутствие tracked diff, экспортирует Git HEAD, собирает wheel/sdist из чистой временной копии, формирует Linux source archive и SHA256SUMS. Не использует старый local build/lib.
- release.yml на version tag: проверка тега, полный GUI regression, сборка, versioned GHCR distribution image, GitHub Release с файлами. GITHUB_TOKEN используется внутри Actions; локальные токены не нужны для SSH push.
- packaging/Dockerfile содержит только /packages с файлами выпуска. GitHub Packages не поддерживает PyPI; GHCR служит для распространения файлов, не для запуска GUI/systemd/nfqws в контейнере. Полный архив устанавливается на Linux host.

## Проверки до commit и публикации

208 unittest OK, skipped=1; stdout/stderr сохранены в /tmp/zapret-publish-tests.*. compileall, bash -n, Python 3.10 syntax, git diff --check, YAML parsing двух workflows — OK. SSH ls-remote подтверждает доступ и отсутствие тега v0.3.2; origin/main ещё у версии 0.2.0. gh локально не авторизован. Текущий репозиторий public.

## Статус

Сборка из финального Git HEAD и фактический push/tag/Actions/Release/Packages ещё предстоят. По результату добавить запись с фактическими ссылками и ограничениями. Видимость нового GHCR package по умолчанию может быть private и меняется владельцем в Packages settings. Чистая установка движка на отдельной ОС и доступность Discord не подтверждены выпуском.


## Чистый CI и версия 0.3.3

main и v0.3.2 успешно отправлены через SSH. GitHub Checks и Release остановились на transport-тестах: class ClientTransportTests проверял реальный /usr/local/bin/zapret-console, случайно существовавший на предыдущем host. Файлы выпуска и Package 0.3.2 не опубликованы. API полных логов требует авторизации, поэтому добавлен scripts/check-tests.py с failure details в публичных check annotations; по ним причина независимо подтверждена.

Тестовый fixture теперь создаёт свой временный launcher и подменяет только client.LAUNCHER; production проверки наличия/ссылок/доверенности не ослаблялись. Локальные 208 тестов снова прошли. Версия исправленного выпуска 0.3.3; v0.3.2 не перемещается. README/HANDOFF/CONTRIBUTING/AGENTS согласованы с новым номером. Сборка 0.3.2 локально прошла: SHA256, отсутствие Textual в wheel, QML, полный архив с документами, install/uninstall из архива в DESTDIR. Docker build на host недоступен по правам сокета, выполняется Actions.


Второй чистый прогон f41e6c6: Python 3.12/3.14 и desktop OK, Python 3.10 нашёл историческое ожидание Textual в wheel-тесте. Локальный старый build/lib маскировал его. PackageDataTests теперь собирает wheel из отдельной чистой копии src/metadata и явно отвергает /tui/. GUI CI/Release и инструкции dev устанавливают setuptools/wheel, чтобы упаковочный тест не пропускался в новых Python. Исторические build/ не использованы в реальной сборке выпуска. 208 тестов снова OK в GUI-venv.


## Финальный результат

- Исходники отправлены в main через SSH. Выпуск v0.3.3 создан из 3db21c5; v0.3.2 остался неудачной исторической попыткой, тег не перемещался.
- Чистый Checks: Python 3.10, 3.12, 3.14 и desktop/staging — success. https://github.com/KrakeKrip/Zapret-discord-linux/actions/runs/37974235385
- Checks тега: success. https://github.com/KrakeKrip/Zapret-discord-linux/actions/runs/37974413562
- Release workflow, включая полный regression, build, GHCR push и создание release: success. https://github.com/KrakeKrip/Zapret-discord-linux/actions/runs/37974413582
- Release https://github.com/KrakeKrip/Zapret-discord-linux/releases/tag/v0.3.3 содержит SHA256SUMS, zapret-manager-0.3.3-linux.tar.gz, zapret_console-0.3.3-py3-none-any.whl и zapret_console-0.3.3.tar.gz. Три файла реально скачаны без авторизации и SHA-256 совпали с опубликованным SHA256SUMS.
- Package ghcr.io/krakekrip/zapret-manager:0.3.3 реально доступен anonymous pull. Registry API подтвердил manifest, version=0.3.3 и source=https://github.com/KrakeKrip/Zapret-discord-linux. Digest sha256:a799f6f5573d9838942546efe5a693cd62f74ae9356a8e00748b4d0da7f2ec62. Дополнительной настройки public владельцем не потребовалось.
- Локальная итоговая сборка 0.3.3 успешна, checksums и отсутствие Textual проверены. Локальный полный regression — 208 OK, skipped=1. Правки fixture и wheel-теста затронули только тесты/CI; production transport security не ослаблена.
- HANDOFF/TASKS обновлены фактическими итогами. Финальный docs-only commit отправляется с [skip ci], поскольку код совпадает с уже проверенным опубликованным тегом.

Непроверенные сценарии: реальное восстановление движка после последней команды владельца, сетевой обход/голос Discord, установка движка на чистой ОС, визуальное состояние названий в работающем GNOME. Локальная установленная версия не обновлялась этим выпуском. Чужой reports/TASK-002-report.md остаётся untracked и сохранён.
