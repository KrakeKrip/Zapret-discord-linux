"""Textual pilot, lifecycle and CAS coexistence; never authorizes live changes."""
import asyncio
import importlib.util
import io
import json
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from zapret_console import app as cli, core
from zapret_console.tui.app import run_tui

HAVE_TEXTUAL = importlib.util.find_spec('textual') is not None
if HAVE_TEXTUAL:
    from zapret_console.tui.ui import ZapretApp, ProfileName, Confirm
    from textual.widgets import Button, Input, Select, TabbedContent, TextArea, Footer

CONFIG = {'interface': 'any', 'strategy': 'general_alt11.bat', 'gamefiltertcp': 'false',
          'gamefilterudp': 'false', 'firewall_backend': 'auto'}
SNAPSHOT = {'revision': 'a' * 64, 'revision_error': None, 'config': dict(CONFIG),
            'profiles': [{'name': 'home', 'config': dict(CONFIG)}, {'name': 'broken', 'config': None, 'error': 'повреждён'}],
            'service_state': 'active', 'autostart': 'enabled'}


class FakeBackend:
    requires_terminal = False
    def __init__(self):
        self.data = dict(SNAPSHOT)
        self.names = ['general_alt11.bat', 'general_alt10.bat']
        self.requests = []
        self.result = {'ok': True, 'code': 'ok', 'message': ''}
        self.gate = None
        self.read_error = None
        self.read_count = 0

    def snapshot(self):
        self.read_count += 1
        if self.read_error:
            raise RuntimeError(self.read_error)
        return self.data

    def strategies(self):
        return self.names

    def request(self, action, value, revision):
        self.requests.append((action, value, revision))
        if self.gate:
            self.gate.wait(10)
        return self.result

    def diagnose(self, privileged=False):
        return {'report': 'VPN не подтверждает работу zapret. Голос проверяется отдельно.'}

    def journal(self):
        return {'text': '[red]literal log[/red]', 'warning': 'Нет доступа к части записей', 'ok': True}


class TuiEntryTests(unittest.TestCase):
    def test_root_and_no_tty_refused_before_start(self):
        with patch('zapret_console.tui.app.os.geteuid', return_value=0), patch('sys.stdout', new_callable=io.StringIO):
            self.assertEqual(run_tui(), 1)
        with patch('zapret_console.tui.app.os.geteuid', return_value=1000), \
             patch('sys.stdin.isatty', return_value=False), patch('sys.stdout', new_callable=io.StringIO):
            self.assertEqual(run_tui(), 1)

    def test_cli_mode_guards_do_not_load_context(self):
        for args in [['--gui', '--tui'], ['--tui', '--status'], ['--tui', '--legacy-menu'], ['--legacy-menu', '--status']]:
            with self.subTest(args=args), patch.object(cli.sys, 'argv', ['zapret-console'] + args), \
                 patch.object(cli, 'load_context') as context, patch('sys.stderr', new_callable=io.StringIO):
                with self.assertRaises(SystemExit) as code:
                    cli.main()
                self.assertEqual(code.exception.code, 2)
                context.assert_not_called()

    def test_cli_imports_do_not_import_ui_libraries(self):
        r = subprocess.run([sys.executable, '-c', 'import sys; import zapret_console.app; import zapret_console.client; assert "textual" not in sys.modules; assert "PySide6" not in sys.modules'],
                           env=dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / 'src')), capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)


