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
