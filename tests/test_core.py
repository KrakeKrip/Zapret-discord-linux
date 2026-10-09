import fcntl
import json
import multiprocessing
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from zapret_console import app, core


class MenuTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / 'custom-strategies').mkdir()
        (self.root / 'zapret-latest').mkdir()
        for n in ('general_alt11.bat', 'general_alt10.bat'):
            (self.root / 'zapret-latest' / n).touch()
        self.ctx = core.BackendContext(root=self.root, state=self.root / 'state', unit='zapret.service')
        self.patches = [patch.object(core, 'trusted')]
        for p in self.patches:
            p.start()
        self.old = dict(interface='any', gamefiltertcp='true', gamefilterudp='false',
                        strategy='general_alt11.bat', firewall_backend='nftables')
        core.write_config(self.ctx, self.old)

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_strategy_preserves_flags_and_does_not_start_stopped_service(self):
        with patch.object(core.os, 'geteuid', return_value=0), patch.object(core, 'active', return_value=False), patch.object(core, 'systemctl') as ctl:
            core.admin_command(self.ctx, 'strategy', 'general_alt10.bat')
            ctl.assert_not_called()
        new = core.config(self.ctx)
        self.assertEqual(new['strategy'], 'general_alt10.bat')
        self.assertEqual({k: v for k, v in new.items() if k != 'strategy'}, {k: v for k, v in self.old.items() if k != 'strategy'})

    def test_failed_restart_restores_config(self):
        new = self.old | {'strategy': 'general_alt10.bat'}
        with patch.object(core, 'active', return_value=True), patch.object(core, 'systemctl', side_effect=[RuntimeError('failed'), None]) as ctl:
            with self.assertRaisesRegex(RuntimeError, 'восстановлена'):
                core.apply_config(self.ctx, new)
            self.assertEqual(ctl.call_count, 2)
        self.assertEqual(core.config(self.ctx), self.old)

    def test_rejects_shell_text_and_paths_before_mutation(self):
        for value in ('../../evil.bat', 'general_alt11.bat; touch /tmp/test', 'missing.bat'):
            with self.assertRaises(ValueError):
                core.apply_config(self.ctx, self.old | {'strategy': value})
            self.assertEqual(core.config(self.ctx), self.old)

    def test_save_and_restore_working_config(self):
        with patch.object(core.os, 'geteuid', return_value=0), patch.object(core, 'active', return_value=False):
            core.admin_command(self.ctx, 'save-good')
            core.admin_command(self.ctx, 'strategy', 'general_alt10.bat')
            core.admin_command(self.ctx, 'restore-good')
        self.assertEqual(core.config(self.ctx), self.old)

    def test_config_text_is_never_executed(self):
        sentinel = self.root / 'unsafe'
        with (self.root / 'conf.env').open('a') as f:
            f.write(f'\nstrategy=$(touch {sentinel})\n')
        with self.assertRaises(ValueError):
            core.config(self.ctx)
        self.assertFalse(sentinel.exists())

    def test_eof_in_websocket_handshake_is_bounded(self):
        from unittest.mock import MagicMock
        sock = MagicMock()
        sock.recv.return_value = b''
        context = MagicMock()
        context.wrap_socket.return_value = sock
        with patch.object(app.socket, 'create_connection', return_value=sock), patch.object(app.ssl, 'create_default_context', return_value=context):
            with self.assertRaisesRegex(RuntimeError, 'handshake'):
                app.gateway_probe()

    def test_restore_previous_swaps_profiles(self):
        with patch.object(core.os, 'geteuid', return_value=0), patch.object(core, 'active', return_value=False):
            core.admin_command(self.ctx, 'strategy', 'general_alt10.bat')
            core.admin_command(self.ctx, 'restore-previous')
        self.assertEqual(core.config(self.ctx), self.old)
        self.assertEqual(json.loads((self.ctx.state / 'previous.json').read_text())['strategy'], 'general_alt10.bat')

    def test_settings_reject_service_command_injection(self):
        path = self.root / 'settings.json'
        path.write_text(json.dumps({'backend_root': '/opt/test', 'service': 'zapret; touch /tmp/unsafe'}))
        with self.assertRaises(ValueError):
            core.BackendContext.from_settings(path)

    def test_relative_backend_path_is_rejected(self):
        path = self.root / 'settings.json'
        path.write_text(json.dumps({'backend_root': '../test', 'service': 'zapret.service'}))
        with self.assertRaises(ValueError):
            core.BackendContext.from_settings(path)

    def test_partial_settings_keep_defaults(self):
        path = self.root / 'settings.json'
        path.write_text(json.dumps({'service': 'other.service'}))
        ctx = core.BackendContext.from_settings(path)
        self.assertEqual(ctx.root, core.DEFAULT_ROOT)
        self.assertEqual(ctx.unit, 'other.service')

    def test_missing_settings_file_yields_defaults(self):
        ctx = core.BackendContext.from_settings(self.root / 'absent.json')
        self.assertEqual(ctx.root, core.DEFAULT_ROOT)
        self.assertEqual(ctx.unit, core.DEFAULT_UNIT)

    def test_failed_service_after_restart_is_rolled_back(self):
        new = self.old | {'strategy': 'general_alt10.bat'}
        with patch.object(core, 'active', side_effect=[True, False]), patch.object(core, 'systemctl') as ctl, patch('time.sleep'):
            with self.assertRaisesRegex(RuntimeError, 'восстановлена'):
                core.apply_config(self.ctx, new)
            self.assertEqual(ctl.call_count, 2)
        self.assertEqual(core.config(self.ctx), self.old)


