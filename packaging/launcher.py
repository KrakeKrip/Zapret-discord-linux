#!/usr/bin/python3 -I
"""Installed entry point. Root helper uses only system Python and trusted code."""
import os
import stat
from pathlib import Path
import sys

prefix = Path(__file__).resolve().parent.parent
base = prefix / 'lib' / 'zapret-console'
try:
    release = (base / 'current').resolve(strict=True)
    release.relative_to(base / 'releases')
    if os.geteuid() == 0:
        package = release / 'app' / 'zapret_console'
        for node in (*package.rglob('*'), package, *package.parents):
            if node.is_symlink():
                raise RuntimeError(f'Ссылка внутри установленного кода: {node}')
            info = node.stat()
            sticky = stat.S_ISDIR(info.st_mode) and info.st_uid == 0 and info.st_mode & stat.S_ISVTX
            if info.st_uid != 0 or (info.st_mode & 0o022 and not sticky):
                raise RuntimeError(f'Недоверенный путь установленного приложения: {node}')
    core_modes = {'--admin', '--request-json', '--status', '--json', '--doctor', '--diagnose', '--version', '--help', '-h', '--legacy-menu'}
    if os.geteuid() != 0 and not core_modes.intersection(sys.argv[1:]):
        python = release / 'venv' / 'bin' / 'python'
        if not python.is_file():
            raise RuntimeError('UI-зависимости не установлены. Выполни sudo bash scripts/install.sh --ui all (или --ui tui). Прежнее меню: --legacy-menu')
        os.execv(str(python), [str(python), '-I', str(release / 'bootstrap.py'), *sys.argv[1:]])
    sys.path.insert(0, str(release / 'app'))
    from zapret_console.app import entrypoint
    entrypoint()
except (OSError, ValueError, RuntimeError) as error:
    print(f'Ошибка запуска: {error}', file=sys.stderr)
    raise SystemExit(1)
