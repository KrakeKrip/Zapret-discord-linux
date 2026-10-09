"""Only dry-run/authorization/preflight checks; no host removal in tests."""
import importlib.util
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
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
