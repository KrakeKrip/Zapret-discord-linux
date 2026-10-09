# TASK-006 — Миграция реальной установки и удаление старого движка

Дата: 2026-10-09. Пользователь явно подтвердил удаление стороннего движка после объяснения, что рабочий обход отключится. Исходники своего продукта, settings и профили сохраняются.

## Причина отказа первоначальной установки

Root:root каталог /usr/local/lib/zapret-console имел mode 775. Новый установщик отказал до активации версии; /usr/local/bin/zapret-console остался 0.2.0. Нативные зависимости пользователь установил успешно, включая libxcb-cursor0.

Добавлена строго ограниченная миграция каталога версии 0.2.0: только при root-вызове, root:root владельце, без world write и symlink/current, с проверенными root:root неизменяемыми app.py/__init__.py и маркером версии 0.2.0. Родитель проверяется общим check_path. Убирается group write только у этого каталога; неизвестная/посторонняя установка не исправляется автоматически. Два новых теста проверяют положительный сценарий и отказ для world-writable/неизвестного каталога.

## Подготовленная операция

scripts/remove-legacy-backend.py требует явного --remove-legacy-backend; dry-run немутирующий, обычный пользователь без авторизации отклоняется. Фиксированные пути проверяются на root:root, отсутствие symlink/world write и соответствие unit/старого меню ожидаемому backend.

1. Архивировать /opt/zapret-discord-youtube-linux, unit, zapret-menu и старое состояние меню в root-only /var/backups/zapret-console/legacy-<UTC>.tar.gz.
2. Обновить свой GUI/TUI через исправленный установщик; ошибка оставляет старый движок работать.
3. systemctl stop и disable zapret_discord_youtube.service, с исполнением штатного cleanup firewall.
4. Проверить отсутствие активного сервиса, его nfqws и таблицы inet zapretunix. При остатках удаление файлов отменяется, глобального flush нет.
5. Удалить старый backend, точный unit-файл и zapret-menu; daemon-reload. Свой проект, /etc/zapret-console, /var/lib/zapret-console и старые данные профилей остаются.

Лог привилегированного выполнения: /var/log/zapret-console-migration.log (0600). Новый GUI/TUI после удаления останется без подключённого движка. Собственный новый движок в рамках удаления не создаётся.

## Проверено

- Миграция каталога: 19 install-тестов OK.
- Четыре теста удаления: явный флаг обязателен; dry-run не вызывает system commands/delete; unprivileged отказ; symlink backend отклоняется до мутаций.
- Полный GUI/TUI regression: 199 тестов OK, skipped=1, stderr без Qt/QML ошибок.
- compileall установочных скриптов, dry-run удаления — OK.

## Системное выполнение

Запущена системная авторизация:

```bash
pkexec --disable-internal-agent /usr/bin/python3 -I /home/atlkhnv/Zapret-discord-linux/scripts/remove-legacy-backend.py --remove-legacy-backend
```

Авторизация polkit не завершилась за более 5 минут. Ожидающий pkexec (real uid 1000) остановлен SIGTERM до выполнения скрипта; старый сервис всё ещё active и версия интерфейса 0.2.0. Изменений в /opt и /usr/local не выполнено. Для завершения требуется запуск в пользовательском терминале:

```bash
sudo /usr/bin/python3 -I /home/atlkhnv/Zapret-discord-linux/scripts/remove-legacy-backend.py --remove-legacy-backend
```

В этой команде уже объединены исправленная установка собственного GUI/TUI и подтверждённое удаление старого движка/меню. Ничего ещё не объявляется установленным/удалённым. Пароль агент не получает.
