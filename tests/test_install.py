"""Installer integration uses DESTDIR; never changes the host installation."""
from contextlib import redirect_stdout, redirect_stderr
import fcntl
import importlib.util
import io
import json
import os
import runpy
import shutil
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('installer', ROOT / 'scripts/install.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.previous_umask = os.umask(0o022)
        self.temp = tempfile.TemporaryDirectory()
        self.stage = Path(self.temp.name)
        self.prefix = self.stage / 'usr/local'
        self.base = self.prefix / 'lib/zapret-console'
        self.settings = self.stage / 'etc/zapret-console/settings.json'
        self.state = self.stage / 'var/lib/zapret-console'
        self.launcher = self.prefix / 'bin/zapret-console'
        self.output = redirect_stdout(io.StringIO())
        self.output.__enter__()

    def tearDown(self):
        self.output.__exit__(None, None, None)
        self.temp.cleanup()
        os.umask(self.previous_umask)

    def runner(self, argv):
        subprocess.run(argv, check=True, capture_output=True, text=True)

    def install(self, **kwargs):
        return installer.install(ROOT, str(self.stage), runner=kwargs.pop('runner', self.runner), **kwargs)

    def test_staged_install_has_all_frontends_resources_and_launchers(self):
        release = self.install()
        self.assertEqual((self.base / 'current').resolve(), release)
        for relative in ('app/zapret_console/app.py', 'app/zapret_console/gui/qml/Main.qml', 'app/zapret_console/client.py'):
            self.assertTrue((release / relative).is_file())
        self.assertFalse((release / 'venv').exists())  # No network by default.
        self.assertTrue(os.access(self.launcher, os.X_OK))
        self.assertEqual(self.launcher.stat().st_mode & 0o777, 0o755)
        result = subprocess.run([str(self.launcher), '--version'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('0.3.1', result.stdout)
        for name in ('zapret-console.desktop', 'zapret-console-tui.desktop'):
            path = self.prefix / 'share/applications' / name
            self.assertTrue(path.is_file())
            if shutil.which('desktop-file-validate'):
                subprocess.run(['desktop-file-validate', str(path)], check=True, capture_output=True)
        self.assertIn('Terminal=false', (self.prefix / 'share/applications/zapret-console.desktop').read_text())
        self.assertIn('Terminal=true', (self.prefix / 'share/applications/zapret-console-tui.desktop').read_text())

    def test_update_preserves_custom_settings_profiles_and_previous_release(self):
        first = self.install(backend_root='/opt/custom', unit='custom.service')
        before = self.settings.read_bytes()
        (self.state / 'profiles').mkdir()
        profile = self.state / 'profiles/home.json'
        profile.write_text('original profile')
        second = self.install(ui='tui')
        self.assertNotEqual(first, second)
        self.assertTrue(first.exists())
        self.assertEqual(self.settings.read_bytes(), before)
        self.assertEqual(profile.read_text(), 'original profile')
        self.assertFalse((self.prefix / 'share/applications/zapret-console.desktop').exists())
        self.assertTrue((self.prefix / 'share/applications/zapret-console-tui.desktop').exists())

    def test_dependency_failure_keeps_previous_release_and_files(self):
        first = self.install()
        before = self.launcher.read_bytes(), self.settings.read_bytes()
        def fail(argv):
            if 'venv' in argv:
                raise subprocess.CalledProcessError(1, argv)
            self.runner(argv)
        with self.assertRaises(subprocess.CalledProcessError):
            self.install(with_deps=True, runner=fail)
        self.assertEqual((self.base / 'current').resolve(), first)
        self.assertEqual((self.launcher.read_bytes(), self.settings.read_bytes()), before)
        self.assertEqual(list((self.base / 'releases').iterdir()), [first])

    def test_post_switch_failure_rolls_back_all_published_files(self):
        first = self.install()
        before = self.settings.read_bytes()
        desktop = self.prefix / 'share/applications/zapret-console.desktop'
        original = desktop.read_bytes()
        def fail(argv):
            if argv[0] == str(self.launcher):
                raise subprocess.CalledProcessError(1, argv)
            self.runner(argv)
        with self.assertRaises(subprocess.CalledProcessError):
            self.install(ui='none', backend_root='/opt/new', runner=fail)
        self.assertEqual((self.base / 'current').resolve(), first)
        self.assertEqual(self.settings.read_bytes(), before)
        self.assertEqual(desktop.read_bytes(), original)
        self.assertEqual(list((self.base / 'releases').iterdir()), [first])

    def test_first_install_failure_removes_new_artifacts(self):
        def fail(argv):
            if argv[0] == str(self.launcher):
                raise subprocess.CalledProcessError(1, argv)
            self.runner(argv)
        with self.assertRaises(subprocess.CalledProcessError):
            self.install(runner=fail)
        self.assertFalse(self.launcher.exists())
        self.assertFalse(self.settings.exists())
        self.assertFalse((self.base / 'current').exists())

    def test_install_and_uninstall_refuse_busy_lock(self):
        self.install()
        with (self.base / '.install.lock').open('a') as stream:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(RuntimeError, 'уже выполняется'):
                self.install()
            with self.assertRaisesRegex(RuntimeError, 'уже выполняется'):
                installer.uninstall(str(self.stage))
        self.assertTrue(self.launcher.exists())

    def test_symlinked_parent_cannot_redirect_install_or_uninstall(self):
        external = self.stage / 'external'
        external.mkdir()
        (self.stage / 'usr').symlink_to(external, target_is_directory=True)
        for operation in (lambda: self.install(), lambda: installer.uninstall(str(self.stage))):
            with self.assertRaisesRegex(RuntimeError, 'Ссылка'):
                operation()
        self.assertEqual(list(external.iterdir()), [])

    def test_symlinked_settings_and_launcher_are_refused(self):
        external = self.stage / 'external'
        external.write_text('untouched')
        for target in (self.settings, self.launcher):
            target.parent.mkdir(parents=True, exist_ok=True)
            target.symlink_to(external)
            with self.assertRaisesRegex(RuntimeError, 'Ссылка'):
                self.install()
            target.unlink()
        self.assertEqual(external.read_text(), 'untouched')

    def test_current_outside_releases_is_refused(self):
        self.base.mkdir(parents=True)
        (self.base / 'current').symlink_to(self.stage)
        with self.assertRaises(ValueError):
            self.install()
        self.assertFalse(self.launcher.exists())

    def test_uninstall_preserves_settings_and_state(self):
        self.install()
        settings = self.settings.read_bytes()
        profile = self.state / 'known-good.json'
        profile.write_text('original')
        installer.uninstall(str(self.stage))
        self.assertFalse(self.launcher.exists())
        self.assertFalse((self.base / 'current').exists())
        self.assertEqual(self.settings.read_bytes(), settings)
        self.assertEqual(profile.read_text(), 'original')
        self.assertEqual([p.name for p in self.base.iterdir()], ['.install.lock'])
        self.assertFalse((self.prefix / 'share/applications/zapret-console.desktop').exists())

    def test_invalid_settings_do_not_publish_application(self):
        for kwargs in ({'backend_root': 'relative'}, {'unit': 'bad\nunit'}, {'ui': 'bad'}):
            with self.assertRaises(ValueError):
                self.install(**kwargs)
        self.assertFalse(self.launcher.exists())

    def test_dependencies_use_exact_project_pins(self):
        self.assertEqual(installer.requirements(ROOT, 'all'), ['PySide6==6.12.0'])
        self.assertEqual(installer.requirements(ROOT, 'tui'), [])
        self.assertEqual(installer.requirements(ROOT, 'none'), [])

    def test_legacy_tree_is_adopted_and_failure_preserves_legacy_launcher(self):
        legacy = self.base / 'zapret_console'
        legacy.mkdir(parents=True)
        (legacy / 'app.py').write_text('legacy')
        self.launcher.parent.mkdir(parents=True)
        self.launcher.write_text('#!/bin/sh\necho legacy\n')
        self.launcher.chmod(0o755)
        original = self.launcher.read_bytes()
        def fail(argv):
            if argv[0] == str(self.launcher):
                raise subprocess.CalledProcessError(1, argv)
            self.runner(argv)
        with self.assertRaises(subprocess.CalledProcessError):
            self.install(runner=fail)
        self.assertEqual(self.launcher.read_bytes(), original)
        self.assertEqual((legacy / 'app.py').read_text(), 'legacy')
        self.install()
        self.assertTrue((self.base / 'current').exists())


    def test_writable_destination_is_refused(self):
        self.base.mkdir(parents=True)
        self.base.chmod(0o777)
        with self.assertRaisesRegex(RuntimeError, 'посторонней записи'):
            self.install()
        self.assertFalse(self.launcher.exists())


    def test_launcher_ignores_pythonpath_and_cli_needs_no_ui_runtime(self):
        self.install(ui='none')
        poison = self.stage / 'poison/zapret_console'
        poison.mkdir(parents=True)
        (poison / '__init__.py').write_text('raise RuntimeError("poisoned import")')
        result = subprocess.run([str(self.launcher), '--help'], env=dict(os.environ, PYTHONPATH=str(poison.parent), PYTHONHOME='/invalid'), capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--gui', result.stdout)
        self.assertFalse((self.prefix / 'share/applications/zapret-console.desktop').exists())
        self.assertFalse((self.prefix / 'share/applications/zapret-console-tui.desktop').exists())


    def test_terminal_launcher_needs_no_venv_even_when_explicitly_selected(self):
        self.install(ui='tui')
        for args in ([], ['--tui'], ['--legacy-menu']):
            result = subprocess.run([str(self.launcher), *args], stdin=subprocess.DEVNULL, capture_output=True, text=True)
            self.assertNotIn('зависимости не установлены', result.stderr)
            self.assertNotIn('textual', result.stderr.lower())
            self.assertIn('Запусти zapret-console в терминале', result.stderr)
        gui = subprocess.run([str(self.launcher), '--gui'], capture_output=True, text=True)
        self.assertNotEqual(gui.returncode, 0)
        self.assertIn('Графические зависимости не установлены', gui.stderr)

    def test_root_launcher_refuses_writable_imported_module_before_import(self):
        release = self.install()
        core = release / 'app/zapret_console/core.py'
        core.write_text('raise AssertionError("unsafe module executed")')
        real_stat = Path.stat
        def root_stat(path, *args, **kwargs):
            result = list(real_stat(path, *args, **kwargs))
            result[4] = 0  # Fixture stands in for root-owned installed files.
            if path == core:
                result[0] |= 0o022
            return os.stat_result(result)
        with patch('os.geteuid', return_value=0), patch.object(Path, 'stat', root_stat), \
             patch('sys.argv', [str(self.launcher), '--status']), redirect_stdout(io.StringIO()), \
             redirect_stderr(io.StringIO()) as error:
            with self.assertRaises(SystemExit) as exit_code:
                runpy.run_path(str(self.launcher), run_name='__main__')
        self.assertEqual(exit_code.exception.code, 1)
        self.assertIn('core.py', error.getvalue())
        self.assertIn('Недоверенный', error.getvalue())


    def test_same_explicit_settings_are_preserved_byte_for_byte(self):
        self.install()
        original = b'{"service":"custom.service", "backend_root":"/opt/custom", "extra":42}\n'
        self.settings.write_bytes(original)
        self.install(backend_root='/opt/custom', unit='custom.service')
        self.assertEqual(self.settings.read_bytes(), original)
        self.install(backend_root='/opt/new')
        self.assertEqual(json.loads(self.settings.read_bytes())['extra'], 42)


    def test_only_verified_root_legacy_directory_permissions_are_normalized(self):
        package = self.base / 'zapret_console'
        package.mkdir(parents=True)
        (package / '__init__.py').write_text("__version__ = '0.2.0'\n")
        (package / 'app.py').write_text('legacy')
        self.base.chmod(0o775)
        real_stat = Path.stat
        def root_stat(path, *args, **kwargs):
            result = list(real_stat(path, *args, **kwargs))
            result[4] = result[5] = 0
            return os.stat_result(result)
        with patch('os.geteuid', return_value=0), patch.object(Path, 'stat', root_stat):
            installer.repair_legacy_base(self.base)
        self.assertEqual(self.base.stat().st_mode & 0o777, 0o755)

    def test_legacy_repair_does_not_relax_world_writable_or_unknown_install(self):
        self.base.mkdir(parents=True)
        self.base.chmod(0o777)
        with patch('os.geteuid', return_value=0):
            installer.repair_legacy_base(self.base)
        self.assertEqual(self.base.stat().st_mode & 0o777, 0o777)
        self.base.chmod(0o775)
        with patch('os.geteuid', return_value=0):
            installer.repair_legacy_base(self.base)
        self.assertEqual(self.base.stat().st_mode & 0o777, 0o775)
