"""Install immutable application releases, keeping the backend unchanged."""
import argparse
import ast
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
import uuid


def check_path(path):
    """Never traverse a writable or symlinked system destination (staging too)."""
    path = Path(path).absolute()
    for node in (path, *path.parents):
        if node.is_symlink():
            raise RuntimeError(f'Ссылка вместо пути установки: {node}')
        if node.exists():
            if node != path and not node.is_dir():
                raise RuntimeError(f'Родитель не является каталогом: {node}')
            info = node.stat()
            # /tmp is a valid staging ancestor; a sticky root-owned directory
            # cannot let another user replace our existing child directory.
            sticky = stat.S_ISDIR(info.st_mode) and info.st_uid == 0 and info.st_mode & stat.S_ISVTX
            if info.st_mode & 0o022 and not sticky:
                raise RuntimeError(f'Путь доступен для посторонней записи: {node}')
            if os.geteuid() == 0 and info.st_uid != 0:
                raise RuntimeError(f'Путь установки не принадлежит root: {node}')
    return path


def atomic(path, data, mode=0o644):
    check_path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
    descriptor, name = tempfile.mkstemp(prefix='.zapret-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(data)
        os.chmod(name, mode)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


@contextmanager
def installation_lock(base):
    check_path(base)
    base.mkdir(parents=True, exist_ok=True, mode=0o755)
    lock = check_path(base / '.install.lock')
    with lock.open('a') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Другая установка или удаление уже выполняется')
        yield


def requirements(source, ui):
    # Python 3.10 has no tomllib; parse only our literal extras, never eval.
    section = (source / 'pyproject.toml').read_text().split('[project.optional-dependencies]\n', 1)[1].split('\n[', 1)[0]
    extras = {}
    for line in section.splitlines():
        if '=' in line:
            key, value = line.split('=', 1)
            extras[key.strip()] = ast.literal_eval(value.strip())
    result = list(extras['tui']) if ui != 'none' else []
    if ui == 'all':
        result.extend(extras['gui'])
    if not all(isinstance(item, str) and re.fullmatch(r'[A-Za-z0-9_.-]+==[0-9.]+', item) for item in result):
        raise ValueError('Недопустимые зависимости UI')
    return result


def run(argv):
    subprocess.run(argv, check=True)


def install(source, stage='', ui='all', with_deps=None, backend_root=None, unit=None, runner=run):
    if ui not in ('all', 'tui', 'none'):
        raise ValueError('Недопустимый режим UI')
    stage = str(stage)
    if stage and (not Path(stage).is_absolute() or '..' in Path(stage).parts):
        raise ValueError('DESTDIR должен быть абсолютным путём без ..')
    if not stage and os.geteuid() != 0:
        raise RuntimeError('Установка: sudo bash scripts/install.sh')
    prefix = Path(stage + '/usr/local')
    base = check_path(prefix / 'lib' / 'zapret-console')
    settings = check_path(Path(stage + '/etc/zapret-console/settings.json'))
    state = check_path(Path(stage + '/var/lib/zapret-console'))
    original_settings = settings.read_bytes() if settings.exists() else None
    old = json.loads(original_settings) if original_settings is not None else {}
    root = backend_root or old.get('backend_root', '/opt/zapret-discord-youtube-linux')
    service = unit or old.get('service', 'zapret_discord_youtube.service')
    if not isinstance(root, str) or not Path(root).is_absolute() or not isinstance(service, str) or not re.fullmatch(r'[A-Za-z0-9_.@-]+\.service', service):
        raise ValueError('Некорректный путь адаптера или имя сервиса')
    if not stage:
        for tool in ('curl', 'ip', 'systemctl', 'sudo', 'whiptail'):
            if not shutil.which(tool):
                raise RuntimeError(f'Не найдена зависимость: {tool}. Запусти scripts/setup.sh')
        if ui == 'all' and not shutil.which('pkexec'):
            raise RuntimeError('Не найден pkexec. Запусти scripts/setup.sh')
        if not (Path(root) / 'conf.env').is_file() or not os.access(Path(root) / 'nfqws', os.X_OK):
            raise RuntimeError(f'Сначала настрой адаптер: {root}')
    deps = requirements(source, ui)
    with_deps = not bool(stage) if with_deps is None else with_deps
    desktop = prefix / 'share/applications'
    icon = prefix / 'share/icons/hicolor/scalable/apps/zapret-console.svg'
    launcher = prefix / 'bin/zapret-console'
    gui_entry, tui_entry = desktop / 'zapret-console.desktop', desktop / 'zapret-console-tui.desktop'
    destinations = (launcher, icon, gui_entry, tui_entry, settings)
    for path in destinations:
        check_path(path)
    current = base / 'current'
    with installation_lock(base):
        old_target = None
        if current.is_symlink():
            old_target = os.readlink(current)
            target = current.resolve(strict=True)
            target.relative_to(base / 'releases')
            check_path(target)
        elif current.exists():
            raise RuntimeError('current должен быть ссылкой на установленный выпуск')
        if (settings.read_bytes() if settings.exists() else None) != original_settings:
            raise RuntimeError('Настройки изменились во время подготовки установки. Запусти её заново.')
        release = check_path(base / 'releases' / uuid.uuid4().hex)
        release.mkdir(parents=True, mode=0o755)
        previous = {p: (p.read_bytes(), p.stat().st_mode & 0o777) if p.exists() else None for p in destinations}
        switched = False
        published = False
        try:
            package = source / 'src/zapret_console'
            if package.is_symlink() or any(p.is_symlink() for p in package.rglob('*')):
                raise RuntimeError('Исходный пакет содержит символические ссылки')
            shutil.copytree(package, release / 'app/zapret_console', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
            for p in (release / 'app').rglob('*'):
                p.chmod(0o755 if p.is_dir() else 0o644)
            bootstrap = b"import sys\nfrom pathlib import Path\nsys.path.insert(0, str(Path(__file__).resolve().parent / 'app'))\nfrom zapret_console.app import entrypoint\nentrypoint()\n"
            atomic(release / 'bootstrap.py', bootstrap)
            if with_deps and deps:
                runner(['/usr/bin/python3', '-I', '-m', 'venv', str(release / 'venv')])
                python = str(release / 'venv/bin/python')
                runner([python, '-I', '-m', 'pip', '--isolated', 'install', '--disable-pip-version-check', *deps])
                imports = 'import textual' + ('; import PySide6; from PySide6.QtQml import QQmlApplicationEngine' if ui == 'all' else '')
                runner([python, '-I', '-c', imports])
            runner(['/usr/bin/python3', '-I', str(release / 'bootstrap.py'), '--help'])
            atomic(release / 'installation.json', json.dumps({'ui': ui, 'dependencies_installed': bool(with_deps and deps)}, indent=2).encode())
            state.mkdir(parents=True, exist_ok=True, mode=0o755)
            published = True
            atomic(launcher, (source / 'packaging/launcher.py').read_bytes(), 0o755)
            atomic(icon, (source / 'packaging/zapret-console.svg').read_bytes())
            for path, enabled, name in ((gui_entry, ui == 'all', 'zapret-console.desktop'), (tui_entry, ui != 'none', 'zapret-console-tui.desktop')):
                if enabled:
                    atomic(path, (source / 'packaging' / name).read_bytes())
                elif path.exists():
                    path.unlink()
            if original_settings is None or root != old.get('backend_root') or service != old.get('service'):
                updated_settings = dict(old, backend_root=root, service=service)
                atomic(settings, (json.dumps(updated_settings, indent=2) + '\n').encode())
            next_link = base / ('.current-' + uuid.uuid4().hex)
            next_link.symlink_to(Path('releases') / release.name)
            os.replace(next_link, current)
            switched = True
            # Verify the published launcher before declaring success.
            runner([str(launcher), '--version'])
        except BaseException:
            if switched:
                if old_target is None:
                    current.unlink()
                else:
                    rollback = base / ('.rollback-' + uuid.uuid4().hex)
                    rollback.symlink_to(old_target)
                    os.replace(rollback, current)
            if published:
                for path, value in previous.items():
                    if value is None:
                        path.unlink(missing_ok=True)
                    else:
                        atomic(path, *value)
            shutil.rmtree(release)
            raise
    print('Установлено. Терминал: zapret-console; окно: zapret-console --gui' if ui == 'all' else 'Установлено. Режим: ' + ui)
    if stage and not with_deps and deps:
        print('Staging: UI-зависимости не загружались; для полной проверки передай --with-deps.')
    return release


def uninstall(stage=''):
    stage = str(stage)
    if stage and (not Path(stage).is_absolute() or '..' in Path(stage).parts):
        raise ValueError('DESTDIR должен быть абсолютным путём без ..')
    if not stage and os.geteuid() != 0:
        raise RuntimeError('Удаление: sudo bash scripts/uninstall.sh')
    prefix = Path(stage + '/usr/local')
    base = check_path(prefix / 'lib/zapret-console')
    files = [prefix / 'bin/zapret-console', prefix / 'share/applications/zapret-console.desktop',
             prefix / 'share/applications/zapret-console-tui.desktop', prefix / 'share/icons/hicolor/scalable/apps/zapret-console.svg']
    for path in files:
        check_path(path)
    # Keep the parent/lock inode so install and uninstall never race after unlink.
    with installation_lock(base):
        for path in files:
            path.unlink(missing_ok=True)
        for path in base.iterdir():
            if path.name == '.install.lock':
                continue
            if path.is_symlink() or not path.is_dir():
                path.unlink()
            else:
                shutil.rmtree(path)
    print('Приложение и ярлыки удалены. Адаптер, сервис, настройки и профили сохранены.')


def main():
    os.umask(0o022)
    parser = argparse.ArgumentParser(description='Установить GUI/TUI без изменения адаптера')
    parser.add_argument('--backend-root')
    parser.add_argument('--service')
    parser.add_argument('--ui', choices=('all', 'tui', 'none'), default='all')
    parser.add_argument('--with-deps', action='store_true', default=None, help='Загрузить зависимости также в DESTDIR')
    parser.add_argument('--uninstall', action='store_true')
    args = parser.parse_args()
    stage = os.environ.get('DESTDIR', '')
    try:
        if args.uninstall:
            uninstall(stage)
        else:
            install(Path(__file__).resolve().parents[1], stage, args.ui, args.with_deps, args.backend_root, args.service)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        parser.exit(1, f'Ошибка установки: {error}\n')


if __name__ == '__main__':
    main()
