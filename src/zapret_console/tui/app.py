"""Textual frontend over the same client/CAS/lock used by QML."""
import os
import sys

from .. import client


def run_tui():
    if os.geteuid() == 0:
        print('Запусти терминальный интерфейс обычным пользователем, без sudo.')
        return 1
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print('Нужен интерактивный терминал. Для скриптов: --status или --diagnose.')
        return 1
    try:
        from .ui import ZapretApp
    except ImportError as e:
        if e.name != 'textual' and not (e.name or '').startswith('textual.'):
            raise
        print('Textual не установлен. Для запуска из исходников:\n'
              '  python3 -m venv .venv\n'
              '  .venv/bin/pip install ".[tui]"\n'
              '  .venv/bin/python -m zapret_console --tui\n'
              'Прежнее меню: zapret-console --legacy-menu')
        return 1
    ZapretApp(client.Backend(mode='terminal')).run()
    return 0
