import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from zapret_console import diagnostics
import json
import subprocess
import tempfile
import unittest


class DiagnosticsTests(unittest.TestCase):
    def test_engine_queue_and_firewall_are_independent(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            proc = base / 'proc'
            (proc / '42').mkdir(parents=True)
            (proc / '42/comm').write_text('nfqws\n')
            (proc / 'net/netfilter').mkdir(parents=True)
            (proc / 'net/netfilter/nfnetlink_queue').write_text('220 1234 0 2 65535 2 3 150 1\n')
            groups = base / 'cgroups'
            (groups / 'system.slice/zapret.service').mkdir(parents=True)
            (groups / 'system.slice/zapret.service/cgroup.procs').write_text('42\n')
            def run(args, **kw):
                output = 'ActiveState=active\nControlGroup=/system.slice/zapret.service\n' if args[0] == 'systemctl' else json.dumps({'nftables': [{'rule': {'handle': 2, 'expr': [{'queue': {'num': 220}}]}}]})
                return subprocess.CompletedProcess(args, 0, output, '')
            result = diagnostics.runtime_snapshot('zapret.service', run=run, proc=proc, cgroups=groups)
            self.assertEqual(result['engine'], 'running')
            self.assertEqual(result['firewall'], 'configured')
            self.assertEqual(result['sequence'], 150)
            self.assertEqual(result['queue_drops'], 5)

    def test_permission_failure_is_unknown_not_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            def run(args, **kw):
                return subprocess.CompletedProcess(args, 1, '', 'Operation not permitted')
            result = diagnostics.runtime_snapshot('zapret.service', run=run, proc=Path(directory), cgroups=Path(directory))
            self.assertEqual(result['firewall'], 'unknown')
            self.assertEqual(result['queue'], 'unknown')

    def test_vpn_success_does_not_confirm_zapret(self):
        lines = diagnostics.runtime_summary({'sequence': 10}, {'sequence': 15}, 'tun0', 'eth0', True)
        report = '\n'.join(lines)
        self.assertIn('не подтверждает работу zapret', report)
        self.assertIn('других приложений', report)

    def test_iptables_backend_is_detected_when_nft_table_is_absent(self):
        with tempfile.TemporaryDirectory() as directory:
            def run(args, **kw):
                if args[0] == 'nft':
                    return subprocess.CompletedProcess(args, 1, '', 'No such file or directory')
                output = '-A zapret -j NFQUEUE --queue-num 220 --queue-bypass' if args[0] == 'iptables' else 'ActiveState=active\n'
                return subprocess.CompletedProcess(args, 0, output, '')
            result = diagnostics.runtime_snapshot('zapret.service', run=run, proc=Path(directory), cgroups=Path(directory))
            self.assertEqual(result['firewall'], 'configured')

    def test_reset_counter_does_not_become_negative_traffic(self):
        lines = diagnostics.runtime_summary({'sequence': 100}, {'sequence': 3}, 'eth0', 'eth0', False)
        self.assertIn('сброшен', '\n'.join(lines))

    def test_missing_route_does_not_prove_participation(self):
        lines = diagnostics.runtime_summary({}, {}, None, 'any', True)
        self.assertIn('Маршрут не определён', '\n'.join(lines))
