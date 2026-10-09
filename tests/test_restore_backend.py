"""Restore archived files only in a temporary sandbox, never on the host."""
from contextlib import ExitStack, redirect_stdout
import importlib.util
import io
import os
import subprocess
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
                for member in extra if isinstance(extra, list) else [extra]:
                    archive.addfile(member)

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

    def hardlink(self, name, target):
        member = tarfile.TarInfo(str(self.engine / name).lstrip('/'))
        member.type = tarfile.LNKTYPE
        member.linkname = target
        return member

    def test_gnu_tar_user_lists_hardlinks_are_restored_with_same_inode(self):
        source = self.root / 'source'
        source_engine = source / str(self.engine).lstrip('/')
        source_engine.mkdir(parents=True)
        for name, content in [('nfqws', b'engine'), ('service.sh', b'service'),
                              ('conf.env', b'strategy=general_alt11.bat\n')]:
            path = source_engine / name
            path.write_bytes(content)
            path.chmod(0o755 if name != 'conf.env' else 0o644)
        lists = source_engine / 'zapret-latest/lists'
        user_lists = source_engine / 'user-lists'
        lists.mkdir(parents=True)
        user_lists.mkdir()
        names = ('list-exclude-user.txt', 'list-general-user.txt', 'ipset-exclude-user.txt')
        for name in names:
            (lists / name).write_text('user data')
            os.link(lists / name, user_lists / name)
        source_unit = source / str(self.unit).lstrip('/')
        source_unit.parent.mkdir(parents=True)
        source_unit.write_text(str(self.engine))
        subprocess.run(['/usr/bin/tar', '-czf', str(self.archive), '-C', str(source), '--',
                        str(self.engine).lstrip('/'), str(self.unit).lstrip('/')], check=True)
        with tarfile.open(self.archive) as archive:
            self.assertEqual(sum(member.islnk() for member in archive.getmembers()), 3)
        restore.unpack_engine(self.archive, self.stage)
        for name in names:
            a, b = self.stage / 'zapret-latest/lists' / name, self.stage / 'user-lists' / name
            self.assertEqual(a.read_text(), 'user data')
            self.assertEqual(a.stat().st_ino, b.stat().st_ino)

    def test_forward_hardlink_chain_resolves_to_regular_file(self):
        first = self.hardlink('user-lists/first', str(self.engine / 'user-lists/second').lstrip('/'))
        second = self.hardlink('user-lists/second', str(self.engine / 'conf.env').lstrip('/'))
        self.bundle(extra=[first, second])
        restore.unpack_engine(self.archive, self.stage)
        self.assertEqual((self.stage / 'user-lists/first').stat().st_ino,
                         (self.stage / 'conf.env').stat().st_ino)

    def test_invalid_hardlink_targets_are_refused_before_any_writes(self):
        for target in ['/etc/passwd', '../escape', str(self.unit).lstrip('/'),
                       str(self.engine / 'missing').lstrip('/')]:
            with self.subTest(target=target):
                self.bundle(extra=self.hardlink('user-lists/link', target))
                with self.assertRaises(RuntimeError):
                    restore.unpack_engine(self.archive, self.stage)
                self.assertEqual(list(self.stage.iterdir()), [])

    def test_hardlink_cycle_is_refused_before_any_writes(self):
        first = self.hardlink('first', str(self.engine / 'second').lstrip('/'))
        second = self.hardlink('second', str(self.engine / 'first').lstrip('/'))
        self.bundle(extra=[first, second])
        with self.assertRaisesRegex(RuntimeError, 'Цикл'):
            restore.unpack_engine(self.archive, self.stage)
        self.assertEqual(list(self.stage.iterdir()), [])
