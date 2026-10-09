import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from zapret_console import setup
import tempfile
import unittest
from unittest.mock import patch


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.root = self.base / 'backend'
        self.units = self.base / 'units'
        self.units.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def fake_runner(self, args, **kw):
        if args[:2] == ['git', 'init']:
            self.stage = Path(args[2])
            (self.stage / 'service.sh').write_text('#!/bin/bash\n')
        if 'download-deps' in args:
            (self.stage / 'nfqws').write_text('engine fixture')
            (self.stage / 'zapret-latest').mkdir()
            (self.stage / 'zapret-latest/general_alt11.bat').write_text('fixture')

    def create(self, runner=None, strategy='general_alt11.bat'):
        with patch.object(setup.os, 'listdir', return_value=['lo', 'eth-test']):
            setup.create_backend(self.root, 'eth-test', strategy, 'zapret.service',
                                 runner=runner or self.fake_runner, system_dir=self.units)

    def test_adopt_existing_preserves_configuration(self):
        self.root.mkdir()
        for name in ('nfqws', 'service.sh', 'conf.env'):
            (self.root / name).write_text('original')
        self.assertEqual(setup.backend_plan(self.root), 'adopt')
        with self.assertRaisesRegex(RuntimeError, 'не должна заменяться'):
            self.create()
        self.assertEqual((self.root / 'conf.env').read_text(), 'original')

    def test_partial_install_is_not_overwritten(self):
        self.root.mkdir()
        (self.root / 'nfqws').write_text('original')
        with self.assertRaisesRegex(RuntimeError, 'неполная'):
            setup.backend_plan(self.root)
        self.assertEqual((self.root / 'nfqws').read_text(), 'original')

    def test_fresh_install_pins_source_and_creates_readable_profile(self):
        from unittest.mock import Mock
        runner = Mock(side_effect=self.fake_runner)
        self.create(runner)
        self.assertEqual(self.root.stat().st_mode & 0o777, 0o755)
        self.assertIn('strategy=general_alt11.bat', (self.root / 'conf.env').read_text())
        self.assertIn(str(self.root), (self.units / 'zapret.service').read_text())
        self.assertTrue(any(setup.ADAPTER_REV in c.args[0] for c in runner.call_args_list))
        self.assertFalse(any('start' in c.args[0] or 'enable' in c.args[0] for c in runner.call_args_list))

    def test_download_failure_cleans_stage(self):
        def fail(args, **kw):
            self.fake_runner(args, **kw)
            if 'download-deps' in args:
                raise RuntimeError('download failed')
        with self.assertRaisesRegex(RuntimeError, 'download failed'):
            self.create(fail)
        self.assertFalse(self.root.exists())
        self.assertEqual(list(self.base.glob('.zapret-setup-*')), [])

    def test_service_registration_failure_removes_new_install(self):
        count = 0
        def fail_once(args, **kw):
            nonlocal count
            self.fake_runner(args, **kw)
            if args == ['systemctl', 'daemon-reload']:
                count += 1
                if count == 1:
                    raise RuntimeError('registration failed')
        with self.assertRaisesRegex(RuntimeError, 'registration failed'):
            self.create(fail_once)
        self.assertFalse(self.root.exists())
        self.assertFalse((self.units / 'zapret.service').exists())

    def test_unknown_strategy_does_not_commit_installation(self):
        with self.assertRaisesRegex(ValueError, 'Стратегия отсутствует'):
            self.create(strategy='missing.bat')
        self.assertFalse(self.root.exists())

    def test_systemd_path_injection_is_rejected(self):
        for root in (Path('/opt/bad path'), Path('/opt/../bad'), Path('/opt/bad\nExecStart=evil')):
            with self.assertRaises(ValueError):
                setup.unit_text(root)


class DependencyTests(unittest.TestCase):
    def test_gui_packages_are_optional_but_venv_is_present(self):
        self.assertIn('python3-venv', setup.dependency_packages('tui'))
        self.assertNotIn('pkexec', setup.dependency_packages('tui'))
        self.assertIn('pkexec', setup.dependency_packages('all'))
        self.assertIn('libxcb-cursor0', setup.dependency_packages('all'))

    def test_missing_native_dependency_installs_before_application(self):
        import subprocess
        with patch.object(setup.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, '', 'missing')), patch.object(setup, 'run') as runner:
            setup.ensure_dependencies('all')
        self.assertEqual(runner.call_args_list[0].args[0], ['apt-get', 'update'])
        self.assertIn('python3-venv', runner.call_args_list[1].args[0])
        self.assertIn('pkexec', runner.call_args_list[1].args[0])

    def test_installed_dependencies_do_not_run_apt(self):
        import subprocess
        installed = '\n'.join(['installed'] * len(setup.dependency_packages('tui'))) + '\n'
        with patch.object(setup.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, installed, '')), patch.object(setup, 'run') as runner:
            setup.ensure_dependencies('tui')
        runner.assert_not_called()
