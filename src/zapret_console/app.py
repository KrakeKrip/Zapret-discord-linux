#!/usr/bin/env python3
"""Zapret Console CLI: whiptail menu, status, diagnostics and user interaction.

All adapter operations delegate to zapret_console.core; this module owns
argument parsing, dialogs, message texts and exit codes.
"""
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

from . import core
from .core import BackendContext

VERSION = '0.2.0'
LAUNCHER = '/usr/local/bin/zapret-console'

VALUE_ACTIONS = frozenset({'strategy', 'interface', 'profile-save', 'profile-replace',
                           'profile-restore', 'profile-delete'})
NO_VALUE_ACTIONS = frozenset({'start', 'stop', 'restart', 'enable', 'disable',
                              'save-good', 'restore-good', 'restore-previous', 'runtime'})


def load_context():
    return BackendContext.from_settings()


def _response(ok, code, message, data=None):
    return {'protocol': 1, 'ok': ok, 'code': code, 'message': message, 'data': data}


def parse_request(raw):
    """Validate one --request-json payload; raises ValueError on any deviation."""
    if len(raw.encode('utf-8')) > 65536:
        raise ValueError('Размер запроса превышает 64 KiB')
    try:
        data = json.loads(raw)
    except ValueError:
        raise ValueError('Запрос не является корректным JSON')
    if not isinstance(data, dict) or set(data) != {'protocol', 'action', 'value', 'expected_revision'}:
        raise ValueError('Запрос должен содержать ровно поля protocol, action, value, expected_revision')
    if type(data['protocol']) is not int or data['protocol'] != 1:
        raise ValueError('Неподдерживаемая версия протокола')
    action = data['action']
    if not isinstance(action, str) or (action not in VALUE_ACTIONS and action not in NO_VALUE_ACTIONS):
        raise ValueError('Неизвестное действие')
    value, revision = data['value'], data['expected_revision']
    if action in VALUE_ACTIONS:
        if not isinstance(value, str):
            raise ValueError('Для этого действия value должен быть строкой')
    elif value is not None:
        raise ValueError('Для этого действия value должен быть null')
    if action in core.REVISION_ACTIONS:
        if not isinstance(revision, str) or not revision:
            raise ValueError('Для этого действия требуется ожидаемая revision — непустая строка')
    elif revision is not None:
        raise ValueError('Для этого действия expected_revision должен быть null')
    return {'action': action, 'value': value, 'expected_revision': revision}


def request_endpoint(raw, context=None):
    """Machine endpoint for --request-json; returns (payload, exit_code).

    stdout carries exactly one JSON object with protocol/ok/code/message/data;
    codes: ok, busy, conflict, invalid_request, permission_denied,
    operation_failed.
    """
    try:
        parsed = parse_request(raw)
    except ValueError as e:
        return _response(False, 'invalid_request', str(e)), 1
    try:
        ctx = context if context is not None else load_context()
    except Exception as e:
        return _response(False, 'operation_failed', f'Настройки недоступны: {e}'), 1
    if os.geteuid() != 0:
        return _response(False, 'permission_denied', 'Для системного изменения требуются права администратора'), 1
    try:
        result = core.admin_command(ctx, parsed['action'], parsed['value'], parsed['expected_revision'])
    except core.BusyError as e:
        return _response(False, 'busy', str(e)), 1
    except core.ConflictError as e:
        return _response(False, 'conflict', str(e)), 1
    except (ValueError, RuntimeError, OSError, subprocess.TimeoutExpired) as e:
        return _response(False, 'operation_failed', str(e)), 1
    return _response(True, 'ok', '', result), 0


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


def status_data(ctx):
    c = core.config(ctx)
    state = core.command(['systemctl', 'is-active', ctx.unit]).stdout.strip() or 'unknown'
    enabled = core.command(['systemctl', 'is-enabled', ctx.unit]).stdout.strip() or 'unknown'
    return {'version': VERSION, 'service': ctx.unit, 'state': state, 'autostart': enabled, 'config': c}


def status(ctx):
    c = core.config(ctx)
    state = 'РАБОТАЕТ' if core.active(ctx) else 'ОСТАНОВЛЕН'
    auto = core.command(['systemctl', 'is-enabled', ctx.unit]).returncode == 0
    return f"{state} · автозапуск {'включён' if auto else 'выключен'}\nСтратегия: {c['strategy']} · интерфейс: {c['interface']}"


def gateway_probe():
    from .diagnostics import gateway_probe as probe
    return probe()


def get_runtime(ctx):
    from .diagnostics import runtime_snapshot
    if os.geteuid() == 0:
        return runtime_snapshot(ctx.unit)
    if not Path(LAUNCHER).is_file():
        return runtime_snapshot(ctx.unit)
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
    return runtime_snapshot(ctx.unit)


def diagnose(ctx):
    from .diagnostics import collect_diagnostics
    print('\nПроверка текущего сетевого пути. Это может занять некоторое время…', flush=True)
    print('Проверка firewall и очереди может запросить пароль sudo.', flush=True)
    result = collect_diagnostics(ctx, runtime_reader=lambda: get_runtime(ctx),
                                 gateway=gateway_probe,
                                 progress=lambda text: print('  ' + text, flush=True))
    report = result['report']
    dest = Path(os.environ.get('XDG_STATE_HOME', str(Path.home() / '.local/state'))) / 'zapret-console/diagnostics.txt'
    core.atomic_write(dest, report + '\n')
    return report + f'\n\nОтчёт сохранён: {dest}'