class CoreContractTests(unittest.TestCase):
    """Import and context creation must not touch the system (acceptance #1)."""

    def test_import_and_context_creation_have_no_side_effects(self):
        src = str(Path(__file__).resolve().parents[1] / 'src')
        code = (
            'import sys, subprocess\n'
            'sys.path.insert(0, sys.argv[1])\n'
            'def boom(*args, **kwargs):\n'
            '    raise AssertionError("system call during import or context creation")\n'
            'subprocess.run = boom\n'
            'subprocess.Popen = boom\n'
            'from zapret_console import core\n'
            'ctx = core.BackendContext(root="/tmp/zc-root", state="/tmp/zc-state", unit="x.service")\n'
            'assert ctx.known.name == "known-good.json" and ctx.lock.name == ".lock"\n'
            'print("clean")\n'
        )
        r = subprocess.run([sys.executable, '-c', code, src], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), 'clean')

    def test_admin_entry_checks_root_itself(self):
        with tempfile.TemporaryDirectory() as directory:
            ctx = core.BackendContext(state=Path(directory) / 'state', unit='x.service')
            with patch.object(core.os, 'geteuid', return_value=1000):
                with self.assertRaisesRegex(RuntimeError, 'права администратора'):
                    core.admin_command(ctx, 'stop')


def _child_mutation(state_dir, root_dir, queue):
    """Separate process: one profile-save through the shared administrative entry."""
    from unittest.mock import patch
    from zapret_console import core
    ctx = core.BackendContext(root=root_dir, state=state_dir, unit='locktest.service')
    try:
        with patch.object(core, 'trusted'), patch.object(core.os, 'geteuid', return_value=0):
            core.admin_command(ctx, 'profile-save', 'runner')
        queue.put('done')
    except Exception as e:
        queue.put(f'error: {e}')


class SharedLockTests(unittest.TestCase):
    """One shared STATE/.lock flock must serialize independent processes."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / 'zapret-latest').mkdir()
        (self.root / 'zapret-latest/general_alt11.bat').touch()
        self.ctx = core.BackendContext(root=self.root, state=self.root / 'state', unit='locktest.service')
        self.old = dict(interface='any', gamefiltertcp='true', gamefilterudp='false',
                        strategy='general_alt11.bat', firewall_backend='auto')
        with patch.object(core, 'trusted'):
            core.write_config(self.ctx, self.old)
        self.ctx.state.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self.tmp.cleanup()

    def start_child(self):
        mp = multiprocessing.get_context('fork')
        queue = mp.Queue()
        proc = mp.Process(target=_child_mutation, args=(str(self.ctx.state), str(self.root), queue))
        proc.start()
        return proc, queue

    def test_busy_lock_refuses_mutation_in_process(self):
        with self.ctx.lock.open('a') as held:
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with patch.object(core, 'trusted'), patch.object(core.os, 'geteuid', return_value=0):
                with self.assertRaisesRegex(RuntimeError, 'уже выполняется'):
                    core.admin_command(self.ctx, 'profile-save', 'runner')
        self.assertFalse((core.profiles_dir(self.ctx) / 'runner.json').exists())

    def test_second_process_refused_while_lock_held_then_proceeds(self):
        with self.ctx.lock.open('a') as held:
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
            proc, queue = self.start_child()
            proc.join(30)
            self.assertFalse(proc.is_alive(), 'child hung on a busy lock')
            result = queue.get(timeout=10)
            self.assertTrue(result.startswith('error:'), result)
            self.assertIn('уже выполняется', result)
        self.assertFalse((core.profiles_dir(self.ctx) / 'runner.json').exists())
        proc, queue = self.start_child()
        proc.join(30)
        self.assertFalse(proc.is_alive(), 'child hung after lock release')
        self.assertEqual(queue.get(timeout=10), 'done')
        saved = json.loads((core.profiles_dir(self.ctx) / 'runner.json').read_text())
        self.assertEqual(saved, self.old)


if __name__ == '__main__':
    unittest.main()
