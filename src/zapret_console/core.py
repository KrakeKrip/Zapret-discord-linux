"""Shared adapter management: configuration, profiles and service operations.

The module is independent of terminal interfaces: no whiptail, no input(),
no terminal output; operations take an explicit BackendContext, return data
and raise errors. Importing the module and building a context performs no
systemctl or sudo calls and changes no files. Administrative changes go
through admin_command, which checks root, trusts the affected paths and
serializes mutations with the STATE/.lock lock.
"""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile

DEFAULT_ROOT = Path('/opt/zapret-discord-youtube-linux')
DEFAULT_STATE = Path('/var/lib/zapret-console')
DEFAULT_UNIT = 'zapret_discord_youtube.service'
SETTINGS_PATH = Path('/etc/zapret-console/settings.json')
FIELDS = ('interface', 'gamefiltertcp', 'gamefilterudp', 'strategy', 'firewall_backend')

# File-changing actions that verify the caller's expected_revision under the lock.
REVISION_ACTIONS = frozenset({'strategy', 'interface', 'save-good', 'restore-good', 'restore-previous',
                              'profile-save', 'profile-replace', 'profile-restore', 'profile-delete'})


class BusyError(RuntimeError):
    """Another process holds the shared administrative lock."""


class ConflictError(RuntimeError):
    """Files changed since the caller read their revision; nothing was written."""


class BackendContext:
    """Paths and service identity of one adapter installation."""

    def __init__(self, root=DEFAULT_ROOT, state=DEFAULT_STATE, unit=DEFAULT_UNIT):
        self.root = Path(root)
        self.state = Path(state)
        self.unit = unit
        self.known = self.state / 'known-good.json'
        self.lock = self.state / '.lock'

    @classmethod
    def from_settings(cls, path=SETTINGS_PATH):
        """Context from the installed settings file; defaults when it is absent."""
        root, unit = str(DEFAULT_ROOT), DEFAULT_UNIT
        if path.exists():
            trusted(path)
            settings = json.loads(path.read_text())
            root = settings.get('backend_root', root)
            unit = settings.get('service', unit)
            if not isinstance(root, str) or not Path(root).is_absolute():
                raise ValueError('backend_root должен быть абсолютным путём')
            if not isinstance(unit, str) or not re.fullmatch(r'[A-Za-z0-9_.@-]+\.service', unit):
                raise ValueError('Недопустимое имя сервиса')
        return cls(root=root, unit=unit)


def trusted(path):
    """Root actions may only use administrator-controlled files and directories."""
    resolved = path.resolve(strict=True)
    for node in (resolved, *resolved.parents):
        st = node.stat()
        if st.st_uid != 0 or st.st_mode & stat.S_IWOTH or (st.st_mode & stat.S_IWGRP and st.st_gid != 0):
            raise RuntimeError(f'Путь доступен для изменения обычному пользователю: {node}')


def command(args, timeout=20):
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout)


def preflight(ctx):
    errors = []
    for name in ('systemctl', 'ip', 'curl', 'whiptail', 'sudo'):
        if not shutil.which(name):
            errors.append(f'Не найдена утилита: {name}')
    if not (ctx.root / 'conf.env').is_file():
        errors.append(f'Не найден конфиг адаптера: {ctx.root / "conf.env"}')
    if not (ctx.root / 'nfqws').is_file():
        errors.append(f'Не найден движок: {ctx.root / "nfqws"}')
    return errors


def strategies(ctx):
    names = set()
    for folder in ('custom-strategies', 'zapret-latest'):
        for p in (ctx.root / folder).glob('*.bat'):
            if re.fullmatch(r'[A-Za-z0-9_.-]+\.bat', p.name):
                names.add(p.name)
    return sorted(names)


def validate(ctx, c):
    if set(c) != set(FIELDS):
        raise ValueError('Неполная конфигурация')
    if c['interface'] != 'any' and c['interface'] not in os.listdir('/sys/class/net'):
        raise ValueError('Сетевой интерфейс отсутствует')
    if not re.fullmatch(r'[A-Za-z0-9_.:-]+', c['interface']):
        raise ValueError('Недопустимое имя интерфейса')
    if c['strategy'] not in strategies(ctx):
        raise ValueError('Стратегия отсутствует')
    if c['gamefiltertcp'] not in ('true', 'false') or c['gamefilterudp'] not in ('true', 'false'):
        raise ValueError('Некорректные настройки GameFilter')
    if c['firewall_backend'] not in ('auto', 'nftables', 'iptables'):
        raise ValueError('Некорректный бэкенд')
    return c


