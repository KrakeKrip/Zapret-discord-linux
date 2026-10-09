"""Read-only runtime evidence; unknown states are distinct from failures."""
import json
from pathlib import Path
import re
import subprocess
import socket
import ssl

from . import core


def runtime_snapshot(unit, run=subprocess.run, proc=Path('/proc'), cgroups=Path('/sys/fs/cgroup')):
    result = {'service': 'unknown', 'engine': 'unknown', 'firewall': 'unknown',
              'queue': 'unknown', 'sequence': None, 'queue_drops': None}
    try:
        service = run(['systemctl', 'show', unit, '--property=ActiveState,ControlGroup'],
                      capture_output=True, text=True, timeout=10)
        props = dict(line.split('=', 1) for line in service.stdout.splitlines() if '=' in line)
    except (OSError, subprocess.TimeoutExpired):
        props = {}
    result['service'] = props.get('ActiveState', 'unknown')
    group = props.get('ControlGroup', '')
    if group.startswith('/') and '..' not in Path(group).parts:
        try:
            pids = (cgroups / group.lstrip('/') / 'cgroup.procs').read_text().split()
            result['engine'] = 'missing'
            for pid in pids:
                if pid.isdigit():
                    try:
                        if (proc / pid / 'comm').read_text().strip() == 'nfqws':
                            result['engine'] = 'running'
                    except OSError:
                        if result['engine'] != 'running':
                            result['engine'] = 'unknown'
        except OSError:
            pass
    try:
        rows = (proc / 'net/netfilter/nfnetlink_queue').read_text().splitlines()
        result['queue'] = 'missing'
        for row in rows:
            cols = row.split()
            if len(cols) >= 8 and cols[0] == '220':
                result.update(queue='bound', sequence=int(cols[7]),
                              queue_drops=int(cols[5]) + int(cols[6]))
    except (OSError, ValueError):
        pass
    try:
        rules = run(['nft', '-j', 'list', 'table', 'inet', 'zapretunix'],
                    capture_output=True, text=True, timeout=10)
        if rules.returncode == 0:
            doc = json.loads(rules.stdout)
            found = []
            for item in doc.get('nftables', []):
                rule = item.get('rule', {})
                for expr in rule.get('expr', []):
                    if expr.get('queue', {}).get('num') == 220:
                        found.append(rule.get('handle'))
            result['firewall'] = 'configured' if found else 'missing'
        elif re.search(r'No such file|does not exist', rules.stderr, re.I):
            result['firewall'] = 'missing'
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass
    if result['firewall'] != 'configured':
        try:
            rules = run(['iptables', '-t', 'mangle', '-S', 'zapret'],
                        capture_output=True, text=True, timeout=10)
            if rules.returncode == 0 and re.search(r'-j NFQUEUE\b.*--queue-num 220\b', rules.stdout):
                result['firewall'] = 'configured'
            elif rules.returncode != 0 and not re.search(r'No chain|does not exist|No such', rules.stderr, re.I):
                result['firewall'] = 'unknown'
        except (OSError, subprocess.TimeoutExpired):
            result['firewall'] = 'unknown'
    return result


def runtime_summary(before, after, route_interface, configured_interface, network_ok):
    lines = ['Сервис: ' + {'active': 'запущен', 'inactive': 'остановлен', 'failed': 'ошибка'}.get(after.get('service'), 'не удалось определить'),
             'Движок nfqws: ' + {'running': 'найден в сервисе', 'missing': 'не найден в сервисе'}.get(after.get('engine'), 'не удалось проверить'),
             'Правила firewall: ' + {'configured': 'перенаправление в очередь настроено', 'missing': 'правила не найдены'}.get(after.get('firewall'), 'не удалось проверить'),
             'Очередь пакетов: ' + {'bound': 'обработчик подключён', 'missing': 'обработчик не найден'}.get(after.get('queue'), 'не удалось проверить')]
    old, new = before.get('sequence'), after.get('sequence')
    delta = None
    if isinstance(old, int) and isinstance(new, int) and new >= old:
        delta = new - old
        lines.append(f'За время проверки очередь обработала пакетов: {delta}.')
        lines.append('Счётчик общий: он может включать трафик других приложений.')
    route_matches = bool(route_interface) and (configured_interface == 'any' or route_interface == configured_interface)
    if not route_interface:
        lines.append('Маршрут не определён; участие zapret в проверке не подтверждено.')
    elif not route_matches or route_interface.startswith(('tun', 'tap', 'wg', 'tailscale', 'proton', 'mullvad')):
        lines.append(f'Трафик идёт через {route_interface}, zapret настроен на {configured_interface}.')
        lines.append('Проверка этого пути не подтверждает работу zapret. Проверь подключение без VPN.')
    elif delta == 0:
        lines.append('Во время проверки новых пакетов в очереди не обнаружено.')
    elif delta is None:
        lines.append('Обработка трафика не подтверждена: счётчик очереди недоступен или сброшен.')
    lines.append('Discord через текущий путь: ' + ('все сетевые проверки прошли' if network_ok else 'часть сетевых проверок не прошла'))
    drops = after.get('queue_drops')
    if drops:
        lines.append(f'Счётчик потерянных пакетов очереди: {drops}; это накопленное значение.')
    lines.append('Успешные сетевые проверки не подтверждают работу голоса и трансляции.')
    return lines


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



