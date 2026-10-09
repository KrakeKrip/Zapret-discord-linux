"""UI-independent client for privileged operations (internal protocol v1).

Reads snapshots directly (read-only, no root) and executes fixed
administrative actions through the installed launcher's --request-json
machine endpoint, started as a separate process. No print/input/clear/
whiptail here and no Qt/Textual imports; results come back as structured
data and errors are raised only for programmer mistakes.

Request:  {"protocol": 1, "action": str, "value": str|null, "expected_revision": str|null}
Response: {"protocol": 1, "ok": bool, "code": str, "message": str, "data": ...}

Endpoint codes: ok, busy, conflict, invalid_request, permission_denied,
operation_failed. A reply is trusted only when ok/code are consistent
(ok:true with code ok, ok:false with one of the five error codes) and the
exit code matches (0 for ok:true, 1 for ok:false); contradictions, unknown
codes or unparseable output become transport_error, since the result of the
operation is then unknown. The client itself adds transport_error,
auth_cancelled and auth_failed: cancelled or failed authorization is
recognized only on the pkexec transport (exit 126/127 without a valid
reply). Requests are never repeated automatically; after a timeout the
interface must re-read the state.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import core

LAUNCHER = '/usr/local/bin/zapret-console'
PROTOCOL = 1
REQUEST_TIMEOUT = 120

# Codes the helper v1 may send; auth_* and transport_error are client-side only.
HELPER_CODES = frozenset({'ok', 'busy', 'conflict', 'invalid_request',
                          'permission_denied', 'operation_failed'})


def snapshot(context=None):
    """Read-only backend state with revision; needs no root and writes nothing."""
    ctx = context if context is not None else core.BackendContext.from_settings()
    return core.snapshot(ctx)


def make_request(action, value=None, expected_revision=None):
    return {'protocol': PROTOCOL, 'action': action, 'value': value,
            'expected_revision': expected_revision}


def _error(code, message):
    return {'protocol': PROTOCOL, 'ok': False, 'code': code, 'message': message, 'data': None}


def _parse_response(text):
    """(response, None) for a valid, self-consistent helper v1 reply; (None, reason) otherwise."""
    try:
        data = json.loads(text)
    except ValueError:
        return None, 'stdout не является корректным JSON'
    if not isinstance(data, dict) or set(data) != {'protocol', 'ok', 'code', 'message', 'data'}:
        return None, 'структура ответа не соответствует протоколу'
    if type(data['protocol']) is not int or data['protocol'] != PROTOCOL:
        return None, 'несовместимая версия протокола'
    if type(data['ok']) is not bool or not isinstance(data['code'], str) or not isinstance(data['message'], str):
        return None, 'некорректные поля ok/code/message'
    if data['code'] not in HELPER_CODES:
        return None, f'неизвестный код ответа {data["code"]!r}'
    if (data['code'] == 'ok') != data['ok']:
        return None, f'код {data["code"]!r} противоречит ok={data["ok"]}'
    return data, None


def _run(argv, stdin, transport, timeout):
    """Run the helper once; transport is 'direct', 'sudo' or 'pkexec'.

    Only a structurally valid reply with consistent ok/code and the matching
    exit code (0 for ok:true, 1 for ok:false) is passed through. Contradictory
    or unparseable output becomes transport_error: the result of the operation
    is then unknown, so the interface must re-read the state. Exit 126/127 is
    mapped to auth_cancelled/auth_failed only for the pkexec transport.
    """
    r = subprocess.run(argv, stdin=stdin, stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE if transport == 'pkexec' else None,
                       text=True, timeout=timeout)
    parsed, reason = _parse_response(r.stdout)
    if parsed is not None:
        if r.returncode == (0 if parsed['ok'] else 1):
            return parsed
        return _error('transport_error',
                      f'Ответ launcher (ok={parsed["ok"]}, код {parsed["code"]}) противоречит '
                      f'коду выхода {r.returncode}. Результат операции неизвестен — '
                      'перечитай состояние перед новыми действиями.')
    if transport == 'pkexec' and r.returncode == 126:
        return _error('auth_cancelled', 'Авторизация отменена')
    if transport == 'pkexec' and r.returncode == 127:
        return _error('auth_failed', 'Авторизация не выполнена')
    return _error('transport_error',
                  f'Launcher не вернул корректный ответ ({reason}; код выхода {r.returncode}). '
                  'Результат операции неизвестен — перечитай состояние перед новыми действиями.')


def request(body, mode='terminal', timeout=REQUEST_TIMEOUT):
    """Execute one request via the installed launcher; never retries.

    mode 'terminal' asks for the password through sudo in the inherited TTY;
    mode 'gui' uses pkexec with the desktop agent and captured output. An
    already-root caller runs the launcher directly without elevation.
    """
    launcher = Path(LAUNCHER)
    if launcher.is_symlink() or not launcher.is_file():
        return _error('transport_error', f'Установленный launcher не найден: {LAUNCHER}')
    try:
        core.trusted(launcher)
    except (RuntimeError, OSError) as e:
        return _error('transport_error', f'Launcher не доверенный: {e}')
    payload = json.dumps(body, ensure_ascii=False)
    try:
        if os.geteuid() == 0:
            return _run([LAUNCHER, '--request-json', payload],
                        stdin=subprocess.DEVNULL, transport='direct', timeout=timeout)
        if mode == 'gui':
            if not shutil.which('pkexec'):
                return _error('transport_error', 'Не найдена утилита pkexec')
            return _run(['pkexec', '--disable-internal-agent', LAUNCHER, '--request-json', payload],
                        stdin=subprocess.DEVNULL, transport='pkexec', timeout=timeout)
        if not shutil.which('sudo'):
            return _error('transport_error', 'Не найдена утилита sudo')
        if not sys.stdin.isatty():
            return _error('auth_failed', 'Нет терминала для ввода пароля. Открой интерфейс в терминале или используй режим gui.')
        return _run(['sudo', '--', LAUNCHER, '--request-json', payload],
                    stdin=None, transport='sudo', timeout=timeout)
    except subprocess.TimeoutExpired:
        return _error('transport_error',
                      'Время ожидания истекло; результат операции неизвестен. Перечитай состояние перед новыми действиями.')
    except OSError as e:
        return _error('transport_error', f'Не удалось запустить launcher: {e}')
