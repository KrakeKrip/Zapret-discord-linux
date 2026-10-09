"""Local migration requested by the owner: update UI, remove the legacy engine.

Fixed paths only. Never remove the user's project, settings or current profiles.
"""
import argparse
from datetime import datetime, timezone
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess

SOURCE = Path(__file__).resolve().parents[1]
BACKEND = Path('/opt/zapret-discord-youtube-linux')
UNIT = 'zapret_discord_youtube.service'
UNIT_FILE = Path('/etc/systemd/system') / UNIT
OLD_MENU = Path('/usr/local/bin/zapret-menu')
BACKUP_DIR = Path('/var/backups/zapret-console')
PROC_DIR = Path('/proc')
OLD_STATE = Path('/var/lib/zapret-menu')


def load_installer():
    spec = importlib.util.spec_from_file_location('installer', SOURCE / 'scripts/install.py')
    installer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(installer)
    return installer


def check_legacy_installation():
    for path in (BACKEND, UNIT_FILE, OLD_MENU):
        if path.is_symlink() or not path.exists() or path.stat().st_uid != 0 or path.stat().st_gid != 0 or path.stat().st_mode & 0o002:
            raise RuntimeError(f'Неподходящий путь старой установки: {path}')
    if str(BACKEND) not in UNIT_FILE.read_text() or str(BACKEND) not in OLD_MENU.read_text():
        raise RuntimeError('Сервис/меню не относятся к ожидаемой старой установке')


def main():
    parser = argparse.ArgumentParser(description='Обновить свой интерфейс и удалить старый движок/меню с резервной копией')
    parser.add_argument('--remove-legacy-backend', action='store_true', required=True)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    print(f'План: обновить свой GUI/TUI; архивировать и удалить {BACKEND}, {UNIT_FILE}, {OLD_MENU}.', flush=True)
    print('Наш репозиторий, /etc/zapret-console и /var/lib/zapret-console сохраняются. Обход будет выключен.', flush=True)
    if args.dry_run:
        return
    if os.geteuid() != 0:
        raise RuntimeError('Нужна системная авторизация sudo/pkexec')
    os.umask(0o022)
    check_legacy_installation()
    installer = load_installer()
    backup_dir = installer.check_path(BACKUP_DIR)
    backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    archive = backup_dir / ('legacy-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '.tar.gz')
    log_file = installer.check_path(backup_dir / 'migration.log')
    descriptor = os.open(log_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'w') as log:
        os.fchmod(log.fileno(), 0o600)
        def run(argv):
            subprocess.run(argv, check=True, stdout=log, stderr=subprocess.STDOUT, timeout=600)
        paths = [BACKEND, UNIT_FILE, OLD_MENU]
        old_state = OLD_STATE
        if old_state.exists() and not old_state.is_symlink():
            paths.append(old_state)
        print('Создаю резервную копию…', flush=True)
        run(['/usr/bin/tar', '-czf', str(archive), '-C', '/', '--', *[str(p.relative_to('/')) for p in paths]])
        archive.chmod(0o600)
        print('Обновляю собственное приложение…', flush=True)
        installer.install(SOURCE, ui='all', runner=run)
        print('Останавливаю и отключаю сторонний сервис…', flush=True)
        run(['/usr/bin/systemctl', 'stop', UNIT])
        run(['/usr/bin/systemctl', 'disable', UNIT])
        active = subprocess.run(['/usr/bin/systemctl', 'is-active', UNIT], capture_output=True, text=True)
        if active.stdout.strip() not in ('inactive', 'failed'):
            raise RuntimeError('Сервис не остановлен; файлы не удаляются')
        for proc in PROC_DIR.iterdir():
            if not proc.name.isdigit():
                continue
            try:
                executable = (proc / 'cmdline').read_bytes().split(b'\0')[0]
                if executable == str(BACKEND / 'nfqws').encode():
                    raise RuntimeError('Старый nfqws всё ещё работает; файлы не удаляются')
            except (FileNotFoundError, PermissionError, ProcessLookupError):
                pass
        nft = shutil.which('nft')
        if nft and subprocess.run([nft, 'list', 'table', 'inet', 'zapretunix'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
            raise RuntimeError('Старые правила zapretunix остались; удаление файлов остановлено')
        shutil.rmtree(BACKEND)
        UNIT_FILE.unlink()
        OLD_MENU.unlink()
        run(['/usr/bin/systemctl', 'daemon-reload'])
        # Old menu profiles remain in the archive; current product profiles stay.
        print(f'Старый движок и меню удалены. Резервная копия: {archive}', flush=True)
        print('Свой интерфейс установлен: zapret-console / zapret-console --gui. Движок не подключён.', flush=True)


if __name__ == '__main__':
    try:
        main()
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        raise SystemExit(f"Миграция остановлена: {error}. Журнал (если создан): {BACKUP_DIR / 'migration.log'}")
