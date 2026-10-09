"""Simple terminal menu routing; no UI framework or live authorization."""
import io
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from zapret_console import app as cli


class TerminalMenuTests(unittest.TestCase):
    def test_default_and_compatible_flags_open_the_same_simple_menu(self):
        for flag in ([], ['--tui'], ['--legacy-menu']):
            with self.subTest(flag=flag), patch.object(cli.sys, 'argv', ['zapret-console', *flag]), \
                 patch.object(cli, 'load_context'), patch.object(cli.sys.stdin, 'isatty', return_value=True), \
                 patch.object(cli.core, 'preflight', return_value=[]), \
                 patch.object(cli, 'status', return_value='status'), \
                 patch.object(cli.core, 'active', return_value=False), \
                 patch.object(cli, 'menu', return_value='exit') as menu, \
                 patch.object(cli, 'privileged') as mutation:
                cli.main()
                self.assertEqual(menu.call_count, 1)
                entries = dict(menu.call_args.args[1])
                self.assertEqual(entries['toggle'], 'Включить')
                self.assertIn('strategy', entries)
                self.assertIn('good', entries)
                mutation.assert_not_called()

    def test_noninteractive_menu_explains_how_to_use_cli(self):
        with patch.object(cli.sys, 'argv', ['zapret-console']), patch.object(cli, 'load_context'), \
             patch.object(cli.sys.stdin, 'isatty', return_value=False), patch.object(cli, 'menu') as menu:
            with self.assertRaisesRegex(RuntimeError, '--status и --diagnose'):
                cli.main()
            menu.assert_not_called()

    def test_menu_actions_use_existing_shared_administrative_path(self):
        for active, action in ((False, 'start'), (True, 'stop')):
            with self.subTest(active=active), patch.object(cli.sys, 'argv', ['zapret-console']), \
                 patch.object(cli, 'load_context'), patch.object(cli.sys.stdin, 'isatty', return_value=True), \
                 patch.object(cli.core, 'preflight', return_value=[]), \
                 patch.object(cli, 'status', return_value='status'), \
                 patch.object(cli.core, 'active', return_value=active), \
                 patch.object(cli, 'menu', side_effect=['toggle', 'exit']), \
                 patch.object(cli, 'privileged') as mutation:
                cli.main()
                mutation.assert_called_once_with(action)

    def test_cli_mode_guards_do_not_load_context(self):
        for args in [['--gui', '--tui'], ['--tui', '--status'], ['--tui', '--legacy-menu'], ['--legacy-menu', '--status']]:
            with self.subTest(args=args), patch.object(cli.sys, 'argv', ['zapret-console'] + args), \
                 patch.object(cli, 'load_context') as context, patch('sys.stderr', new_callable=io.StringIO):
                with self.assertRaises(SystemExit) as code:
                    cli.main()
                self.assertEqual(code.exception.code, 2)
                context.assert_not_called()

    def test_menu_and_cli_imports_do_not_import_ui_libraries(self):
        result = subprocess.run([sys.executable, '-c', 'import sys; import zapret_console.app; import zapret_console.client; assert "textual" not in sys.modules; assert "PySide6" not in sys.modules'],
                                env=dict(os.environ, PYTHONPATH=str(ROOT / 'src')), capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
