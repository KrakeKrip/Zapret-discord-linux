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


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / 'zapret-latest').mkdir()
        for n in ('general_alt11.bat', 'general_alt10.bat'):
            (self.root / 'zapret-latest' / n).touch()
        self.ctx = core.BackendContext(root=self.root, state=self.root / 'state', unit='zapret.service')
        self.old = dict(interface='any', gamefiltertcp='true', gamefilterudp='false',
                        strategy='general_alt11.bat', firewall_backend='nftables')
        core.write_config(self.ctx, self.old)

    def tearDown(self):
        self.tmp.cleanup()

    def fake_system(self):
        def run(args, **kw):
            out = 'active\n' if 'is-active' in args else 'enabled\n'
            return subprocess.CompletedProcess(args, 0, out, '')
        return patch.object(core, 'command', side_effect=run)

    def snap(self):
        with self.fake_system():
            return core.snapshot(self.ctx)

    def test_snapshot_is_reproducible_and_read_only(self):
        before = sorted(str(p.relative_to(self.root)) for p in self.root.rglob('*'))
        first, second = self.snap(), self.snap()
        self.assertEqual(first['revision'], second['revision'])
        self.assertEqual(first['config'], self.old)
        self.assertIsNone(first['config_error'])
        self.assertEqual(first['service_state'], 'active')
        self.assertEqual(first['autostart'], 'enabled')
        self.assertEqual(first['profiles'], [])
        self.assertEqual(sorted(str(p.relative_to(self.root)) for p in self.root.rglob('*')), before)

    def test_revision_tracks_config_profiles_and_legacy_files(self):
        base = self.snap()['revision']
        profiles = self.ctx.state / 'profiles'
        profiles.mkdir(parents=True)
        (profiles / 'home.json').write_text(json.dumps(self.old))
        with_profile = self.snap()['revision']
        self.assertNotEqual(with_profile, base)
        core.write_config(self.ctx, self.old | {'strategy': 'general_alt10.bat'})
        after_conf = self.snap()['revision']
        self.assertNotEqual(after_conf, with_profile)
        (profiles / 'home.json').write_text(json.dumps(self.old | {'firewall_backend': 'auto'}))
        edited = self.snap()['revision']
        self.assertNotEqual(edited, with_profile)
        (profiles / 'temp.json').write_text(json.dumps(self.old))
        with_temp = self.snap()['revision']
        self.assertNotEqual(with_temp, edited)
        (profiles / 'temp.json').unlink()
        # identical bytes after create+delete count as the same state
        self.assertEqual(self.snap()['revision'], edited)
        self.assertNotEqual(self.snap()['revision'], after_conf)
        self.ctx.known.write_text(json.dumps(self.old))
        with_known = self.snap()['revision']
        self.assertNotEqual(with_known, edited)
        (self.ctx.state / 'previous.json').write_text('{}')
        self.assertNotEqual(self.snap()['revision'], with_known)

    def test_revision_ignores_lock_temp_files_and_identical_rewrites(self):
        base = self.snap()['revision']
        self.ctx.state.mkdir(parents=True, exist_ok=True)
        self.ctx.lock.write_text('junk')
        (self.ctx.state / '.zapret-console-partial').write_text('half-written')
        conf = self.ctx.root / 'conf.env'
        conf.write_bytes(conf.read_bytes())
        self.assertEqual(self.snap()['revision'], base)

    def test_snapshot_reports_corrupt_profiles_without_breaking(self):
        profiles = self.ctx.state / 'profiles'
        profiles.mkdir(parents=True)
        (profiles / 'broken.json').write_text('{oops')
        snap = self.snap()
        self.assertEqual(snap['profiles'][0]['name'], 'broken')
        self.assertIsNone(snap['profiles'][0]['config'])
        self.assertIn('повреждён', snap['profiles'][0]['error'])
        self.assertIsNone(snap['config_error'])
        # readable bytes still yield a valid revision
        self.assertIsNotNone(snap['revision'])
        self.assertIsNone(snap['revision_error'])
        damaged = snap['revision']
        (profiles / 'broken.json').write_text('{"strategy": 5')
        self.assertNotEqual(self.snap()['revision'], damaged)

    def test_missing_or_invalid_config_disables_revision(self):
        (self.root / 'conf.env').unlink()
        snap = self.snap()
        self.assertIsNone(snap['config'])
        self.assertIn('Не найден конфиг', snap['config_error'])
        self.assertIsNone(snap['revision'])
        self.assertIn('conf.env', snap['revision_error'])
        (self.root / 'conf.env').write_text('strategy=general_alt11.bat\n')
        snap = self.snap()
        self.assertIn('Неполная конфигурация', snap['config_error'])
        self.assertIsNone(snap['revision'])
        self.assertIn('не прошла проверку', snap['revision_error'])
        core.write_config(self.ctx, self.old)
        snap = self.snap()
        self.assertEqual(snap['config'], self.old)
        self.assertIsNotNone(snap['revision'])
        self.assertIsNone(snap['revision_error'])

    def test_unreadable_legacy_file_disables_revision(self):
        self.ctx.state.mkdir(parents=True)
        for path in (self.ctx.known, self.ctx.state / 'previous.json'):
            path.write_text('{}')
            path.chmod(0o000)
            try:
                snap = self.snap()
                self.assertIsNone(snap['revision'], path)
                self.assertIn(str(path), snap['revision_error'])
                self.assertIn('прочитано не полностью', snap['revision_error'])
            finally:
                path.chmod(0o644)
        snap = self.snap()
        self.assertIsNone(snap['config_error'])
        self.assertIsNone(snap['profiles_error'])
        self.assertIsNotNone(snap['revision'])

    def test_unreadable_profile_file_disables_revision(self):
        profiles = self.ctx.state / 'profiles'
        profiles.mkdir(parents=True)
        (profiles / 'locked.json').write_text(json.dumps(self.old))
        (profiles / 'locked.json').chmod(0o000)
        try:
            snap = self.snap()
            self.assertIsNone(snap['revision'])
            self.assertIn('locked', snap['revision_error'])
            self.assertIn('Не удалось прочитать профиль', snap['profiles'][0]['error'])
        finally:
            (profiles / 'locked.json').chmod(0o644)
        self.assertIsNotNone(self.snap()['revision'])

    def test_profiles_listing_error_disables_revision(self):
        profiles = self.ctx.state / 'profiles'
        profiles.mkdir(parents=True)
        (profiles / 'home.json').write_text(json.dumps(self.old))
        with patch.object(Path, 'iterdir', side_effect=PermissionError('denied')):
            snap = self.snap()
        self.assertIsNone(snap['revision'])
        self.assertIn('перечислить', snap['revision_error'])
        self.assertIn('перечислить', snap['profiles_error'])

    def test_snapshot_reads_each_file_once(self):
        profiles = self.ctx.state / 'profiles'
        profiles.mkdir(parents=True)
        (profiles / 'home.json').write_text(json.dumps(self.old))
        self.ctx.known.write_text('{}')
        real_read = Path.read_bytes
        counts = {}

        def counting(path):
            counts[str(path)] = counts.get(str(path), 0) + 1
            return real_read(path)

        with self.fake_system(), patch.object(Path, 'read_bytes', counting):
            snap = core.snapshot(self.ctx)
        self.assertEqual(counts[str(self.ctx.root / 'conf.env')], 1)
        self.assertEqual(counts[str(profiles / 'home.json')], 1)
        self.assertEqual(counts[str(self.ctx.known)], 1)
        self.assertEqual(snap['revision'], self.snap()['revision'])

    def test_profiles_dir_absent_and_symlink_in_snapshot(self):
        snap = self.snap()
        self.assertEqual(snap['profiles'], [])
        self.assertIsNone(snap['profiles_error'])
        self.assertIsNone(snap['revision_error'])
        self.assertIsNotNone(snap['revision'])
        self.ctx.state.mkdir(parents=True)
        outside = self.root / 'outside'
        outside.mkdir()
        (outside / 'external.json').write_text(json.dumps(self.old))
        (self.ctx.state / 'profiles').symlink_to(outside)
        snap = self.snap()
        self.assertIn('символической', snap['profiles_error'])
        self.assertEqual(snap['profiles'], [])
        self.assertIsNone(snap['revision'])
        self.assertIn('символическая ссылка', snap['revision_error'])


