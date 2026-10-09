"""Shared inspection pipeline: no real network/system changes in tests."""
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from zapret_console import core, client, diagnostics


class InspectionTests(unittest.TestCase):
    def setUp(self):
        self.ctx = core.BackendContext('/tmp/backend', '/tmp/state', 'custom.service')
        self.config = {'interface': 'eth0', 'strategy': 'general_alt11.bat'}
        self.runtime = {'service': 'active', 'engine': 'running', 'firewall': 'unknown',
                        'queue': 'bound', 'sequence': 1}

    def collect(self, command=None, runtime=None, **kw):
        def run(argv, **kwargs):
            output = '1.2.3.4 dev eth0' if argv[0] == 'ip' else 'HTTP 200'
            return subprocess.CompletedProcess(argv, 0, output, '')
        with patch.object(core, 'config', return_value=self.config):
            return diagnostics.collect_diagnostics(self.ctx,
                runtime_reader=runtime or Mock(side_effect=[self.runtime, dict(self.runtime, sequence=5)]),
                command=command or run, resolve=lambda *a: [(None, None, None, None, ('1.2.3.4', 443))],
                gateway=lambda: 'WebSocket connected', **kw)

    def test_network_success_keeps_unknown_firewall_and_shared_counter_caveat(self):
        progress = []
        data = self.collect(progress=progress.append)
        self.assertTrue(data['network_ok'])
        self.assertEqual(len(data['checks']), 3)
        self.assertEqual(data['runtime']['firewall'], 'unknown')
        self.assertIn('не удалось проверить', data['report'])
        self.assertIn('других приложений', data['report'])
        self.assertIn('Голос и трансляция', data['report'])
        self.assertEqual(len(progress), 5)

    def test_failed_http_and_missing_command_do_not_abort_remaining_probes(self):
        def run(argv, **kwargs):
            if argv[0] == 'ip':
                raise FileNotFoundError('ip absent')
            raise subprocess.TimeoutExpired(argv, 15)
        data = self.collect(command=run)
        self.assertFalse(data['network_ok'])
        self.assertTrue(data['checks'][-1]['ok'])
        self.assertIsNone(data['route_interface'])
        self.assertIn('Маршрут не определён', data['report'])

    def test_vpn_with_any_config_does_not_confirm_zapret(self):
        report = '\n'.join(diagnostics.runtime_summary(self.runtime, dict(self.runtime, sequence=5),
                                                        'tun0', 'any', True))
        self.assertIn('без VPN', report)
        self.assertIn('не подтверждает работу zapret', report)

    def test_default_client_does_not_request_authorization(self):
        with patch.object(diagnostics, 'collect_diagnostics', return_value={'report': 'ok'}) as collect, \
             patch.object(client, 'request') as auth:
            client.diagnose(context=self.ctx, mode='gui')
        auth.assert_not_called()
        self.assertIsNone(collect.call_args.kwargs['runtime_reader'])

    def test_optional_authorization_cancellation_stops_before_network(self):
        with patch.object(core, 'config', return_value=self.config), \
             patch.object(client, 'request', return_value={'ok': False, 'code': 'auth_cancelled', 'message': 'cancelled'}) as auth, \
             patch.object(core, 'command') as command:
            with self.assertRaises(client.ReadOperationError) as caught:
                client.diagnose(context=self.ctx, mode='gui', privileged=True)
        self.assertEqual(caught.exception.code, 'auth_cancelled')
        self.assertEqual(auth.call_count, 1)
        command.assert_not_called()
        self.assertEqual(auth.call_args.args[0], client.make_request('runtime'))
        self.assertEqual(auth.call_args.kwargs['mode'], 'gui')

    def test_journal_is_fixed_unit_bounded_and_preserves_permission_hint(self):
        run = Mock(return_value=subprocess.CompletedProcess([], 0, 'x' * 140000, 'Permission limited'))
        result = diagnostics.journal_snapshot(self.ctx, command=run)
        self.assertEqual(len(result['text']), 131072)
        self.assertEqual(result['warning'], 'Permission limited')
        self.assertTrue(result['ok'])
        self.assertIn('custom.service', run.call_args.args[0])
        self.assertIn('100', run.call_args.args[0])
        self.assertEqual(run.call_args.kwargs['timeout'], 15)

    def test_journal_nonzero_is_failure_not_empty_success(self):
        run = Mock(return_value=subprocess.CompletedProcess([], 1, '', 'Permission denied'))
        result = diagnostics.journal_snapshot(self.ctx, command=run)
        self.assertFalse(result['ok'])
        self.assertEqual(result['warning'], 'Permission denied')

    def test_unavailable_system_tools_leave_runtime_unknown(self):
        run = Mock(side_effect=FileNotFoundError('absent'))
        data = diagnostics.runtime_snapshot('custom.service', run=run, proc=Path('/missing-proc'), cgroups=Path('/missing-cgroups'))
        self.assertEqual(data['service'], 'unknown')
        self.assertEqual(data['firewall'], 'unknown')
        self.assertEqual(data['engine'], 'unknown')

    def test_missing_nft_and_unreadable_iptables_are_unknown(self):
        def run(argv, **kw):
            if argv[0] == 'nft':
                return subprocess.CompletedProcess(argv, 1, '', 'No such file')
            if argv[0] == 'iptables':
                return subprocess.CompletedProcess(argv, 1, '', 'Permission denied')
            return subprocess.CompletedProcess(argv, 0, 'ActiveState=active', '')
        data = diagnostics.runtime_snapshot('custom.service', run=run, proc=Path('/missing-proc'), cgroups=Path('/missing-cgroups'))
        self.assertEqual(data['firewall'], 'unknown')

    def test_journal_rejects_unbounded_or_non_numeric_limits(self):
        command = Mock()
        for limit in [0, 101, True, '100']:
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                diagnostics.journal_snapshot(self.ctx, command=command, lines=limit)
        command.assert_not_called()
