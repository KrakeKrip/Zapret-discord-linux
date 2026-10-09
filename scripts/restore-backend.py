"""Restore only the archived engine and service; keep our UI and profiles."""
import argparse
import importlib.util
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tarfile
import tempfile

SOURCE = Path(__file__).resolve().parents[1]
BACKUP_DIR = Path('/var/backups/zapret-console')
BACKEND = Path('/opt/zapret-discord-youtube-linux')
UNIT = 'zapret_discord_youtube.service'
UNIT_FILE = Path('/etc/systemd/system') / UNIT


def load_installer():
    spec = importlib.util.spec_from_file_location('installer', SOURCE / 'scripts/install.py')
    installer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(installer)
    return installer


def unpack_engine(archive, stage):
    """Copy selected regular files/directories; never extract archived menus."""
    prefix = PurePosixPath(str(BACKEND).lstrip('/'))
    unit_name = str(UNIT_FILE).lstrip('/')
    unit_data = None
    seen = set()
    with tarfile.open(archive, 'r:gz') as bundle:
        selected = []
        for member in bundle.getmembers():
            name = PurePosixPath(member.name)
            if name.is_absolute() or '..' in name.parts:
                raise RuntimeError('Небезопасный путь в резервной копии')
            if str(name) == unit_name:
                if unit_data is not None or not member.isfile():
                    raise RuntimeError('Некорректный unit в резервной копии')
                with bundle.extractfile(member) as stream:
                    unit_data = stream.read()
                continue
            if name != prefix and prefix not in name.parents:
                continue
            if name in seen or not (member.isfile() or member.isdir()):
                raise RuntimeError(f'Неподдерживаемый объект в резервной копии: {name}')
            seen.add(name)
            selected.append((member, name.relative_to(prefix)))
        if unit_data is None or str(BACKEND).encode() not in unit_data:
            raise RuntimeError('В архиве нет подходящего сервиса')
        for required in ('conf.env', 'nfqws', 'service.sh'):
            if not any(str(relative) == required and member.isfile() for member, relative in selected):
                raise RuntimeError(f'В архиве отсутствует {required}')
        for member, relative in sorted(selected, key=lambda item: (len(item[1].parts), str(item[1]))):
            destination = stage.joinpath(*relative.parts)
            if member.isdir():
                destination.mkdir(parents=True, exist_ok=True)
                destination.chmod(0o755)
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                with bundle.extractfile(member) as stream, destination.open('xb') as output:
                    shutil.copyfileobj(stream, output)
                destination.chmod(member.mode & 0o755)
    if not os.access(stage / 'nfqws', os.X_OK):
        raise RuntimeError('Архивный nfqws не является исполняемым файлом')
    return unit_data


def restore(archive, installer, runner=subprocess.run):
    installer.check_path(archive)
    installer.check_path(BACKEND.parent)
    installer.check_path(UNIT_FILE.parent)
    if BACKEND.exists() or BACKEND.is_symlink() or UNIT_FILE.exists() or UNIT_FILE.is_symlink():
        raise RuntimeError('Движок или сервис уже существует; восстановление не заменяет установку')
    stage = Path(tempfile.mkdtemp(prefix='.zapret-restore-', dir=BACKEND.parent))
    published = False
    try:
        stage.chmod(0o700)
        unit_data = unpack_engine(archive, stage)
        # Ensure ownership for administrative configuration and execution.
        for path in (stage, *stage.rglob('*')):
            os.chown(path, 0, 0)
        stage.chmod(0o755)
        stage.rename(BACKEND)
        published = True
        unit_created = False
        try:
            with UNIT_FILE.open('xb') as output:
                unit_created = True
                output.write(unit_data)
            UNIT_FILE.chmod(0o644)
        except BaseException:
            if unit_created:
                UNIT_FILE.unlink(missing_ok=True)
            shutil.rmtree(BACKEND)
            published = False
            raise
        runner(['/usr/bin/systemctl', 'daemon-reload'], check=True, timeout=30)
        runner(['/usr/bin/systemctl', 'start', UNIT], check=True, timeout=60)
        state = runner(['/usr/bin/systemctl', 'is-active', UNIT], capture_output=True, text=True, timeout=15)
        if state.returncode != 0 or state.stdout.strip() != 'active':
            raise RuntimeError('Файлы восстановлены, но сервис не стал active; проверь журнал сервиса')
        print('Движок восстановлен, сервис active. Это ещё не подтверждает доступность Discord.', flush=True)
        print('Управление: zapret-console или zapret-console --gui. Старое меню не восстановлено.', flush=True)
    finally:
        if not published and stage.exists():
            shutil.rmtree(stage)


def main():
    parser = argparse.ArgumentParser(description='Восстановить движок из резервной копии без старого меню')
    parser.add_argument('--restore-backend', action='store_true', required=True)
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise RuntimeError('Запусти эту команду через sudo')
    os.umask(0o022)
    installer = load_installer()
    installer.check_path(BACKUP_DIR)
    archives = sorted(BACKUP_DIR.glob('legacy-*.tar.gz'))
    if not archives:
        raise RuntimeError(f'Резервная копия не найдена: {BACKUP_DIR}')
    archive = archives[-1]
    print(f'Резервная копия: {archive}', flush=True)
    restore(archive, installer)


if __name__ == '__main__':
    try:
        main()
    except (OSError, RuntimeError, ValueError, tarfile.TarError, subprocess.SubprocessError) as error:
        raise SystemExit(f'Восстановление остановлено: {error}')
