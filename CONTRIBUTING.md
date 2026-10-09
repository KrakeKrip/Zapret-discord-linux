# Разработка

Нужен Python 3.10 или новее. У тестов нет сторонних зависимостей:

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q src
bash -n scripts/install.sh scripts/uninstall.sh scripts/setup.sh
PYTHONPATH=src python3 -m zapret_console --help
```

Тесты используют временные каталоги и подменяют системные операции; они не меняют настоящий сервис и правила сети. Проверяйте UI в обычном терминале. Системные действия доступны после установки 0.3.0 в `/usr/local`. Установочные тесты используют DESTDIR и не изменяют host.

## GUI (экспериментально)

Графическое окно на PySide6/QML ставится отдельным extra и запускается из исходников:

```bash
python3 -m venv .venv
.venv/bin/pip install ".[gui]"
.venv/bin/python -m zapret_console --gui
```

GUI-тесты входят в общий unittest-стек: без PySide6 они пропускаются, в venv запускаются headless:

```bash
QT_QPA_PLATFORM=offscreen QT_QUICK_BACKEND=software .venv/bin/python -m unittest discover -s tests -v
```

QML-файлы в `src/zapret_console/gui/qml/` включаются в пакет как package data; изменения интерфейса проверяйте загрузкой QML без предупреждений.

В issue укажите ОС, версию приложения, сценарий, ожидаемое поведение и результат `zapret-console --doctor`. Отчёт диагностики содержит сетевой интерфейс и локальный IP; перед публикацией уберите сведения, которыми не хотите делиться. Токены и логи Discord прикладывать не нужно.


## Полная установка

`sudo bash scripts/setup.sh --yes` проверяет нативные зависимости и устанавливает all. `--ui tui` — без Qt, `--ui none` — CLI/whiptail. Установщик не перезапускает существующий сервис. Для staging без сети: `DESTDIR=/tmp/zapret-stage bash scripts/install.sh`; с настоящими зависимостями: добавьте `--with-deps`.
