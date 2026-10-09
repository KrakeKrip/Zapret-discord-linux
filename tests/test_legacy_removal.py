"""Preflight and sandbox migrations; never remove files from the host installation."""
import importlib.util
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from contextlib import ExitStack, redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/remove-legacy-backend.py'
spec = importlib.util.spec_from_file_location('legacy_removal', SCRIPT)
removal = importlib.util.module_from_spec(spec)
spec.loader.exec_module(removal)


class RemovalPreflightTests(unittest.TestCase):
    def test_explicit_removal_flag_is_required(self):
        result = subprocess.run([sys.executable, '-I', str(SCRIPT)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn('--remove-legacy-backend', result.stderr)

    def test_dry_run_does_not_start_system_commands_or_delete(self):
        with patch('sys.argv', [str(SCRIPT), '--remove-legacy-backend', '--dry-run']), \
             patch.object(removal.subprocess, 'run') as command, patch.object(removal.shutil, 'rmtree') as delete, \
             redirect_stdout(io.StringIO()) as output:
            removal.main()
        command.assert_not_called()
        delete.assert_not_called()
        self.assertIn('сохраняются', output.getvalue())

    def test_unprivileged_execution_stops_before_mutations(self):
        with patch('sys.argv', [str(SCRIPT), '--remove-legacy-backend']), \
             patch.object(removal.os, 'geteuid', return_value=1000), \
             patch.object(removal.subprocess, 'run') as command, patch.object(removal.shutil, 'rmtree') as delete, \
             redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, 'авторизация'):
                removal.main()
        command.assert_not_called()
        delete.assert_not_called()

    def test_symlinked_backend_is_refused_before_system_commands(self):
        with tempfile.TemporaryDirectory() as folder:
            backend = Path(folder) / 'backend'
            backend.symlink_to(Path(folder))
            with patch('sys.argv', [str(SCRIPT), '--remove-legacy-backend']), \
                 patch.object(removal, 'BACKEND', backend), patch.object(removal.os, 'geteuid', return_value=0), \
                 patch.object(removal.subprocess, 'run') as command, patch.object(removal.shutil, 'rmtree') as delete, \
                 redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(RuntimeError, 'Неподходящий путь'):
                    removal.main()
            command.assert_not_called()
            delete.assert_not_called()


class RemovalMigrationTests(unittest.TestCase):
    def exercise(self, *, install_failure=False, residual=None, log_symlink=False):
        with tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
            root = Path(folder)
            backend, unit, menu = root / 'backend', root / 'legacy.service', root / 'menu'
            backend.mkdir()
            (backend / 'nfqws').write_text('legacy engine')
            unit.write_text(str(backend))
            menu.write_text(str(backend))
            settings, profiles = root / 'settings.json', root / 'profiles.json'
            settings.write_text('preserved settings')
            profiles.write_text('preserved profiles')
            backups, proc = root / 'backups', root / 'proc'
            proc.mkdir()
            if residual == 'process':
                (proc / '123').mkdir()
                (proc / '123/cmdline').write_bytes(str(backend / 'nfqws').encode() + b'\0')
            if log_symlink:
                backups.mkdir(mode=0o700)
                (backups / 'migration.log').symlink_to(settings)
            checked, events = [], []
            real_installer = removal.load_installer()
            actual_uid = removal.os.geteuid()

            def check_path(path):
                checked.append(Path(path))
                # Use the real permission/symlink validator with the sandbox owner.
                with patch.object(removal.os, 'geteuid', return_value=actual_uid):
                    return real_installer.check_path(path)

            def install(source, *, ui, runner):
                events.append('install')
                self.assertEqual(ui, 'all')
                self.assertTrue(backend.exists())
                if install_failure:
                    raise RuntimeError('test installation failed')

            def command(argv, **kwargs):
                if argv[0] == '/usr/bin/tar':
                    events.append('archive')
                    Path(argv[2]).write_bytes(b'test archive')
                elif argv[0] == '/usr/bin/systemctl':
                    events.append(argv[1])
                    if argv[1] == 'is-active':
                        return SimpleNamespace(returncode=0, stdout='active' if residual == 'service' else 'inactive')
                elif argv[0] == '/test/nft':
                    return SimpleNamespace(returncode=0 if residual == 'firewall' else 1)
                else:
                    self.fail(f'Unexpected command: {argv}')
                return SimpleNamespace(returncode=0)

            for name, value in [('BACKEND', backend), ('UNIT_FILE', unit), ('OLD_MENU', menu),
                                ('BACKUP_DIR', backups), ('PROC_DIR', proc), ('OLD_STATE', root / 'old-state')]:
                stack.enter_context(patch.object(removal, name, value))
            stack.enter_context(patch('sys.argv', [str(SCRIPT), '--remove-legacy-backend']))
            stack.enter_context(patch.object(removal.os, 'geteuid', return_value=0))
            # Root ownership preflight is covered separately; fixtures belong to the test user.
            stack.enter_context(patch.object(removal, 'check_legacy_installation'))
            stack.enter_context(patch.object(removal, 'load_installer', return_value=SimpleNamespace(check_path=check_path, install=install)))
            stack.enter_context(patch.object(removal.subprocess, 'run', side_effect=command))
            stack.enter_context(patch.object(removal.shutil, 'which', return_value='/test/nft'))
            stack.enter_context(redirect_stdout(io.StringIO()))
            error = None
            try:
                removal.main()
            except RuntimeError as exc:
                error = str(exc)
            self.assertEqual(settings.read_text(), 'preserved settings')
            self.assertEqual(profiles.read_text(), 'preserved profiles')
            self.assertFalse(any(str(path).startswith('/var/log') for path in checked))
            self.assertIn(backups / 'migration.log', checked)
            if install_failure or residual or log_symlink:
                self.assertIsNotNone(error)
                self.assertTrue(all(path.exists() for path in (backend, unit, menu)))
                self.assertNotIn('daemon-reload', events)
            else:
                self.assertIsNone(error)
                self.assertFalse(any(path.exists() for path in (backend, unit, menu)))
                self.assertEqual(events, ['archive', 'install', 'stop', 'disable', 'is-active', 'daemon-reload'])
            if log_symlink:
                self.assertIn('Ссылка', error)
                self.assertEqual(events, [])
            else:
                self.assertEqual(backups.stat().st_mode & 0o777, 0o700)
                self.assertEqual((backups / 'migration.log').stat().st_mode & 0o777, 0o600)
                self.assertEqual(len(list(backups.glob('legacy-*.tar.gz'))), 1)
            if install_failure:
                self.assertEqual(events, ['archive', 'install'])

    def test_complete_migration_uses_protected_log_and_preserves_own_data(self):
        self.exercise()

    def test_failed_installation_keeps_legacy_service_and_files(self):
        self.exercise(install_failure=True)

    def test_residual_service_process_or_firewall_prevents_removal(self):
        for residual in ('service', 'process', 'firewall'):
            with self.subTest(residual=residual):
                self.exercise(residual=residual)

    def test_symlinked_log_is_rejected_before_archive_or_install(self):
        self.exercise(log_symlink=True)