def profile_label(name, data):
    if data is None:
        return f'{name} — повреждён, недоступен для восстановления'
    return f'{name} — {data["strategy"]} · интерфейс: {data["interface"]}'


def profiles_menu(ctx):
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
                name = dialog(['--inputbox', 'Введи имя нового профиля. ' + core.PROFILE_NAME_HINT, '10', '{W}'])
                if name is None:
                    continue
                # whiptail may append a newline to the form result; typed spaces stay rejected.
                name = name.rstrip('\n')
                core.profile_path(ctx, name)
                target = core.profiles_dir(ctx) / f'{name}.json'
                if target.exists():
                    if dialog(['--yesno', f'Профиль "{name}" уже существует. Заменить его текущей настройкой?', '10', '{W}']) is None:
                        continue
                    privileged('profile-replace', name)
                else:
                    privileged('profile-save', name)
            elif selected == 'restore':
                entries = core.profile_entries(ctx)
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
                entries = core.profile_entries(ctx)
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
    parser.add_argument('--gui', action='store_true', help='Открыть графическое окно (нужен пакет zapret-console[gui])')
    parser.add_argument('--tui', action='store_true', help='Открыть терминальное приложение Textual')
    parser.add_argument('--legacy-menu', action='store_true', help='Открыть прежнее whiptail-меню')
    parser.add_argument('--request-json', help=argparse.SUPPRESS, metavar='JSON')
    args = parser.parse_args()
    if args.request_json is not None:
        if args.admin or args.status or args.diagnose or args.doctor or args.json or args.gui or args.tui or args.legacy_menu:
            payload, code = _response(False, 'invalid_request', '--request-json не совмещается с другими режимами'), 1
        else:
            try:
                payload, code = request_endpoint(args.request_json)
            except Exception as e:
                payload, code = _response(False, 'operation_failed', f'Внутренняя ошибка: {e}'), 1
        print(json.dumps(payload, ensure_ascii=False))
        raise SystemExit(code)
    if args.tui and (args.gui or args.legacy_menu or args.admin or args.status or args.diagnose or args.doctor or args.json):
        parser.error("--tui не совмещается с другими режимами")
    if args.legacy_menu and (args.gui or args.admin or args.status or args.diagnose or args.doctor or args.json):
        parser.error("--legacy-menu не совмещается с другими режимами")
    if args.gui:
        if args.admin or args.status or args.diagnose or args.doctor or args.json:
            parser.error('--gui не совмещается с другими режимами')
        try:
            from .gui.app import run_gui
        except ImportError:
            print('GUI-модули не установлены. Графический интерфейс пока доступен из исходников:\n'
                  '  python3 -m venv .venv\n'
                  '  .venv/bin/pip install ".[gui]"\n'
                  '  .venv/bin/python -m zapret_console --gui')
            raise SystemExit(1)
        raise SystemExit(run_gui())
    ctx = load_context()
    if args.json and not args.status:
        parser.error('--json используется вместе с --status')
    if args.admin:
        result = core.admin_command(ctx, args.admin, args.value)
        print(json.dumps(result) if args.admin == 'runtime' else 'Готово.')
        return
    if args.doctor:
        errors = core.preflight(ctx)
        print('\n'.join(errors) if errors else f'Зависимости найдены. Адаптер: {ctx.root}\nСервис: {ctx.unit}')
        if errors:
            raise SystemExit(1)
        return
    if args.status:
        print(json.dumps(status_data(ctx), ensure_ascii=False) if args.json else status(ctx))
        return
    if args.diagnose:
        print(diagnose(ctx))
        return
    if not args.legacy_menu:
        try:
            from .tui.app import run_tui
        except ImportError:
            raise RuntimeError('TUI-модули пока доступны из исходников; прежнее меню: --legacy-menu')
        raise SystemExit(run_tui())
    if not sys.stdin.isatty():
        raise RuntimeError('Запусти zapret-console в терминале; для скриптов есть --status и --diagnose')
    errors = core.preflight(ctx)
    if errors:
        raise RuntimeError('\n'.join(errors) + '\nИнструкция: README.md → Установка')
    while True:
        try:
            choice = menu(status(ctx), [
                ('toggle', 'Остановить' if core.active(ctx) else 'Включить'),
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
                privileged('stop' if core.active(ctx) else 'start')
            elif choice == 'restart':
                privileged('restart')
            elif choice == 'strategy':
                current = core.config(ctx)['strategy']
                known = json.loads(ctx.known.read_text())['strategy'] if ctx.known.exists() else ''
                entries = [(s, ('Сейчас' if s == current else '') + (' · Сохранена' if s == known else '')) for s in core.strategies(ctx)]
                selected = menu('Выбери стратегию. Активный сервис перезапустится.', entries, current, tags=True)
                if selected and selected != current:
                    privileged('strategy', selected)
            elif choice == 'good':
                saved = json.loads(ctx.known.read_text()) if ctx.known.exists() else None
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
                    profiles_menu(ctx)
            elif choice == 'diagnose':
                subprocess.run(['clear'], check=False)
                show(diagnose(ctx))
            elif choice == 'logs':
                from .diagnostics import journal_snapshot
                result = journal_snapshot(ctx, lines=60)
                show(result['text'] + '\n' + result['warning'])
            elif choice == 'interface':
                entries = [('any', 'Все интерфейсы')] + [(n, '') for n in sorted(os.listdir('/sys/class/net')) if n != 'lo']
                selected = menu('Выбери интерфейс обычного подключения к интернету.', entries, core.config(ctx)['interface'], tags=True)
                if selected and selected != core.config(ctx)['interface']:
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