def config(ctx):
    result = {}
    for line in (ctx.root / 'conf.env').read_text().splitlines():
        key, sep, value = line.partition('=')
        if sep and key in FIELDS:
            result[key] = value.strip()
    result.setdefault('firewall_backend', 'auto')
    return validate(ctx, result)


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


def write_config(ctx, c):
    validate(ctx, c)
    atomic_write(ctx.root / 'conf.env', ''.join(f'{k}={c[k]}\n' for k in FIELDS))


def active(ctx):
    return command(['systemctl', 'is-active', ctx.unit]).returncode == 0


def systemctl(ctx, action):
    r = command(['systemctl', action, ctx.unit], timeout=30)
    if r.returncode:
        raise RuntimeError(r.stderr.strip() or r.stdout.strip() or 'systemctl завершился с ошибкой')


def apply_config(ctx, new):
    old = config(ctx)
    was_active = active(ctx)
    validate(ctx, new)
    atomic_write(ctx.state / 'previous.json', json.dumps(old, indent=2))
    write_config(ctx, new)
    if was_active:
        try:
            systemctl(ctx, 'restart')
            # Wait for the adapter to finish its own one-second initialization.
            import time
            time.sleep(2)
            if not active(ctx):
                raise RuntimeError('Сервис не запустился')
        except Exception as e:
            write_config(ctx, old)
            try:
                systemctl(ctx, 'restart')
            except Exception as restore_error:
                raise RuntimeError(f'{e}. Конфигурация возвращена, но перезапуск не удался: {restore_error}')
            raise RuntimeError(f'{e}. Предыдущая конфигурация восстановлена.')


PROFILE_NAME = r'[A-Za-z0-9][A-Za-z0-9_-]{0,47}'
PROFILE_NAME_HINT = ('Имя профиля: 1–48 символов, латинские буквы и цифры, '
                     'внутри также "_" и "-". Первый символ — буква или цифра; точки, пробелы и '
                     'разделители пути нельзя.')


def profiles_dir(ctx):
    return ctx.state / 'profiles'


def profile_path(ctx, name):
    if not isinstance(name, str) or not re.fullmatch(PROFILE_NAME, name):
        raise ValueError(PROFILE_NAME_HINT)
    return profiles_dir(ctx) / f'{name}.json'


def check_profiles_dir(ctx, create=False):
    """Reject symlinked profiles dir; for creation also require trusted owners (real trusted)."""
    d = profiles_dir(ctx)
    if d.is_symlink():
        raise RuntimeError('Каталог профилей не может быть символической ссылкой')
    if create:
        if d.is_dir():
            trusted(d)
        elif d.exists():
            raise RuntimeError(f'{d} должен быть каталогом профилей')
        else:
            trusted(ctx.state)
            d.mkdir(parents=True)
            # Ordinary users need read access for the unprivileged listing.
            os.chmod(d, 0o755)
            trusted(d)
    return d


def _profile_from_bytes(data, name=None):
    label = (f'Профиль повреждён: {name} не содержит конфигурацию из пяти полей' if name
             else 'Профиль повреждён: ожидается конфигурация из пяти полей')
    try:
        parsed = json.loads(data)
    except ValueError:
        raise ValueError(label)
    if not isinstance(parsed, dict) or set(parsed) != set(FIELDS):
        raise ValueError(label)
    return parsed


def read_profile(path):
    return _profile_from_bytes(path.read_bytes(), path.name)


def profile_entries(ctx):
    """Sorted [(name, config)] for menus; a damaged profile yields None instead of config."""
    d = check_profiles_dir(ctx)
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


def profile_op(ctx, action, name):
    """Admin-side profile storage; revalidates name and paths independently of the menu."""
    path = profile_path(ctx, name)
    check_profiles_dir(ctx, create=action == 'profile-save')
    if action == 'profile-save':
        if path.is_symlink():
            raise RuntimeError('Файл профиля не может быть символической ссылкой')
        if path.exists():
            raise RuntimeError(f'Профиль "{name}" уже существует. Замена требует отдельного подтверждения.')
        atomic_write(path, json.dumps(config(ctx), ensure_ascii=False, indent=2))
        return
    if path.is_symlink():
        raise RuntimeError('Файл профиля не может быть символической ссылкой')
    if not path.is_file():
        raise RuntimeError(f'Профиль "{name}" не найден')
    trusted(path)
    if action == 'profile-replace':
        atomic_write(path, json.dumps(config(ctx), ensure_ascii=False, indent=2))
    elif action == 'profile-restore':
        apply_config(ctx, validate(ctx, read_profile(path)))
    elif action == 'profile-delete':
        os.unlink(path)


