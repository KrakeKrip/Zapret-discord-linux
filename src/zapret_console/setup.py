"""First-run installation for Debian/Ubuntu; existing backends are adopted."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

ADAPTER_URL = 'https://github.com/Sergeydigl3/zapret-discord-youtube-linux.git'
ADAPTER_REV = '69db771b527ba11ca71efe28728a7f9491eec352'
DEFAULT_ROOT = Path('/opt/zapret-discord-youtube-linux')
DEFAULT_UNIT = 'zapret_discord_youtube.service'


def run(args, **kw):
    subprocess.run(args, check=True, **kw)


def interfaces():
    result = subprocess.run(['ip', '-j', 'route', 'show', 'table', 'main', 'default'], capture_output=True, text=True, check=True)
    names = [r['dev'] for r in json.loads(result.stdout) if r.get('dev') and not r['dev'].startswith(('tun', 'tap', 'wg'))]
    return sorted(set(names))


def ready(root):
    return all((root / n).is_file() for n in ('service.sh', 'conf.env', 'nfqws'))


def backend_plan(root):
    if ready(root):
        return 'adopt'
    if root.exists():
        raise RuntimeError(f'В {root} неполная установка. Укажи другой каталог или восстанови её вручную.')
    return 'create'


def unit_text(root):
    # systemd token parsing is stricter than normal filesystem paths.
    if not re.fullmatch(r'/[A-Za-z0-9_./-]+', str(root)) or '..' in root.parts:
        raise ValueError('Для установки сервиса используй абсолютный путь без пробелов и специальных символов')
    return f'''[Unit]
Description=Zapret Manager network backend
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory={root}
ExecStart=/usr/bin/bash {root}/service.sh daemon
ExecStop=/usr/bin/bash {root}/service.sh kill
TimeoutStopSec=15

[Install]
WantedBy=multi-user.target
'''


def create_backend(root, interface, strategy, unit, runner=run, system_dir=Path('/etc/systemd/system')):
    if backend_plan(root) != 'create':
        raise RuntimeError('Существующая установка не должна заменяться')
    unit_text(root)
    service_file = system_dir / unit
    if service_file.exists():
        raise RuntimeError(f'Сервис {unit} уже существует. Мастер не будет заменять его.')
    root.parent.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix='.zapret-setup-', dir=root.parent))
    temp.chmod(0o755)
    committed = False
    try:
        runner(['git', 'init', str(temp)])
        runner(['git', '-C', str(temp), 'remote', 'add', 'origin', ADAPTER_URL])
        runner(['git', '-C', str(temp), 'fetch', '--depth', '1', 'origin', ADAPTER_REV])
        runner(['git', '-C', str(temp), 'checkout', '--detach', 'FETCH_HEAD'])
        runner(['bash', str(temp / 'service.sh'), 'download-deps', '--default'], cwd=temp)
        choices = {p.name for folder in ('custom-strategies', 'zapret-latest') for p in (temp / folder).glob('*.bat')}
        if strategy not in choices or not re.fullmatch(r'[A-Za-z0-9_.-]+\.bat', strategy):
            raise ValueError(f'Стратегия отсутствует: {strategy}')
        if interface not in os.listdir('/sys/class/net') or interface == 'lo' or not re.fullmatch(r'[A-Za-z0-9_.:-]+', interface):
            raise ValueError('Недопустимый сетевой интерфейс')
        (temp / 'conf.env').write_text(f'interface={interface}\ngamefiltertcp=false\ngamefilterudp=false\nstrategy={strategy}\nfirewall_backend=nftables\n')
        (temp / 'conf.env').chmod(0o644)
        if not (temp / 'nfqws').is_file():
            raise RuntimeError('Скачивание движка не завершено')
        temp.rename(root)
        committed = True
        service_file.write_text(unit_text(root))
        service_file.chmod(0o644)
        runner(['systemctl', 'daemon-reload'])
    except Exception:
        if committed:
            service_file.unlink(missing_ok=True)
            shutil.rmtree(root)
            runner(['systemctl', 'daemon-reload'])
        raise
    finally:
        if temp.exists():
            shutil.rmtree(temp)


def dependency_packages(ui):
    common = ['git', 'curl', 'whiptail', 'iproute2', 'nftables', 'sudo']
    if ui != 'none':
        common.append('python3-venv')
    if ui == 'all':
        common += ['pkexec', 'polkitd', 'libegl1', 'libgl1', 'libxcb-cursor0',
                   'libxcb-icccm4', 'libxcb-image0', 'libxcb-keysyms1',
                   'libxcb-render-util0', 'libxcb-randr0', 'libxcb-shape0',
                   'libxcb-xfixes0', 'libxcb-sync1', 'libxcb-xkb1',
                   'libxkbcommon-x11-0', 'libdbus-1-3']
    return common


def ensure_dependencies(ui):
    packages = dependency_packages(ui)
    probe = subprocess.run(['dpkg-query', '-W', '-f=${db:Status-Status}\n', *packages], capture_output=True, text=True)
    if probe.returncode != 0 or probe.stdout.splitlines() != ['installed'] * len(packages):
        run(['apt-get', 'update'])
        run(['apt-get', 'install', '-y', *packages])


def main():
    parser = argparse.ArgumentParser(description='Мастер установки Zapret Manager')
    parser.add_argument('--ui', choices=('all', 'tui', 'none'), default='all', help='all: окно и терминал; tui: только терминал; none: только CLI')
    parser.add_argument('--yes', action='store_true', help='Использовать значения по умолчанию без вопросов')
    parser.add_argument('--dry-run', action='store_true', help='Показать план без изменений и загрузок')
    parser.add_argument('--interface')
    parser.add_argument('--strategy', default='general_alt11.bat')
    parser.add_argument('--autostart', action='store_true', help='Включить и запустить только новый сервис')
    parser.add_argument('--backend-root', type=Path)
    parser.add_argument('--service')
    args = parser.parse_args()
    settings_file = Path('/etc/zapret-console/settings.json')
    settings = json.loads(settings_file.read_text()) if settings_file.exists() else {}
    root = args.backend_root or Path(settings.get('backend_root', str(DEFAULT_ROOT)))
    unit = args.service or settings.get('service', DEFAULT_UNIT)
    unit_text(root)
    if not re.fullmatch(r'[A-Za-z0-9_.@-]+\.service', unit):
        raise ValueError('Недопустимое имя сервиса')
    plan = backend_plan(root)
    print(f'Каталог: {root}\nСервис: {unit}\nДействие: ' + ('подключить существующую установку' if plan == 'adopt' else 'установить движок и стратегии'))
    if args.dry_run:
        print(f'План: зависимости Ubuntu/Debian; адаптер; изолированное окружение UI ({args.ui}); приложение и desktop-ярлыки.')
        print('Текущая конфигурация существующей установки будет сохранена.')
        return
    if os.geteuid() != 0:
        raise RuntimeError('Запуск: sudo bash scripts/setup.sh')
    os_release = Path('/etc/os-release').read_text()
    if not re.search(r'^ID=(?:"?)(ubuntu|debian)(?:"?)$', os_release, re.M):
        raise RuntimeError('Автоматическая установка поддерживает Ubuntu/Debian. Для других систем см. scripts/install.sh.')
    if not Path('/run/systemd/system').is_dir():
        raise RuntimeError('Мастер требует работающий systemd')
    if not args.yes:
        if input('Продолжить установку? [Y/n] ').strip().lower() not in ('', 'y', 'yes', 'д', 'да'):
            return
    ensure_dependencies(args.ui)
    if plan == 'create':
        running = subprocess.run(['pgrep', '-x', 'nfqws'], capture_output=True)
        if running.returncode == 0:
            raise RuntimeError('Уже работает другой nfqws. Подключи существующую установку через --backend-root.')
        names = interfaces()
        interface = args.interface or (names[0] if len(names) == 1 else None)
        if args.yes and not interface:
            raise RuntimeError('Несколько интерфейсов или маршрут не определён. Укажи --interface.')
        if not interface or not args.yes:
            print('Интерфейсы: ' + ', '.join(names))
            interface = args.interface or input(f'Интерфейс [{interface or ""}]: ').strip() or interface
        if not interface:
            raise RuntimeError('Интерфейс не выбран. Укажи --interface.')
        strategy = args.strategy
        if not args.yes:
            strategy = input(f'Стратегия [{strategy}]: ').strip() or strategy
        print(f'Первый профиль: {strategy} / {interface}. Работоспособность проверяется после установки.')
        create_backend(root, interface, strategy, unit)
    source = Path(__file__).resolve().parents[2]
    run(['bash', str(source / 'scripts/install.sh'), '--backend-root', str(root), '--service', unit, '--ui', args.ui])
    if plan == 'create' and args.autostart:
        run(['systemctl', 'enable', '--now', unit])
    elif plan == 'create':
        print('Движок установлен и остановлен. Открой zapret-console и нажми «Запустить».')
    print('Мастер завершён. Запуск: zapret-console')


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, ValueError, OSError, subprocess.CalledProcessError) as e:
        raise SystemExit(f'Ошибка: {e}')
