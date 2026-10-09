import fcntl
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from zapret_console import app, client, core


def payload(ok=True, code='ok', message='', data=None):
    return {'protocol': 1, 'ok': ok, 'code': code, 'message': message, 'data': data}


class EndpointTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / 'zapret-latest').mkdir()
        for n in ('general_alt11.bat', 'general_alt10.bat'):
            (self.root / 'zapret-latest' / n).touch()
        self.ctx = core.BackendContext(root=self.root, state=self.root / 'state', unit='zapret.service')
        self.old = dict(interface='any', gamefiltertcp='true', gamefilterudp='false',
                        strategy='general_alt11.bat', firewall_backend='nftables')
        with patch.object(core, 'trusted'):
            core.write_config(self.ctx, self.old)

    def tearDown(self):
        self.tmp.cleanup()

    def inactive_system(self):
        def run(args, **kw):
            return subprocess.CompletedProcess(args, 1, 'inactive\n', '')
        return patch.object(core, 'command', side_effect=run)

    def current_revision(self):
        with self.inactive_system():
            return core.snapshot(self.ctx)['revision']

    def endpoint(self, raw, euid=0):
        with patch.object(app.os, 'geteuid', return_value=euid), \
             patch.object(core, 'trusted'), self.inactive_system():
            return app.request_endpoint(raw, context=self.ctx)


class ParseRequestTests(EndpointTestBase):
    def test_valid_shapes(self):
        parsed = app.parse_request(json.dumps(client.make_request('profile-save', 'home', 'r' * 64)))
        self.assertEqual(parsed, {'action': 'profile-save', 'value': 'home', 'expected_revision': 'r' * 64})
        parsed = app.parse_request(json.dumps(client.make_request('stop')))
        self.assertEqual(parsed, {'action': 'stop', 'value': None, 'expected_revision': None})
        parsed = app.parse_request(json.dumps(client.make_request('runtime')))
        self.assertEqual(parsed['action'], 'runtime')

    def test_deviations_rejected(self):
        good = client.make_request('profile-save', 'home', 'r' * 64)
        bad_cases = [
            'not json',
            '',
            '[1, 2]',
            '"text"',
            json.dumps(good | {'extra': 1}),
            json.dumps({k: v for k, v in good.items() if k != 'value'}),
            json.dumps(good | {'protocol': True}),
            json.dumps(good | {'protocol': '1'}),
            json.dumps(good | {'protocol': 2}),
            json.dumps(good | {'action': 'reboot'}),
            json.dumps(good | {'action': 5}),
            json.dumps(good | {'value': 5}),
            json.dumps(client.make_request('profile-save', 'home', None)),
            json.dumps(client.make_request('profile-save', 'home', '')),
            json.dumps(client.make_request('stop', 'now')),
            json.dumps(client.make_request('stop', expected_revision='r' * 64)),
        ]
        for raw in bad_cases:
            with self.assertRaises(ValueError, msg=raw):
                app.parse_request(raw)

    def test_oversized_request_rejected(self):
        big = client.make_request('profile-save', 'x' * 70000, 'r' * 64)
        with self.assertRaisesRegex(ValueError, '64 KiB'):
            app.parse_request(json.dumps(big))


