"""Read-only runtime evidence; unknown states are distinct from failures."""
import json
from pathlib import Path
import re
import subprocess


def runtime_snapshot(unit, run=subprocess.run, proc=Path('/proc'), cgroups=Path('/sys/fs/cgroup')):
    result = {'service': 'unknown', 'engine': 'unknown', 'firewall': 'unknown',
              'queue': 'unknown', 'sequence': None, 'queue_drops': None}
    service = run(['systemctl', 'show', unit, '--property=ActiveState,ControlGroup'],
                  capture_output=True, text=True, timeout=10)
    props = dict(line.split('=', 1) for line in service.stdout.splitlines() if '=' in line)
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
                        pass
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
        except (OSError, subprocess.TimeoutExpired):
            pass
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
    elif not route_matches:
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