@unittest.skipUnless(HAVE_TEXTUAL, 'Textual не установлен: extra tui')
class TuiTests(unittest.IsolatedAsyncioTestCase):
    async def idle(self, app):
        for _ in range(200):
            await asyncio.sleep(.01)
            if app.pending is None:
                return
        self.fail('TUI operation did not finish')

    async def test_snapshot_without_display_and_narrow_terminal(self):
        backend = FakeBackend()
        with patch.dict(os.environ, {'DISPLAY': '', 'WAYLAND_DISPLAY': ''}):
            app = ZapretApp(backend)
            async with app.run_test(size=(80,24)) as pilot:
                await self.idle(app)
                self.assertEqual(app.snapshot['revision'], 'a' * 64)
                self.assertEqual(backend.requests, [])
                event = app.query_one('#event')
                self.assertLessEqual(event.region.bottom, app.query_one(Footer).region.y)
                self.assertGreater(event.region.height, 0)
                self.assertTrue(app.query_one('#strategy-apply', Button).disabled)
                app.query_one(TabbedContent).active = 'strategies'
                await pilot.pause()
                app.query_one('#strategy-search', Input).value = 'does-not-exist'
                await pilot.pause()
                self.assertIn('general_alt11', str(app.query_one('#current-strategy').render()))
                self.assertTrue(app.query_one('#strategy-apply', Button).disabled)
                await pilot.click('#strategy-apply')
                self.assertEqual(backend.requests, [])

    async def test_profile_modal_captures_revision_and_cancel_does_not_request(self):
        backend = FakeBackend()
        app = ZapretApp(backend)
        async with app.run_test(size=(110,34)) as pilot:
            await self.idle(app)
            app.query_one(TabbedContent).active = 'profiles'
            await pilot.pause()
            await pilot.click('#profile-save')
            self.assertIsInstance(app.screen, ProfileName)
            app.screen.query_one(Input).value = 'mobile'
            await pilot.pause()
            backend.data = dict(SNAPSHOT, revision='b' * 64)
            app.action_refresh()
            await self.idle(app)
            await pilot.click('#save-name')
            await self.idle(app)
            self.assertEqual(backend.requests, [('profile-save', 'mobile', 'a' * 64)])
            await pilot.click('#profile-save')
            await pilot.press('escape')
            self.assertEqual(len(backend.requests), 1)

    async def test_invalid_name_and_revision_loss_prevent_authorization(self):
        backend = FakeBackend()
        app = ZapretApp(backend)
        async with app.run_test(size=(110,34)) as pilot:
            await self.idle(app)
            app.query_one(TabbedContent).active = 'profiles'
            await pilot.pause()
            await pilot.click('#profile-save')
            app.screen.query_one(Input).value = 'bad name'
            await pilot.pause()
            self.assertTrue(app.screen.query_one('#save-name', Button).disabled)
            await pilot.press('enter')
            self.assertEqual(backend.requests, [])
            app.screen.query_one(Input).value = 'mobile'
            backend.data = dict(SNAPSHOT, revision=None, revision_error='unreadable')
            app.action_refresh()
            await self.idle(app)
            self.assertTrue(app.screen.query_one('#save-name', Button).disabled)
            await pilot.press('enter', 'escape')
            self.assertEqual(backend.requests, [])

    async def test_replace_confirmation_safe_focus_and_old_revision(self):
        backend = FakeBackend()
        app = ZapretApp(backend)
        async with app.run_test(size=(110,34)) as pilot:
            await self.idle(app)
            app.query_one(TabbedContent).active = 'profiles'
            app.query_one('#profile-select', Select).value = 'home'
            await pilot.pause()
            await pilot.click('#profile-delete')
            self.assertIsInstance(app.screen, Confirm)
            await pilot.press('enter')
            self.assertEqual(backend.requests, [])
            await pilot.click('#profile-replace')
            backend.data = dict(SNAPSHOT, revision='b' * 64)
            app.action_refresh()
            await self.idle(app)
            await pilot.click('#confirm')
            await self.idle(app)
            self.assertEqual(backend.requests[-1], ('profile-replace', 'home', 'a' * 64))

    async def test_busy_and_close_do_not_kill_in_flight_request(self):
        backend = FakeBackend()
        backend.gate = threading.Event()
        app = ZapretApp(backend)
        try:
            async with app.run_test(size=(100,32)) as pilot:
                await self.idle(app)
                await pilot.click('#service-action')
                for _ in range(100):
                    if backend.requests:
                        break
                    await asyncio.sleep(.01)
                self.assertEqual(backend.requests, [('stop', None, None)])
                app.mutate('restart')
                app.action_quit()
                self.assertTrue(app.closing)
                self.assertIsNotNone(app.pending)
                self.assertEqual(len(backend.requests), 1)
                backend.gate.set()
                await self.idle(app)
        finally:
            backend.gate.set()
        self.assertEqual(backend.requests, [('stop', None, None)])

    async def test_diagnostics_journal_plain_text_and_no_mutations(self):
        backend = FakeBackend()
        app = ZapretApp(backend)
        async with app.run_test(size=(100,32)) as pilot:
            await self.idle(app)
            app.query_one(TabbedContent).active = 'diagnostics'
            await pilot.pause()
            await pilot.click('#diagnose')
            await self.idle(app)
            self.assertIn('VPN', app.query_one('#diagnostic-report', TextArea).text)
            app.query_one(TabbedContent).active = 'journal'
            await pilot.pause()
            await pilot.click('#journal-refresh')
            await self.idle(app)
            self.assertIn('[red]literal', app.query_one('#journal-report', TextArea).text)
            self.assertEqual(backend.requests, [])

    async def test_read_error_disables_files_but_service_actions_remain_explicit(self):
        backend = FakeBackend()
        app = ZapretApp(backend)
        async with app.run_test(size=(100,32)) as pilot:
            await self.idle(app)
            backend.read_error = 'unavailable'
            app.action_refresh()
            await self.idle(app)
            self.assertTrue(app.query_one('#profile-save', Button).disabled)
            self.assertEqual(str(app.query_one('#service-action', Button).label), 'Запустить')
            await pilot.click('#service-action')
            await self.idle(app)
            self.assertEqual(backend.requests[0], ('start', None, None))
            backend.read_error = None
            app.action_refresh()
            await self.idle(app)
            self.assertFalse(app.query_one('#profile-save', Button).disabled)
            self.assertEqual(app.last_event, 'Настройки прочитаны.')

    async def test_sudo_handoff_restores_terminal_on_ui_thread(self):
        backend = FakeBackend()
        backend.requires_terminal = True
        calls = []
        main_thread = threading.get_ident()
        original = backend.request
        def request(*args):
            calls.append(('request', threading.get_ident()))
            return original(*args)
        backend.request = request
        @contextmanager
        def suspend():
            calls.append(('enter', threading.get_ident()))
            try:
                yield
            finally:
                calls.append(('exit', threading.get_ident()))
        app = ZapretApp(backend)
        async with app.run_test() as pilot:
            await self.idle(app)
            with patch.object(app, 'suspend', side_effect=suspend):
                app.mutate('stop')
                await self.idle(app)
            self.assertEqual([x[0] for x in calls], ['enter', 'request', 'exit'])
            self.assertEqual(calls[0][1], main_thread)
            self.assertEqual(calls[2][1], main_thread)
            self.assertNotEqual(calls[1][1], main_thread)

    @unittest.skipUnless(importlib.util.find_spec('PySide6'), 'GUI extra не установлен')
    async def test_real_gui_and_tui_share_cas_and_lock(self):
        from test_gui import qgui_app
        from PySide6.QtCore import QCoreApplication
        from zapret_console.gui.bridge import BackendBridge
        from zapret_console import client
        qgui_app()
        with tempfile.TemporaryDirectory() as directory:
            ctx = core.BackendContext(Path(directory) / 'backend', Path(directory) / 'state')
            (ctx.root / 'zapret-latest').mkdir(parents=True)
            (ctx.root / 'zapret-latest' / 'general_alt11.bat').touch()
            core.write_config(ctx, CONFIG)
            results = []
            class SharedBackend:
                requires_terminal = False
                def snapshot(self):
                    return core.snapshot(ctx)
                def strategies(self):
                    return core.strategies(ctx)
                def request(self, action, value, revision):
                    result = cli.request_endpoint(json.dumps(client.make_request(action, value, revision)), context=ctx)[0]
                    results.append(result)
                    return result
            # Only trust/root identity/systemctl are simulated. Files, endpoint,
            # SHA-256 CAS, atomic writes and flock are the actual implementation.
            with patch.object(core, 'trusted'), patch.object(core.os, 'geteuid', return_value=0), \
                 patch.object(core, 'command', return_value=subprocess.CompletedProcess([], 3, 'inactive', '')):
                backend = SharedBackend()
                gui = BackendBridge(backend=backend, quit_callback=lambda: None)
                app = ZapretApp(backend)
                try:
                    gui.refresh()
                    async with app.run_test(size=(100,32)) as pilot:
                        await self.idle(app)
                        for _ in range(300):
                            QCoreApplication.processEvents()
                            if gui.revision:
                                break
                            await asyncio.sleep(.01)
                        initial = app.snapshot['revision']
                        self.assertEqual(gui.revision, initial)
                        gui.saveProfile('from-gui', initial)
                        for _ in range(300):
                            QCoreApplication.processEvents()
                            if results and not gui.busy:
                                break
                            await asyncio.sleep(.01)
                        self.assertEqual(results[0]['code'], 'ok')
                        app.mutate('profile-save', 'from-tui', initial)
                        await self.idle(app)
                        self.assertEqual(results[-1]['code'], 'conflict')
                        self.assertTrue((ctx.state / 'profiles' / 'from-gui.json').is_file())
                        self.assertFalse((ctx.state / 'profiles' / 'from-tui.json').exists())
                        self.assertIn('другом окне', app.last_event)
                        with ctx.lock.open('a') as lock:
                            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                            app.mutate('profile-save', 'locked', app.snapshot['revision'])
                            await self.idle(app)
                        self.assertEqual(results[-1]['code'], 'busy')
                        self.assertFalse((ctx.state / 'profiles' / 'locked.json').exists())
                        self.assertEqual(len(results), 3)  # No retries by either UI.
                finally:
                    gui.stop()