class RequestEndpointTests(EndpointTestBase):
    def test_ok_mutation_then_operation_failed(self):
        revision = self.current_revision()
        result, code = self.endpoint(json.dumps(client.make_request('profile-save', 'home', revision)))
        self.assertEqual(code, 0)
        self.assertTrue(result['ok'])
        self.assertEqual(result['code'], 'ok')
        self.assertTrue((self.ctx.state / 'profiles' / 'home.json').exists())
        # после сохранения ревизия изменилась: пересчитываем и проверяем отказ dispatch
        fresh = self.current_revision()
        payload, code = self.endpoint(json.dumps(client.make_request('strategy', 'missing.bat', fresh)))
        self.assertEqual(code, 1)
        self.assertEqual(payload['code'], 'operation_failed')

    def test_busy_conflict_and_permission_denied(self):
        revision = self.current_revision()
        self.ctx.state.mkdir(parents=True)
        with self.ctx.lock.open('a') as held:
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result, code = self.endpoint(json.dumps(client.make_request('stop')))
            self.assertEqual((result['code'], code), ('busy', 1))
        result, code = self.endpoint(json.dumps(client.make_request('profile-save', 'home', 'stale')))
        self.assertEqual((result['code'], code), ('conflict', 1))
        self.assertIn('обнови', result['message'].lower())
        self.assertFalse((self.ctx.state / 'profiles' / 'home.json').exists())
        result, code = self.endpoint(json.dumps(client.make_request('stop')), euid=1000)
        self.assertEqual((result['code'], code), ('permission_denied', 1))

    def test_unusable_snapshot_is_operation_failed_not_conflict(self):
        self.ctx.state.mkdir(parents=True)
        known = self.ctx.known
        known.write_text('{}')
        known.chmod(0o000)
        try:
            payload, code = self.endpoint(json.dumps(client.make_request('profile-save', 'home', 'r' * 64)))
        finally:
            known.chmod(0o644)
        self.assertEqual((payload['code'], code), ('operation_failed', 1))
        self.assertIn('прочитано не полностью', payload['message'])
        self.assertFalse((self.ctx.state / 'profiles' / 'home.json').exists())

    def test_runtime_needs_no_lock_or_revision(self):
        with patch('zapret_console.diagnostics.runtime_snapshot', return_value={'engine': 'unknown'}):
            result, code = self.endpoint(json.dumps(client.make_request('runtime')))
        self.assertEqual((result['code'], code), ('ok', 0))
        self.assertEqual(result['data'], {'engine': 'unknown'})
        self.assertFalse((self.ctx.state / '.lock').exists())

    def test_invalid_request_and_settings_error(self):
        result, code = self.endpoint('garbage')
        self.assertEqual((result['code'], code), ('invalid_request', 1))
        with patch.object(app, 'load_context', side_effect=RuntimeError('settings broken')):
            result, code = app.request_endpoint(json.dumps(client.make_request('stop')))
        self.assertEqual((result['code'], code), ('operation_failed', 1))

    def test_main_prints_exactly_one_json_and_exit_code(self):
        body = json.dumps(client.make_request('stop'))
        out = io.StringIO()
        with patch.object(app.sys, 'argv', ['zapret-console', '--request-json', body]), \
             patch.object(app, 'load_context', return_value=self.ctx), \
             patch.object(app.os, 'geteuid', return_value=0), \
             patch.object(core, 'trusted'), patch.object(core, 'systemctl') as ctl:
            with self.assertRaises(SystemExit) as cm, redirect_stdout(out):
                app.main()
        self.assertEqual(cm.exception.code, 0)
        result = json.loads(out.getvalue())
        self.assertEqual(result['code'], 'ok')
        ctl.assert_called_once_with(self.ctx, 'stop')

    def test_combined_modes_rejected_without_dispatch(self):
        out = io.StringIO()
        argv = ['zapret-console', '--request-json', '{}', '--status']
        with patch.object(app.sys, 'argv', argv):
            with self.assertRaises(SystemExit) as cm, redirect_stdout(out):
                app.main()
        self.assertEqual(cm.exception.code, 1)
        result = json.loads(out.getvalue())
        self.assertEqual(result['code'], 'invalid_request')


class ClientTransportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def body_for(action='stop'):
        return json.dumps(client.make_request(action), ensure_ascii=False)

    def run_client(self, mode='terminal', euid=1000, tty=True, stdout='', returncode=0, environ=None):
        response = payload()
        captured = {}

        def fake_run(argv, **kwargs):
            captured['argv'] = argv
            captured['kwargs'] = kwargs
            return subprocess.CompletedProcess(argv, returncode, stdout, '')

        patches = [patch.object(core, 'trusted'),
                   patch.object(client.os, 'geteuid', return_value=euid),
                   patch.object(client.sys.stdin, 'isatty', return_value=tty),
                   patch.object(client.shutil, 'which', return_value='/usr/bin/tool'),
                   patch.dict(os.environ, environ or {}, clear=True),
                   patch('subprocess.run', side_effect=fake_run)]
        for p in patches:
            p.start()
        try:
            result = client.request(client.make_request('stop'), mode=mode)
        finally:
            for p in reversed(patches):
                p.stop()
        return result, captured, response

    def test_terminal_mode_uses_fixed_sudo_argv_once(self):
        response = payload()
        body = self.body_for()
        result, captured, _ = self.run_client(mode='terminal', stdout=json.dumps(response))
        self.assertEqual(result, response)
        self.assertEqual(captured['argv'], ['sudo', '--', client.LAUNCHER, '--request-json', body])
        self.assertIsNone(captured['kwargs'].get('stdin'))
        self.assertEqual(captured['kwargs'].get('stdout'), subprocess.PIPE)
        self.assertIsNone(captured['kwargs'].get('stderr'))
        self.assertTrue(captured['kwargs'].get('text'))

    def test_gui_mode_uses_pkexec_without_tty(self):
        response = payload()
        body = self.body_for()
        result, captured, _ = self.run_client(mode='gui', tty=False, stdout=json.dumps(response))
        self.assertEqual(result, response)
        self.assertEqual(captured['argv'],
                         ['pkexec', '--disable-internal-agent', client.LAUNCHER, '--request-json', body])
        self.assertEqual(captured['kwargs'].get('stdin'), subprocess.DEVNULL)
        self.assertEqual(captured['kwargs'].get('stderr'), subprocess.PIPE)

    def test_root_runs_launcher_without_elevation(self):
        response = payload()
        body = self.body_for()
        result, captured, _ = self.run_client(mode='gui', euid=0, stdout=json.dumps(response))
        self.assertEqual(result, response)
        self.assertEqual(captured['argv'], [client.LAUNCHER, '--request-json', body])

    def test_pkexec_cancel_and_failure_map_to_auth_results(self):
        result, _, _ = self.run_client(mode='gui', returncode=126)
        self.assertEqual(result['code'], 'auth_cancelled')
        result, _, _ = self.run_client(mode='gui', returncode=127)
        self.assertEqual(result['code'], 'auth_failed')

    def test_unclear_output_is_transport_error(self):
        for stdout, rc, mode in [('', 1, 'terminal'), ('garbage', 0, 'terminal'),
                                 (json.dumps(payload() | {'protocol': 2}), 0, 'terminal'),
                                 (json.dumps(payload() | {'ok': 'yes'}), 0, 'gui'),
                                 # ok:true with an error code, and unknown codes
                                 (json.dumps(payload(ok=True, code='conflict')), 0, 'terminal'),
                                 (json.dumps(payload(ok=True, code='future_unknown')), 0, 'terminal'),
                                 (json.dumps(payload(ok=False, code='ok')), 1, 'terminal'),
                                 # exit code must match ok
                                 (json.dumps(payload(ok=True, code='ok')), 1, 'terminal'),
                                 (json.dumps(payload(ok=False, code='busy')), 0, 'terminal')]:
            result, _, _ = self.run_client(mode=mode, stdout=stdout, returncode=rc)
            self.assertEqual(result['code'], 'transport_error', stdout)
            self.assertIn('перечитай', result['message'])

    def test_wrong_typed_code_is_transport_error_without_exception(self):
        for bad in ([], {}, None, 5, True):
            body = json.dumps(payload(ok=False, code=bad))
            with patch.object(core, 'trusted'), \
                 patch.object(client.os, 'geteuid', return_value=1000), \
                 patch.object(client.sys.stdin, 'isatty', return_value=True), \
                 patch.object(client.shutil, 'which', return_value='/usr/bin/sudo'), \
                 patch('subprocess.run',
                       side_effect=lambda argv, **kw: subprocess.CompletedProcess(argv, 1, body, '')) as run_mock:
                result = client.request(client.make_request('stop'), mode='terminal')
            self.assertEqual(result['code'], 'transport_error', bad)
            self.assertFalse(result['ok'])
            self.assertIn('перечитай', result['message'])
            run_mock.assert_called_once()

    def test_valid_helper_errors_pass_through_with_exit_one(self):
        for code in ('busy', 'conflict', 'invalid_request', 'permission_denied', 'operation_failed'):
            body = json.dumps(payload(ok=False, code=code, message='подробности'))
            result, _, _ = self.run_client(mode='terminal', stdout=body, returncode=1)
            self.assertEqual(result['code'], code, code)
            self.assertFalse(result['ok'])
            self.assertEqual(result['message'], 'подробности')

    def test_root_branch_exit_126_127_is_transport_error(self):
        for rc in (126, 127):
            result, _, _ = self.run_client(euid=0, returncode=rc)
            self.assertEqual(result['code'], 'transport_error', rc)
            self.assertIn('перечитай', result['message'])

    def test_timeout_reports_unknown_result_without_retry(self):
        with patch.object(core, 'trusted'), \
             patch.object(client.os, 'geteuid', return_value=1000), \
             patch.object(client.sys.stdin, 'isatty', return_value=True), \
             patch.object(client.shutil, 'which', return_value='/usr/bin/sudo'), \
             patch('subprocess.run', side_effect=subprocess.TimeoutExpired(cmd='x', timeout=120)) as run_mock:
            result = client.request(client.make_request('stop'), mode='terminal')
        self.assertEqual(result['code'], 'transport_error')
        self.assertIn('неизвестен', result['message'])
        self.assertIn('Перечитай', result['message'])
        run_mock.assert_called_once()

    def test_launcher_missing_symlink_or_untrusted_refused(self):
        run_mock = Mock()
        with patch('subprocess.run', run_mock):
            with patch.object(client, 'LAUNCHER', str(self.root / 'absent')):
                self.assertEqual(client.request(client.make_request('stop'))['code'], 'transport_error')
            link = self.root / 'link'
            link.symlink_to(self.root / 'absent')
            with patch.object(client, 'LAUNCHER', str(link)):
                self.assertEqual(client.request(client.make_request('stop'))['code'], 'transport_error')
            plain = self.root / 'zapret-console'
            plain.write_text('#!/bin/sh\n')
            with patch.object(client, 'LAUNCHER', str(plain)):
                result = client.request(client.make_request('stop'))
                self.assertEqual(result['code'], 'transport_error')
                self.assertIn('довер', result['message'])
        run_mock.assert_not_called()

    def test_terminal_without_tty_is_auth_failed(self):
        with patch.object(core, 'trusted'), \
             patch.object(client.os, 'geteuid', return_value=1000), \
             patch.object(client.sys.stdin, 'isatty', return_value=False), \
             patch.object(client.shutil, 'which', return_value='/usr/bin/sudo'), \
             patch('subprocess.run') as run_mock:
            result = client.request(client.make_request('stop'), mode='terminal')
        self.assertEqual(result['code'], 'auth_failed')
        self.assertIn('терминала', result['message'])
        run_mock.assert_not_called()

    def test_terminal_mode_ignores_display(self):
        response = payload()
        body = self.body_for()
        result, captured, _ = self.run_client(mode='terminal', environ={},
                                              stdout=json.dumps(response))
        self.assertEqual(result, response)
        self.assertEqual(captured['argv'], ['sudo', '--', client.LAUNCHER, '--request-json', body])

    def test_client_import_is_clean_and_ui_free(self):
        src = str(Path(__file__).resolve().parents[1] / 'src')
        code = (
            'import sys, subprocess\n'
            'sys.path.insert(0, sys.argv[1])\n'
            'def boom(*args, **kwargs):\n'
            '    raise AssertionError("subprocess during import")\n'
            'subprocess.run = boom\n'
            'subprocess.Popen = boom\n'
            'from zapret_console import client\n'
            'assert client.PROTOCOL == 1\n'
            'banned = ("PySide6", "PyQt", "textual")\n'
            'assert not any(any(b in m for b in banned) for m in set(sys.modules))\n'
            'print("clean")\n'
        )
        r = subprocess.run([sys.executable, '-c', code, src], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), 'clean')

    def test_cli_help_works_without_display(self):
        env = dict(os.environ)
        env.pop('DISPLAY', None)
        env['PYTHONPATH'] = str(Path(__file__).resolve().parents[1] / 'src')
        r = subprocess.run([sys.executable, '-m', 'zapret_console', '--help'],
                           env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0)
        self.assertIn('Zapret Console', r.stdout)

    def test_client_snapshot_passes_through_core(self):
        ctx = core.BackendContext(root=self.root, state=self.root / 'state', unit='x.service')
        (self.root / 'conf.env').write_text('strategy=general_alt11.bat\ninterface=any\n')
        (self.root / 'zapret-latest').mkdir()
        (self.root / 'zapret-latest/general_alt11.bat').touch()

        def run(args, **kw):
            return subprocess.CompletedProcess(args, 1, 'inactive\n', '')

        with patch.object(core, 'command', side_effect=run):
            self.assertEqual(client.snapshot(context=ctx), core.snapshot(ctx))


if __name__ == '__main__':
    unittest.main()
