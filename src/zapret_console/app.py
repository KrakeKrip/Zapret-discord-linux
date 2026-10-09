#!/usr/bin/env python3
"""Zapret Console: systemd controls, saved profiles and network diagnostics."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import fcntl
import stat

ROOT = Path('/opt/zapret-discord-youtube-linux')
STATE = Path('/var/lib/zapret-console')
UNIT = 'zapret_discord_youtube.service'
KNOWN = STATE / 'known-good.json'
VERSION = '0.2.0'
SETTINGS = Path('/etc/zapret-console/settings.json')
LAUNCHER = '/usr/local/bin/zapret-console'
FIELDS = ('interface', 'gamefiltertcp', 'gamefilterudp', 'strategy', 'firewall_backend')


def trusted(path):
    """Root actions may only use administrator-controlled files and directories."""
    resolved = path.resolve(strict=True)
    for node in (resolved, *resolved.parents):
        st = node.stat()
        if st.st_uid != 0 or st.st_mode & stat.S_IWOTH or (st.st_mode & stat.S_IWGRP and st.st_gid != 0):
            raise RuntimeError(f'Путь доступен для изменения обычному пользователю: {node}')


def load_settings():
    global ROOT, UNIT
    if SETTINGS.exists():
        trusted(SETTINGS)
        settings = json.loads(SETTINGS.read_text())
        root = settings.get('backend_root', str(ROOT))
        unit = settings.get('service', UNIT)
        if not isinstance(root, str) or not Path(root).is_absolute():
            raise ValueError('backend_root должен быть абсолютным путём')
        if not isinstance(unit, str) or not re.fullmatch(r'[A-Za-z0-9_.@-]+\.service', unit):
            raise ValueError('Недопустимое имя сервиса')
        ROOT, UNIT = Path(root), unit


def preflight():
    errors = []
    for name in ('systemctl', 'ip', 'curl', 'whiptail', 'sudo'):
        if not shutil.which(name):
            errors.append(f'Не найдена утилита: {name}')
    if not (ROOT / 'conf.env').is_file():
        errors.append(f'Не найден конфиг адаптера: {ROOT / "conf.env"}')
    if not (ROOT / 'nfqws').is_file():
        errors.append(f'Не найден движок: {ROOT / "nfqws"}')
    return errors


def command(args, timeout=20):
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout)


def strategies():
    names = set()
    for folder in ('custom-strategies', 'zapret-latest'):
        for p in (ROOT / folder).glob('*.bat'):
            if re.fullmatch(r'[A-Za-z0-9_.-]+\.bat', p.name):
                names.add(p.name)
    return sorted(names)


def validate(c):
    if set(c) != set(FIELDS):
        raise ValueError('Неполная конфигурация')
    if c['interface'] != 'any' and c['interface'] not in os.listdir('/sys/class/net'):
        raise ValueError('Сетевой интерфейс отсутствует')
    if not re.fullmatch(r'[A-Za-z0-9_.:-]+', c['interface']):
        raise ValueError('Недопустимое имя интерфейса')
    if c['strategy'] not in strategies():
        raise ValueError('Стратегия отсутствует')
    if c['gamefiltertcp'] not in ('true', 'false') or c['gamefilterudp'] not in ('true', 'false'):
        raise ValueError('Некорректные настройки GameFilter')
    if c['firewall_backend'] not in ('auto', 'nftables', 'iptables'):
        raise ValueError('Некорректный бэкенд')
    return c


def config():
    result = {}
    for line in (ROOT / 'conf.env').read_text().splitlines():
        key, sep, value = line.partition('=')
        if sep and key in FIELDS:
            result[key] = value.strip()
    result.setdefault('firewall_backend', 'auto')
    return validate(result)


def atomic_write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix='.zapret-console-')
    try:
        with os.fdopen(fd, 'w') as f:
            f.write(content)
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def write_config(c):
    validate(c)
    atomic_write(ROOT / 'conf.env', ''.join(f'{k}={c[k]}\n' for k in FIELDS))


PROFILE_NAME = r'[A-Za-z0-9][A-Za-z0-9_-]{0,47}'
PROFILE_NAME_HINT = ('Имя профиля: 1–48 символов, латинские буквы и цифры, '
                     'внутри также "_" и "-". Первый символ — буква или цифра; точки, пробелы и '
                     'разделители пути нельзя.')


def profiles_dir():
    return STATE / 'profiles'


def profile_path(name):
    if not isinstance(name, str) or not re.fullmatch(PROFILE_NAME, name):
        raise ValueError(PROFILE_NAME_HINT)
    return profiles_dir() / f'{name}.json'


def check_profiles_dir(create=False):
    """Reject symlinked profiles dir; for creation also require trusted owners (real trusted)."""
    d = profiles_dir()
    if d.is_symlink():
        raise RuntimeError('Каталог профилей не может быть символической ссылкой')
    if create:
        if d.is_dir():
            trusted(d)
        elif d.exists():
            raise RuntimeError(f'{d} должен быть каталогом профилей')
        else:
            trusted(STATE)
            d.mkdir(parents=True)
            # Ordinary users need read access for the unprivileged listing.
            os.chmod(d, 0o755)
            trusted(d)
    return d


def read_profile(path):
    data = json.loads(path.read_text())
    if not isinstance(data, dict) or set(data) != set(FIELDS):
        raise ValueError(f'Профиль повреждён: {path.name} не содержит конфигурацию из пяти полей')
    return data


def profile_entries():
    """Sorted [(name, config)] for menus; a damaged profile yields None instead of config."""
    d = check_profiles_dir()
    if not d.is_dir():
        return []
    entries = []
    for p in sorted(d.iterdir()):
        m = re.fullmatch(f'({PROFILE_NAME})\\.json', p.name)
        if not m or p.is_symlink() or not p.is_file():
            continue
        try:
            entries.append((m.group(1), read_profile(p)))
        except (ValueError, OSError):
            entries.append((m.group(1), None))
    return entries


def profile_label(name, data):
    if data is None:
        return f'{name} — повреждён, недоступен для восстановления'
    return f'{name} — {data["strategy"]} · интерфейс: {data["interface"]}'


def profile_op(action, name):
    """Admin-side profile storage; revalidates name and paths independently of the menu."""
    path = profile_path(name)
    check_profiles_dir(create=action == 'profile-save')
    if action == 'profile-save':
        if path.is_symlink():
            raise RuntimeError('Файл профиля не может быть символической ссылкой')
        if path.exists():
            raise RuntimeError(f'Профиль "{name}" уже существует. Замена требует отдельного подтверждения.')
        atomic_write(path, json.dumps(config(), ensure_ascii=False, indent=2))
        return
    if path.is_symlink():
        raise RuntimeError('Файл профиля не может быть символической ссылкой')
    if not path.is_file():
        raise RuntimeError(f'Профиль "{name}" не найден')
    trusted(path)
    if action == 'profile-replace':
        atomic_write(path, json.dumps(config(), ensure_ascii=False, indent=2))
    elif action == 'profile-restore':
        apply_config(validate(read_profile(path)))
    elif action == 'profile-delete':
        os.unlink(path)


def active():
    return command(['systemctl', 'is-active', UNIT]).returncode == 0


def systemctl(action):
    r = command(['systemctl', action, UNIT], timeout=30)
    if r.returncode:
        raise RuntimeError(r.stderr.strip() or r.stdout.strip() or 'systemctl завершился с ошибкой')


def apply_config(new):
    old = config()
    was_active = active()
    validate(new)
    atomic_write(STATE / 'previous.json', json.dumps(old, indent=2))
    write_config(new)
    if was_active:
        try:
            systemctl('restart')
            # Wait for the adapter to finish its own one-second initialization.
            import time
            time.sleep(2)
            if not active():
                raise RuntimeError('Сервис не запустился')
        except Exception as e:
            write_config(old)
            try:
                systemctl('restart')
            except Exception as restore_error:
                raise RuntimeError(f'{e}. Конфигурация возвращена, но перезапуск не удался: {restore_error}')
            raise RuntimeError(f'{e}. Предыдущая конфигурация восстановлена.')


def admin(action, value=None):
    if os.geteuid() != 0:
        raise RuntimeError('Для системного изменения требуются права администратора')
    if action == 'runtime':
        from .diagnostics import runtime_snapshot
        print(json.dumps(runtime_snapshot(UNIT)))
        return
    trusted(ROOT)
    trusted(ROOT / 'conf.env')
    trusted(ROOT / 'nfqws')
    for path in ROOT.rglob('*.sh'):
        trusted(path)
    if action in ('start', 'stop', 'restart', 'enable', 'disable'):
        systemctl(action)
    elif action == 'strategy':
        new = config()
        new['strategy'] = value
        apply_config(new)
    elif action == 'interface':
        new = config()
        new['interface'] = value
        apply_config(new)
    elif action == 'save-good':
        atomic_write(KNOWN, json.dumps(config(), ensure_ascii=False, indent=2))
    elif action == 'restore-good':
        trusted(KNOWN)
        apply_config(validate(json.loads(KNOWN.read_text())))
    elif action == 'restore-previous':
        previous = STATE / 'previous.json'
        trusted(previous)
        apply_config(validate(json.loads(previous.read_text())))
    elif action in ('profile-save', 'profile-replace', 'profile-restore', 'profile-delete'):
        profile_op(action, value)
    else:
        raise ValueError('Неизвестное действие')
    print('Готово.')


def privileged(action, value=None):
    if not Path(LAUNCHER).is_file():
        raise RuntimeError('Сначала установи приложение: sudo bash scripts/install.sh')
    args = [LAUNCHER, '--admin', action]
    if value is not None:
        args += ['--value', value]
    if os.geteuid() != 0:
        args = ['sudo', '--'] + args
    # Password input belongs to sudo in the user's terminal.
    subprocess.run(['clear'], check=False)
    r = subprocess.run(args)
    if r.returncode:
        input('\nДействие не выполнено. Enter — вернуться в меню…')


def dialog(args):
    width = min(shutil.get_terminal_size().columns - 4, 100)
    height = min(shutil.get_terminal_size().lines - 2, 26)
    if width < 55 or height < 16:
        raise RuntimeError('Увеличь терминал хотя бы до 59 × 18 символов')
    # Leave terminal output attached to the TTY; selection uses a separate FD.
    with tempfile.TemporaryFile(mode='w+') as selection:
        r = subprocess.run(['whiptail', '--title', 'Zapret Console', '--backtitle',
                            '↑↓ выбор · Enter открыть · Tab кнопки · Esc назад',
                            '--ok-button', 'Готово', '--cancel-button', 'Назад',
                            '--yes-button', 'Да', '--no-button', 'Нет',
                            '--output-fd', str(selection.fileno())] +
                           [str(x).replace('{W}', str(width)).replace('{H}', str(height)) for x in args],
                           pass_fds=(selection.fileno(),))
        selection.seek(0)
        return selection.read() if r.returncode == 0 else None


def menu(prompt, entries, default=None, tags=False):
    args = []
    if not tags:
        args += ['--notags']
    if default is not None:
        args += ['--default-item', default]
    rows = max(4, min(12, shutil.get_terminal_size().lines - 12))
    args += ['--menu', prompt, '{H}', '{W}', str(rows)]
    for key, label in entries:
        args += [key, label]
    return dialog(args)


def show(text):
    fd, name = tempfile.mkstemp(prefix='zapret-console-')
    try:
        with os.fdopen(fd, 'w') as f:
            f.write(text)
        dialog(['--textbox', name, '{H}', '{W}', '--scrolltext'])
    finally:
        os.unlink(name)


def status_data():
    c = config()
    state = command(['systemctl', 'is-active', UNIT]).stdout.strip() or 'unknown'
    enabled = command(['systemctl', 'is-enabled', UNIT]).stdout.strip() or 'unknown'
    return {'version': VERSION, 'service': UNIT, 'state': state, 'autostart': enabled, 'config': c}


def status():
    c = config()
    state = 'РАБОТАЕТ' if active() else 'ОСТАНОВЛЕН'
    auto = command(['systemctl', 'is-enabled', UNIT]).returncode == 0
    return f"{state} · автозапуск {'включён' if auto else 'выключен'}\nСтратегия: {c['strategy']} · интерфейс: {c['interface']}"


def gateway_probe():
    s = socket.create_connection(('gateway.discord.gg', 443), timeout=8)
    try:
        s = ssl.create_default_context().wrap_socket(s, server_hostname='gateway.discord.gg')
        s.sendall(b'GET /?v=10&encoding=json HTTP/1.1\r\nHost: gateway.discord.gg\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\nSec-WebSocket-Version: 13\r\n\r\n')
        data = b''
        while b'\r\n\r\n' not in data:
            part = s.recv(4096)
            if not part or len(data) > 65536:
                raise RuntimeError('Сервер не завершил WebSocket handshake')
            data += part
        headers, frame = data.split(b'\r\n\r\n', 1)
        if b' 101 ' not in headers.split(b'\r\n')[0]:
            raise RuntimeError('Сервер не принял WebSocket')
        while len(frame) < 2:
            part = s.recv(4096)
            if not part:
                raise RuntimeError('WebSocket закрылся до получения данных')
            frame += part
        return 'OK — WebSocket подключился, сервер прислал данные'
    finally:
        s.close()


def get_runtime():
    from .diagnostics import runtime_snapshot
    if os.geteuid() == 0:
        return runtime_snapshot(UNIT)
    if not Path(LAUNCHER).is_file():
        return runtime_snapshot(UNIT)
    args = ['sudo']
    if not sys.stdin.isatty():
        args += ['-n']
    args += ['--', LAUNCHER, '--admin', 'runtime']
    try:
        r = subprocess.run(args, stdout=subprocess.PIPE,
                           stderr=None if sys.stdin.isatty() else subprocess.DEVNULL,
                           text=True, timeout=60)
        if r.returncode == 0:
            return json.loads(r.stdout)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass
    return runtime_snapshot(UNIT)


def diagnose():
    from .diagnostics import runtime_summary
    print('\nПроверка текущего сетевого пути. Это займёт до минуты…', flush=True)
    print('Проверка firewall и очереди может запросить пароль sudo.', flush=True)
    before = get_runtime()
    checks = []
    c = config()
    lines = [f"Стратегия: {c['strategy']} · интерфейс: {c['interface']}", '']
    try:
        address = socket.getaddrinfo('discord.com', 443, socket.AF_INET)[0][4][0]
        route = command(['ip', 'route', 'get', address]).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        route = ''
    lines += ['Маршрут к Discord:', route, '']
    match = re.search(r'\bdev (\S+)', route)
    for name, url in [('Страница приложения', 'https://discord.com/app'),
                      ('API Discord', 'https://discord.com/api/v10/gateway')]:
        print(f'  {name}…', flush=True)
        try:
            r = command(['curl', '--noproxy', '*', '-fSs', '--max-time', '12', '-o', '/dev/null',
                         '-w', 'HTTP %{http_code}, получено %{size_download} байт', url], timeout=15)
            lines.append(f"{name}: {'OK' if r.returncode == 0 else 'ОШИБКА'} — {r.stdout.strip()}")
            checks.append(r.returncode == 0)
            if r.returncode:
                lines.append(r.stderr.strip())
        except subprocess.TimeoutExpired:
            checks.append(False)
            lines.append(f'{name}: превышено время ожидания')
    print('  WebSocket…', flush=True)
    try:
        lines.append(gateway_probe())
        checks.append(True)
    except Exception as e:
        checks.append(False)
        lines.append(f'WebSocket: ОШИБКА — {e}')
    after = get_runtime()
    lines += ['', 'Результат диагностики:', *runtime_summary(before, after, match.group(1) if match else None,
                                                           c['interface'], len(checks) == 3 and all(checks))]
    lines += ['', 'Голос и трансляция проверяются подключением к каналу в Discord.',
              'Эта проверка не входит в голосовые каналы и не использует твой аккаунт.']
    report = '\n'.join(lines)
    dest = Path(os.environ.get('XDG_STATE_HOME', str(Path.home() / '.local/state'))) / 'zapret-console/diagnostics.txt'
    atomic_write(dest, report + '\n')
    return report + f'\n\nОтчёт сохранён: {dest}'


def profiles_menu():
    while True:
        try:
            selected = menu('Именованные профили: свои наборы настроек для разных подключений.', [
                ('save', 'Сохранить текущую настройку под именем'),
                ('restore', 'Восстановить выбранный профиль'),
                ('delete', 'Удалить профиль')])
        except (ValueError, RuntimeError, OSError, subprocess.TimeoutExpired) as e:
            show(f'Ошибка: {e}')
            return
        if selected in (None, 'exit'):
            return
        try:
            if selected == 'save':
                name = dialog(['--inputbox', 'Введи имя нового профиля. ' + PROFILE_NAME_HINT, '10', '{W}'])
                if name is None:
                    continue
                # whiptail may append a newline to the form result; typed spaces stay rejected.
                name = name.rstrip('\n')
                profile_path(name)
                target = profiles_dir() / f'{name}.json'
                if target.exists():
                    if dialog(['--yesno', f'Профиль "{name}" уже существует. Заменить его текущей настройкой?', '10', '{W}']) is None:
                        continue
                    privileged('profile-replace', name)
                else:
                    privileged('profile-save', name)
            elif selected == 'restore':
                entries = profile_entries()
                if not entries:
                    show('Именованных профилей пока нет. Сохрани текущую настройку под именем.')
                    continue
                picked = menu('Какой профиль восстановить? Текущая настройка будет заменена.',
                              [(n, profile_label(n, d)) for n, d in entries], tags=True)
                if not picked:
                    continue
                if dict(entries)[picked] is None:
                    show(f'Профиль "{picked}" повреждён: восстановление невозможно. Удали его и сохрани заново.')
                    continue
                privileged('profile-restore', picked)
            elif selected == 'delete':
                entries = profile_entries()
                if not entries:
                    show('Именованных профилей пока нет.')
                    continue
                picked = menu('Какой профиль удалить? Сама настройка сервиса не изменится.',
                              [(n, profile_label(n, d)) for n, d in entries], tags=True)
                if not picked:
                    continue
                if dialog(['--yesno', f'Удалить профиль "{picked}"? Вернуть его через меню будет нельзя.', '10', '{W}']) is not None:
                    privileged('profile-delete', picked)
        except (ValueError, RuntimeError, OSError, subprocess.TimeoutExpired) as e:
            show(f'Ошибка: {e}\n\nТекущая настройка доступна через /opt/zapret-discord-youtube-linux/service.sh')


def main():
    parser = argparse.ArgumentParser(description='Zapret Console — управление обходом DPI в Linux')
    parser.add_argument('--version', action='version', version=f'%(prog)s {VERSION}')
    parser.add_argument('--admin', help=argparse.SUPPRESS, choices=['start', 'stop', 'restart', 'enable', 'disable',
                                         'strategy', 'interface', 'save-good', 'restore-good', 'restore-previous', 'runtime',
                                         'profile-save', 'profile-replace', 'profile-restore', 'profile-delete'])
    parser.add_argument('--value', help=argparse.SUPPRESS)
    parser.add_argument('--json', action='store_true', help='Машиночитаемый статус (с --status)')
    parser.add_argument('--status', action='store_true')
    parser.add_argument('--diagnose', action='store_true')
    parser.add_argument('--doctor', action='store_true', help='Проверить зависимости и подключение адаптера')
    args = parser.parse_args()
    load_settings()
    if args.json and not args.status:
        parser.error('--json используется вместе с --status')
    if args.admin:
        if os.geteuid() != 0:
            raise RuntimeError('Для системного изменения требуются права администратора')
        if args.admin == 'runtime':
            admin('runtime')
            return
        STATE.mkdir(parents=True, exist_ok=True)
        trusted(STATE)
        with (STATE / '.lock').open('a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError('Другое изменение уже выполняется. Попробуй ещё раз после его завершения.')
            admin(args.admin, args.value)
        return
    if args.doctor:
        errors = preflight()
        print('\n'.join(errors) if errors else f'Зависимости найдены. Адаптер: {ROOT}\nСервис: {UNIT}')
        if errors:
            raise SystemExit(1)
        return
    if args.status:
        print(json.dumps(status_data(), ensure_ascii=False) if args.json else status())
        return
    if args.diagnose:
        print(diagnose())
        return
    if not sys.stdin.isatty():
        raise RuntimeError('Запусти zapret-console в терминале; для скриптов есть --status и --diagnose')
    errors = preflight()
    if errors:
        raise RuntimeError('\n'.join(errors) + '\nИнструкция: README.md → Установка')
    while True:
        try:
            choice = menu(status(), [
                ('toggle', 'Остановить' if active() else 'Включить'),
                ('restart', 'Перезапустить'),
                ('strategy', 'Выбрать стратегию'),
                ('good', 'Сохранённый профиль: сохранить / восстановить'),
                ('diagnose', 'Проверить Discord и сетевой путь'),
                ('logs', 'Последние сообщения сервиса'),
                ('interface', 'Выбрать сетевой интерфейс'),
                ('autostart', 'Настроить автозапуск'),
                ('exit', 'Выйти')])
            if choice in (None, 'exit'):
                return
            if choice == 'toggle':
                privileged('stop' if active() else 'start')
            elif choice == 'restart':
                privileged('restart')
            elif choice == 'strategy':
                current = config()['strategy']
                known = json.loads(KNOWN.read_text())['strategy'] if KNOWN.exists() else ''
                entries = [(s, ('Сейчас' if s == current else '') + (' · Сохранена' if s == known else '')) for s in strategies()]
                selected = menu('Выбери стратегию. Активный сервис перезапустится.', entries, current, tags=True)
                if selected and selected != current:
                    privileged('strategy', selected)
            elif choice == 'good':
                saved = json.loads(KNOWN.read_text()) if KNOWN.exists() else None
                text = f"Сохранено: {saved['strategy']} / {saved['interface']}" if saved else 'Сохранённого профиля пока нет'
                selected = menu(text, [('restore-good', 'Восстановить сохранённый профиль'),
                                       ('restore-previous', 'Отменить последнее изменение настроек'),
                                       ('save-good', 'Сохранить текущую рабочую настройку'),
                                       ('profiles', 'Именованные профили: сохранить / восстановить / удалить')])
                if selected == 'save-good':
                    confirmed = dialog(['--yesno', 'Discord работает с текущей настройкой? Сохранить её вместо прежней рабочей?', '10', '{W}'])
                    if confirmed is not None:
                        privileged(selected)
                elif selected in ('restore-good', 'restore-previous'):
                    privileged(selected)
                elif selected == 'profiles':
                    profiles_menu()
            elif choice == 'diagnose':
                subprocess.run(['clear'], check=False)
                show(diagnose())
            elif choice == 'logs':
                r = command(['journalctl', '-u', UNIT, '-n', '60', '--no-pager', '-o', 'short'])
                show(r.stdout + r.stderr)
            elif choice == 'interface':
                entries = [('any', 'Все интерфейсы')] + [(n, '') for n in sorted(os.listdir('/sys/class/net')) if n != 'lo']
                selected = menu('Выбери интерфейс обычного подключения к интернету.', entries, config()['interface'], tags=True)
                if selected and selected != config()['interface']:
                    privileged('interface', selected)
            elif choice == 'autostart':
                selected = menu('Автозапуск управляет запуском при загрузке системы.',
                                [('enable', 'Включить'), ('disable', 'Выключить')])
                if selected:
                    privileged(selected)
        except (ValueError, RuntimeError, OSError, subprocess.TimeoutExpired) as e:
            show(f'Ошибка: {e}\n\nТекущая настройка доступна через /opt/zapret-discord-youtube-linux/service.sh')


def entrypoint():
    try:
        main()
    except KeyboardInterrupt:
        print('\nВыход.')
    except Exception as e:
        print(f'Ошибка: {e}', file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    entrypoint()