def _read_file_state(path):
    """(status, bytes) with status ok/absent/error; absence is a normal state."""
    try:
        return 'ok', path.read_bytes()
    except FileNotFoundError:
        return 'absent', None
    except OSError:
        return 'error', None


def _config_from_bytes(ctx, data):
    result = {}
    for line in data.decode('utf-8').splitlines():
        key, sep, value = line.partition('=')
        if sep and key in FIELDS:
            result[key] = value.strip()
    result.setdefault('firewall_backend', 'auto')
    return validate(ctx, result)


def snapshot(ctx):
    """Read-only view of the backend plus an opaque revision string.

    The revision hashes the backend identity (root/unit) and the exact bytes
    of conf.env, known-good.json, previous.json and every valid named
    profile; absent files and directories are represented explicitly and are
    a normal, fully readable state. Lock contents, temporary files, mtimes
    and systemd's volatile state are not part of it. Each file is read once
    for both its data and its revision bytes, and symlinks are never opened
    in place of the profiles dir or a named profile. Reading needs no root
    and changes no files.

    When some bytes cannot be read or the configuration is invalid, the
    snapshot is not safe to compare against: `revision` is then None and
    `revision_error` names the cause, while config_error/profiles_error and
    per-profile errors keep their details. A corrupt but readable named
    profile still yields a valid revision (its bytes are known, so it can be
    deleted or replaced).
    """
    problems = []
    hasher = hashlib.sha256()

    def feed(label, status, content):
        hasher.update(label.encode('utf-8') + b'\0')
        if status == 'ok':
            hasher.update(b'bytes\0' + str(len(content)).encode('ascii') + b'\0' + content)
        else:
            hasher.update(status.encode('ascii') + b'\0')

    def read_once(label, path):
        status, data = _read_file_state(path)
        feed(label, status, data)
        return status, data

    result = {'root': str(ctx.root), 'unit': ctx.unit, 'revision': None, 'revision_error': None,
              'config': None, 'config_error': None, 'service_state': 'unknown',
              'autostart': 'unknown', 'profiles': [], 'profiles_error': None}

    feed('backend-root', 'ok', str(ctx.root).encode('utf-8'))
    feed('unit', 'ok', ctx.unit.encode('utf-8'))

    status, data = read_once('conf.env', ctx.root / 'conf.env')
    if status == 'ok':
        try:
            result['config'] = _config_from_bytes(ctx, data)
        except (ValueError, OSError) as e:
            result['config_error'] = str(e)
            problems.append(f'конфигурация не прошла проверку: {e}')
    elif status == 'absent':
        result['config_error'] = f'Не найден конфиг адаптера: {ctx.root / "conf.env"}'
        problems.append(f'отсутствует {ctx.root / "conf.env"}')
    else:
        result['config_error'] = f'Не удалось прочитать: {ctx.root / "conf.env"}'
        problems.append(f'не удалось прочитать {ctx.root / "conf.env"}')

    for label, path in (('known-good.json', ctx.known), ('previous.json', ctx.state / 'previous.json')):
        if read_once(label, path)[0] == 'error':
            problems.append(f'не удалось прочитать {path}')

    d = profiles_dir(ctx)
    if d.is_symlink():
        feed('profiles-dir', 'symlink', None)
        result['profiles_error'] = 'Каталог профилей не может быть символической ссылкой'
        problems.append(f'{d} — символическая ссылка')
    elif d.is_dir():
        feed('profiles-dir', 'ok', b'dir')
        try:
            entries = sorted(d.iterdir())
        except OSError as e:
            entries = None
            result['profiles_error'] = f'Не удалось перечислить {d}: {e}'
            problems.append(f'не удалось перечислить {d}: {e}')
        if entries is not None:
            for p in entries:
                m = re.fullmatch(f'({PROFILE_NAME})\\.json', p.name)
                if not m:
                    continue
                name = m.group(1)
                if p.is_symlink():
                    feed(f'profile:{name}', 'symlink', None)
                    result['profiles'].append({'name': name, 'config': None,
                                               'error': 'Файл профиля не может быть символической ссылкой'})
                    problems.append(f'профиль {name} — символическая ссылка')
                    continue
                if not p.is_file():
                    continue
                pstatus, pdata = _read_file_state(p)
                feed(f'profile:{name}', pstatus, pdata)
                entry = {'name': name, 'config': None, 'error': None}
                if pstatus == 'ok':
                    try:
                        entry['config'] = _profile_from_bytes(pdata, name)
                    except (ValueError, OSError) as e:
                        entry['error'] = str(e)
                else:
                    entry['error'] = f'Не удалось прочитать профиль: {name}'
                    problems.append(f'не удалось прочитать профиль {name}')
                result['profiles'].append(entry)
    elif d.exists():
        feed('profiles-dir', 'other', None)
        result['profiles_error'] = f'{d} должен быть каталогом профилей'
        problems.append(f'{d} должен быть каталогом профилей')
    else:
        feed('profiles-dir', 'absent', None)

    result['service_state'] = command(['systemctl', 'is-active', ctx.unit]).stdout.strip() or 'unknown'
    result['autostart'] = command(['systemctl', 'is-enabled', ctx.unit]).stdout.strip() or 'unknown'
    if problems:
        # Bytes were not fully read, so no comparison against them is safe.
        result['revision_error'] = 'Состояние прочитано не полностью: ' + '; '.join(problems)
    else:
        result['revision'] = hasher.hexdigest()
    return result