class RevisionConflictTests(unittest.TestCase):
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

    def as_root(self):
        return patch.object(core.os, 'geteuid', return_value=0)

    def fake_system(self):
        def run(args, **kw):
            return subprocess.CompletedProcess(args, 1, 'inactive\n', '')
        return patch.object(core, 'command', side_effect=run)

    def snap_revision(self):
        with self.fake_system():
            return core.snapshot(self.ctx)['revision']

    def test_second_client_with_stale_revision_gets_conflict(self):
        first_revision = self.snap_revision()
        with self.as_root(), patch.object(core, 'active', return_value=False), \
             patch.object(core, 'trusted'), self.fake_system():
            core.admin_command(self.ctx, 'profile-save', 'first', expected_revision=first_revision)
        self.assertNotEqual(self.snap_revision(), first_revision)
        conf_before = (self.root / 'conf.env').read_bytes()
        with self.as_root(), patch.object(core, 'active', return_value=False), \
             patch.object(core, 'trusted'), patch.object(core, 'systemctl') as ctl, self.fake_system():
            with self.assertRaises(core.ConflictError):
                core.admin_command(self.ctx, 'profile-save', 'second', expected_revision=first_revision)
            ctl.assert_not_called()
        self.assertFalse((self.ctx.state / 'profiles' / 'second.json').exists())
        self.assertEqual((self.root / 'conf.env').read_bytes(), conf_before)

    def test_conflict_precedes_previous_json_and_restart(self):
        first_revision = self.snap_revision()
        # первый клиент меняет файлы, второй держит устаревшую revision
        with self.as_root(), patch.object(core, 'active', return_value=False), \
             patch.object(core, 'trusted'), self.fake_system():
            core.admin_command(self.ctx, 'profile-save', 'newer', expected_revision=first_revision)
        conf_before = (self.root / 'conf.env').read_bytes()
        with self.as_root(), patch.object(core, 'active', return_value=True), \
             patch.object(core, 'trusted'), patch.object(core, 'systemctl') as ctl, self.fake_system():
            with self.assertRaises(core.ConflictError):
                core.admin_command(self.ctx, 'restore-good', expected_revision=first_revision)
            ctl.assert_not_called()
        self.assertFalse((self.ctx.state / 'previous.json').exists())
        self.assertEqual((self.root / 'conf.env').read_bytes(), conf_before)

    def test_matching_revision_allows_mutation_and_changes_revision(self):
        revision = self.snap_revision()
        with self.as_root(), patch.object(core, 'active', return_value=False), \
             patch.object(core, 'trusted'), self.fake_system():
            core.admin_command(self.ctx, 'strategy', 'general_alt10.bat', expected_revision=revision)
        self.assertEqual(core.config(self.ctx)['strategy'], 'general_alt10.bat')
        self.assertNotEqual(self.snap_revision(), revision)

    def test_service_actions_stay_explicit_without_revision(self):
        with self.as_root(), patch.object(core, 'trusted'), patch.object(core, 'systemctl') as ctl:
            core.admin_command(self.ctx, 'stop')
            ctl.assert_called_once_with(self.ctx, 'stop')

    def test_unusable_snapshot_refuses_mutation_as_operation_error(self):
        self.ctx.state.mkdir(parents=True)
        known = self.ctx.known
        known.write_text('{}')
        revision = self.snap_revision()
        known.chmod(0o000)
        try:
            # fresh snapshots cannot produce a revision at all
            with self.fake_system():
                snap = core.snapshot(self.ctx)
            self.assertIsNone(snap['revision'])
            self.assertIn('known-good.json', snap['revision_error'])
            conf_before = (self.root / 'conf.env').read_bytes()
            with self.as_root(), patch.object(core, 'active', return_value=False), \
                 patch.object(core, 'trusted'), patch.object(core, 'systemctl') as ctl, self.fake_system():
                with self.assertRaises(RuntimeError) as cm:
                    core.admin_command(self.ctx, 'profile-save', 'blocked', expected_revision=revision)
            self.assertNotIsInstance(cm.exception, core.ConflictError)
            self.assertIn('прочитано не полностью', str(cm.exception))
            ctl.assert_not_called()
            self.assertFalse((self.ctx.state / 'profiles' / 'blocked.json').exists())
            self.assertEqual((self.root / 'conf.env').read_bytes(), conf_before)
        finally:
            known.chmod(0o644)
        # access restored: bytes match the snapshot again, so the flow works
        with self.as_root(), patch.object(core, 'active', return_value=False), \
             patch.object(core, 'trusted'), self.fake_system():
            core.admin_command(self.ctx, 'profile-save', 'after', expected_revision=revision)
        self.assertTrue((self.ctx.state / 'profiles' / 'after.json').exists())

    def test_busy_and_conflict_are_runtime_subclasses(self):
        self.assertTrue(issubclass(core.BusyError, RuntimeError))
        self.assertTrue(issubclass(core.ConflictError, RuntimeError))
        self.ctx.state.mkdir(parents=True, exist_ok=True)
        with self.ctx.lock.open('a') as held:
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.as_root(), patch.object(core, 'trusted'):
                with self.assertRaises(core.BusyError):
                    core.admin_command(self.ctx, 'stop')


if __name__ == '__main__':
    unittest.main()