def collect_diagnostics(ctx, runtime_reader=None, progress=None, command=None,
                        gateway=None, resolve=None):
    """Shared, read-only diagnostics. No UI, authorization, or file writes.

    Callers choose whether runtime evidence may require authorization. Network
    probes never use a Discord account; unavailable evidence stays unknown.
    """
    command = command or core.command
    gateway = gateway or gateway_probe
    resolve = resolve or socket.getaddrinfo
    progress = progress or (lambda text: None)
    runtime_reader = runtime_reader or (lambda: runtime_snapshot(ctx.unit))
    progress('Читаем состояние сервиса и очереди…')
    config = core.config(ctx)
    before = runtime_reader()
    checks = []
    route, route_interface = '', None
    try:
        address = resolve('discord.com', 443, socket.AF_INET)[0][4][0]
        response = command(['ip', 'route', 'get', address])
        if response.returncode == 0:
            route = response.stdout.strip()
            match = re.search(r'\bdev (\S+)', route)
            route_interface = match.group(1) if match else None
    except (OSError, subprocess.TimeoutExpired, IndexError):
        pass
    for name, url in [('Страница приложения', 'https://discord.com/app'),
                      ('API Discord', 'https://discord.com/api/v10/gateway')]:
        progress(name + '…')
        try:
            r = command(['curl', '--noproxy', '*', '-fSs', '--max-time', '12', '-o', '/dev/null',
                         '-w', 'HTTP %{http_code}, получено %{size_download} байт', url], timeout=15)
            checks.append({'name': name, 'ok': r.returncode == 0,
                           'detail': (r.stdout.strip() + '\n' + r.stderr.strip()).strip()})
        except (OSError, subprocess.TimeoutExpired) as e:
            checks.append({'name': name, 'ok': False, 'detail': str(e)})
    progress('WebSocket…')
    try:
        checks.append({'name': 'WebSocket', 'ok': True, 'detail': gateway()})
    except Exception as e:
        checks.append({'name': 'WebSocket', 'ok': False, 'detail': str(e)})
    progress('Сравниваем состояние очереди…')
    after = runtime_reader()
    network_ok = all(check['ok'] for check in checks)
    lines = [f"Стратегия: {config['strategy']} · интерфейс: {config['interface']}",
             '', 'Маршрут к Discord:', route or 'Не удалось определить', '']
    for check in checks:
        lines.append(f"{check['name']}: {'OK' if check['ok'] else 'ОШИБКА'} — {check['detail']}")
    lines += ['', 'Результат диагностики:',
              *runtime_summary(before, after, route_interface, config['interface'], network_ok),
              '', 'Голос и трансляция проверяются подключением к каналу в Discord.',
              'Эта проверка не входит в голосовые каналы и не использует твой аккаунт.']
    return {'report': '\n'.join(lines), 'checks': checks, 'runtime': after,
            'route_interface': route_interface, 'configured_interface': config['interface'],
            'network_ok': network_ok}


def journal_snapshot(ctx, command=None, lines=100):
    """Bounded service journal, read without elevation or shell commands."""
    if type(lines) is not int or not 1 <= lines <= 100:
        raise ValueError("Количество строк журнала: от 1 до 100")
    command = command or core.command
    r = command(['journalctl', '--unit', ctx.unit, '--lines', str(lines),
                 '--no-pager', '--output', 'short-iso'], timeout=15)
    # Permission hints on stderr matter even when journalctl returns zero.
    return {'text': r.stdout[-131072:], 'warning': r.stderr[:4096].strip(),
            'ok': r.returncode == 0}