def _admin_locked(ctx, action, value=None, expected_revision=None):
    """Dispatch trusted to run only under the shared lock; all checks re-run here."""
    trusted(ctx.root)
    trusted(ctx.root / 'conf.env')
    trusted(ctx.root / 'nfqws')
    for path in ctx.root.rglob('*.sh'):
        trusted(path)
    if expected_revision is not None and action in REVISION_ACTIONS:
        snap = snapshot(ctx)
        if snap['revision'] is None:
            # Never compare error markers and never report this as a conflict:
            # the state could not be read fully enough for a safe comparison.
            raise RuntimeError(f'Мутация отклонена: {snap["revision_error"]}')
        if snap['revision'] != expected_revision:
            raise ConflictError('Данные изменились с момента чтения. Обнови состояние и подтверди действие заново.')
    if action in ('start', 'stop', 'restart', 'enable', 'disable'):
        systemctl(ctx, action)
    elif action == 'strategy':
        new = config(ctx)
        new['strategy'] = value
        apply_config(ctx, new)
    elif action == 'interface':
        new = config(ctx)
        new['interface'] = value
        apply_config(ctx, new)
    elif action == 'save-good':
        atomic_write(ctx.known, json.dumps(config(ctx), ensure_ascii=False, indent=2))
    elif action == 'restore-good':
        trusted(ctx.known)
        apply_config(ctx, validate(ctx, json.loads(ctx.known.read_text())))
    elif action == 'restore-previous':
        previous = ctx.state / 'previous.json'
        trusted(previous)
        apply_config(ctx, validate(ctx, json.loads(previous.read_text())))
    elif action in ('profile-save', 'profile-replace', 'profile-restore', 'profile-delete'):
        profile_op(ctx, action, value)
    else:
        raise ValueError('Неизвестное действие')


def admin_command(ctx, action, value=None, expected_revision=None):
    """Single entry point for administrative changes from any interface.

    Checks root, keeps the read-only runtime action lock-free and serializes
    every mutation (check, write, restart, rollback) with the shared
    STATE/.lock flock; refuses without blocking when the lock is busy.
    With expected_revision set for a file-changing action the revision is
    recomputed under the lock after the trust checks and before any write;
    a mismatch raises ConflictError and nothing is changed. Returns data
    for read-only actions, None for mutations.
    """
    if os.geteuid() != 0:
        raise RuntimeError('Для системного изменения требуются права администратора')
    if action == 'runtime':
        from .diagnostics import runtime_snapshot
        return runtime_snapshot(ctx.unit)
    ctx.state.mkdir(parents=True, exist_ok=True)
    trusted(ctx.state)
    with ctx.lock.open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise BusyError('Другое изменение уже выполняется. Попробуй ещё раз после его завершения.')
        _admin_locked(ctx, action, value, expected_revision)
