"""Restore archived files only in a temporary sandbox, never on the host."""
from contextlib import ExitStack, redirect_stdout
import importlib.util
import io
import os
from pathlib import Path
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/restore-backend.py'
spec = importlib.util.spec_from_file_location('restore_backend', SCRIPT)
restore = importlib.util.module_from_spec(spec)
spec.loader.exec_module(restore)


class RestoreTests(unittest.TestCase):
    def setUp(self):
        self.previous_umask = os.umask(0o022)
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.engine = self.root / 'opt/engine'
        self.engine.parent.mkdir()
        self.unit = self.root / 'system/legacy.service'
        self.unit.parent.mkdir()
        self.stage = self.root / 'stage'
        self.stage.mkdir()
        self.archive = self.root / 'legacy.tar.gz'
        self.stack = ExitStack()
        self.stack.enter_context(patch.object(restore, 'BACKEND', self.engine))
        self.stack.enter_context(patch.object(restore, 'UNIT_FILE', self.unit))

    def tearDown(self):
        self.stack.close()
        self.temp.cleanup()
        os.umask(self.previous_umask)

    def bundle(self, extra=None, missing=None):
        members = [(str(self.engine / 'nfqws').lstrip('/'), b'engine', 0o775),
                   (str(self.engine / 'service.sh').lstrip('/'), b'service', 0o755),
                   (str(self.engine / 'conf.env').lstrip('/'), b'strategy=general_alt11.bat\n', 0o664),
                   (str(self.unit).lstrip('/'), str(self.engine).encode(), 0o664),
                   ('usr/local/bin/zapret-menu', b'old menu', 0o755),
                   ('var/lib/zapret-console/profiles/home.json', b'do not overwrite', 0o644)]
        with tarfile.open(self.archive, 'w:gz') as archive:
            for name, data, mode in members:
                if missing and name.endswith('/' + missing):
                    continue
                member = tarfile.TarInfo(name)
                member.size, member.mode = len(data), mode
                archive.addfile(member, io.BytesIO(data))
            if extra:
                archive.addfile(extra)

    def test_unpack_preserves_strategy_and_excludes_menus_and_profiles(self):
        self.bundle()
        unit = restore.unpack_engine(self.archive, self.stage)
        self.assertEqual(unit, str(self.engine).encode())
        self.assertEqual((self.stage / 'conf.env').read_text(), 'strategy=general_alt11.bat\n')
        self.assertEqual(sorted(p.name for p in self.stage.iterdir()), ['conf.env', 'nfqws', 'service.sh'])
        self.assertEqual((self.stage / 'conf.env').stat().st_mode & 0o777, 0o644)
        self.assertEqual((self.stage / 'nfqws').stat().st_mode & 0o777, 0o755)

    def test_unsafe_archive_or_missing_engine_refused_before_writes(self):
        for name, kind in [('../escape', tarfile.REGTYPE),
                           (str(self.engine / 'link').lstrip('/'), tarfile.SYMTYPE),
                           (str(self.engine / 'device').lstrip('/'), tarfile.CHRTYPE)]:
            with self.subTest(name=name):
                member = tarfile.TarInfo(name)
                member.type, member.linkname = kind, '/etc/passwd'
                self.bundle(extra=member)
                with self.assertRaises(RuntimeError):
                    restore.unpack_engine(self.archive, self.stage)
                self.assertEqual(list(self.stage.iterdir()), [])
        self.bundle(missing='nfqws')
        with self.assertRaisesRegex(RuntimeError, 'отсутствует nfqws'):
            restore.unpack_engine(self.archive, self.stage)
        self.assertEqual(list(self.stage.iterdir()), [])

    def test_full_restore_starts_service_without_reinstalling_old_menu(self):
        self.bundle()
        commands = []
        def run(argv, **kwargs):
            commands.append(argv[1])
            return SimpleNamespace(returncode=0, stdout='active\n')
        installer = restore.load_installer()
        with patch.object(restore.os, 'chown'), redirect_stdout(io.StringIO()):
            restore.restore(self.archive, installer, runner=run)
        self.assertEqual(commands, ['daemon-reload', 'start', 'is-active'])
        self.assertTrue(self.unit.is_file())
        self.assertTrue((self.engine / 'nfqws').is_file())
        self.assertFalse((self.root / 'usr/local/bin/zapret-menu').exists())
        self.assertEqual((self.engine / 'conf.env').read_text(), 'strategy=general_alt11.bat\n')

    def test_existing_installation_is_not_overwritten(self):
        self.bundle()
        self.engine.mkdir()
        marker = self.engine / 'keep'
        marker.write_text('original')
        with self.assertRaisesRegex(RuntimeError, 'уже существует'):
            restore.restore(self.archive, restore.load_installer())
        self.assertEqual(marker.read_text(), 'original')
        self.assertFalse(self.unit.exists())

    def test_unprivileged_main_refused_before_reading_backups(self):
        with patch('sys.argv', [str(SCRIPT), '--restore-backend']), \
             patch.object(restore.os, 'geteuid', return_value=1000), \
             patch.object(restore, 'load_installer') as installer:
            with self.assertRaisesRegex(RuntimeError, 'sudo'):
                restore.main()
            installer.assert_not_called()
