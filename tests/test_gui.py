"""GUI tests: bridge logic, QML loading, CLI guards and package data.

PySide6-dependent tests are skipped when the gui extra is not installed;
they must be executed in the development venv (pip install ".[gui]").
"""
import json
import shutil
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QT_QUICK_BACKEND', 'software')

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from zapret_console import core  # noqa: E402

try:
    from PySide6.QtCore import QCoreApplication, QMetaObject, QObject, QUrl, Qt, QtMsgType, qInstallMessageHandler
    from PySide6.QtQuick import QQuickItem, QQuickWindow
    from PySide6.QtTest import QTest
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine, QQmlExpression
    HAVE_PYSIDE = True
except ImportError:
    HAVE_PYSIDE = False

if HAVE_PYSIDE:
    from zapret_console.gui.bridge import BackendBridge

    _APP = None

    def qgui_app():
        global _APP
        if _APP is None:
            _APP = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
        return _APP

    def wait_until(condition, timeout_ms=8000):
        deadline = time.monotonic() + timeout_ms / 1000
        while time.monotonic() < deadline:
            QCoreApplication.processEvents()
            if condition():
                return True
            time.sleep(0.01)
        return bool(condition())

    CONFIG = {'interface': 'any', 'gamefiltertcp': 'true', 'gamefilterudp': 'false',
              'strategy': 'general_alt11.bat', 'firewall_backend': 'nftables'}
    PROFILE_CONFIG = dict(CONFIG, strategy='general_alt10.bat')
    SAMPLE = {'root': '/tmp/demo', 'unit': 'zapret.service', 'revision': 'a' * 64,
              'revision_error': None, 'config': dict(CONFIG), 'config_error': None,
              'service_state': 'active', 'autostart': 'enabled',
              'profiles': [{'name': 'home', 'config': PROFILE_CONFIG, 'error': None},
                           {'name': 'broken', 'config': None,
                            'error': 'Профиль повреждён: broken.json не содержит конфигурацию из пяти полей'}],
              'profiles_error': None}


class FakeBackend:
    def __init__(self):
        self.snapshots = [dict(SAMPLE)]
        self.strategy_names = ['general_alt11.bat', 'general_alt10.bat', 'custom_tor.bat']
        self.requests = []
        self.request_results = []
        self.snapshot_error = None
        self.snapshot_gate = None
        self.request_gate = None
        self.inspection_gate = None
        self.inspection_calls = []
        self.inspection_error = None

    def snapshot(self):
        if self.snapshot_gate is not None:
            self.snapshot_gate.wait(timeout=15)
        if self.snapshot_error:
            raise RuntimeError(self.snapshot_error)
        if len(self.snapshots) > 1:
            return self.snapshots.pop(0)
        return self.snapshots[0]

    def strategies(self):
        return list(self.strategy_names)

    def diagnose(self, privileged=False, progress=None):
        self.inspection_calls.append(('diagnostic', privileged, threading.get_ident()))
        if progress:
            progress('Проверяем сеть…')
        if self.inspection_gate is not None:
            self.inspection_gate.wait(timeout=15)
        if self.inspection_error:
            raise self.inspection_error
        return {'report': 'Сервис: запущен\nПравила firewall: не удалось проверить\nПроверка через VPN не подтверждает zapret.',
                'network_ok': True, 'route_interface': 'tun0', 'configured_interface': 'eth0'}

    def journal(self):
        self.inspection_calls.append(('journal', False, threading.get_ident()))
        if self.inspection_gate is not None:
            self.inspection_gate.wait(timeout=15)
        if self.inspection_error:
            raise self.inspection_error
        return {'ok': True, 'text': '<b>literal log entry</b>\nservice started', 'warning': 'Некоторые сообщения недоступны'}

    def request(self, action, value=None, expected_revision=None):
        # запрос фиксируется как отправленный до блокировки на gate:
        # «в полёте» он уже считается отправленным
        self.requests.append({'action': action, 'value': value, 'revision': expected_revision})
        if self.request_gate is not None:
            self.request_gate.wait(timeout=15)
        if self.request_results:
            return self.request_results.pop(0)
        return {'protocol': 1, 'ok': True, 'code': 'ok', 'message': '', 'data': None}


@unittest.skipUnless(HAVE_PYSIDE, 'PySide6 не установлен: pip install ".[gui]"')
class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.app = qgui_app()
        self.backend = FakeBackend()
        self.quit_calls = []
        self.bridge = BackendBridge(backend=self.backend,
                                    quit_callback=lambda: self.quit_calls.append(1))
        self.messages = []
        self.bridge.messageRaised.connect(lambda title, text: self.messages.append((title, text)))

    def tearDown(self):
        self.bridge.stop()

    def wait_idle(self):
        self.assertTrue(wait_until(lambda: not self.bridge.busy))

    def test_refresh_applies_real_snapshot_and_strategies(self):
        self.assertTrue(self.bridge.loading)
        self.bridge.refresh()
        self.assertTrue(wait_until(lambda: self.bridge.serviceText == 'Сервис работает'))
        self.assertFalse(self.bridge.loading)
        self.assertEqual(self.bridge.eventTone, 'accent')
        self.assertEqual(self.bridge.serviceTone, 'ok')
        self.assertTrue(self.bridge.serviceRunning)
        self.assertEqual(self.bridge.autostartText, 'Включён')
        self.assertEqual(self.bridge.interfaceName, 'any')
        self.assertEqual(self.bridge.strategy, 'general_alt11.bat')
        self.assertTrue(self.bridge.strategyInstalled)
        self.assertTrue(self.bridge.canMutateFiles)
        self.assertEqual(self.bridge.revision, 'a' * 64)
        self.assertEqual(self.bridge.profiles.rowCount(), 2)
        self.assertEqual(self.bridge.strategies.rowCount(), 3)

    def test_strategy_not_installed_is_reported(self):
        self.backend.strategy_names = ['general.bat']
        self.bridge.refresh()
        self.assertTrue(wait_until(lambda: not self.bridge.loading))
        self.assertFalse(self.bridge.strategyInstalled)
        self.assertEqual(self.bridge.strategy, 'general_alt11.bat')

    def test_operation_event_survives_poll_and_post_operation_refresh(self):
        self.bridge.refresh()
        self.assertTrue(wait_until(lambda: self.bridge.canMutateFiles))
        for code, tone in [('ok', 'ok'), ('conflict', 'warn'),
                           ('auth_cancelled', 'muted'), ('operation_failed', 'error')]:
            with self.subTest(code=code):
                self.backend.request_results = [{'ok': code == 'ok', 'code': code, 'message': 'failed'}]
                before = len(self.backend.requests)
                self.bridge.stopService()
                self.assertTrue(wait_until(lambda: not self.bridge.busy and not self.bridge._snapshot_pending))
                event = self.bridge.lastEvent
                self.assertEqual(self.bridge.eventTone, tone)
                self.bridge.refresh()
                self.assertTrue(wait_until(lambda: not self.bridge._snapshot_pending))
                self.assertEqual(self.bridge.lastEvent, event)
                self.assertEqual(self.bridge.eventTone, tone)
                self.assertEqual(len(self.backend.requests), before + 1)
        self.bridge.refreshManual()
        self.assertTrue(wait_until(lambda: not self.bridge._snapshot_pending))
        self.assertEqual(self.bridge.lastEvent, 'Настройки прочитаны.')
        self.backend.snapshot_error = 'read failure'
        self.bridge.refresh()
        self.assertTrue(wait_until(lambda: not self.bridge._snapshot_pending))
        self.assertEqual(self.bridge.eventTone, 'error')
        self.assertIn('read failure', self.bridge.lastEvent)

    def test_inspection_runs_in_worker_and_prevents_duplicate_or_mutating_jobs(self):
        gate = threading.Event()
        self.backend.inspection_gate = gate
        try:
            self.bridge.runDiagnostics(False)
            self.assertTrue(wait_until(lambda: len(self.backend.inspection_calls) == 1))
            self.assertTrue(self.bridge.busy)
            self.assertNotEqual(self.backend.inspection_calls[0][2], threading.get_ident())
            self.bridge.runDiagnostics(True)
            self.bridge.refreshJournal()
            self.bridge.stopService()
            self.assertEqual(len(self.backend.inspection_calls), 1)
            self.assertEqual(self.backend.requests, [])
        finally:
            gate.set()
        self.assertTrue(wait_until(lambda: not self.bridge.busy))
        self.assertIn('VPN', self.bridge.diagnosticReport)
        self.assertEqual(self.bridge.diagnosticTone, 'warn')

    def test_close_during_inspection_waits_without_service_changes(self):
        gate = threading.Event()
        self.backend.inspection_gate = gate
        try:
            self.bridge.refreshJournal()
            self.assertTrue(wait_until(lambda: len(self.backend.inspection_calls) == 1))
            before = time.monotonic()
            self.bridge.requestClose()
            self.assertLess(time.monotonic() - before, 1)
            self.bridge.runDiagnostics(False)
            self.assertEqual(len(self.backend.inspection_calls), 1)
            self.assertEqual(self.quit_calls, [])
        finally:
            gate.set()
        self.assertTrue(wait_until(lambda: self.quit_calls == [1]))
        self.assertFalse(self.bridge._worker.isRunning())
        self.assertEqual(self.backend.requests, [])

    def test_cancelled_diagnostic_auth_is_neutral_and_preserves_last_report(self):
        from zapret_console.client import ReadOperationError
        self.bridge.runDiagnostics(False)
        self.assertTrue(wait_until(lambda: not self.bridge.busy))
        previous = self.bridge.diagnosticReport
        self.backend.inspection_error = ReadOperationError('auth_cancelled', 'Авторизация отменена')
        self.bridge.runDiagnostics(True)
        self.assertTrue(wait_until(lambda: not self.bridge.busy))
        self.assertEqual(self.bridge.diagnosticReport, previous)
        self.assertEqual(self.bridge.diagnosticTone, 'muted')
        self.assertIn('отменена', self.bridge.diagnosticStatus)
        self.assertEqual(self.backend.requests, [])

    def test_service_state_unknown_and_files_disabled_on_read_error(self):
        self.backend.snapshot_error = 'нет доступа'
        self.bridge.refresh()
        # 'Неизвестно' совпадает с начальным состоянием, ждём признак завершения чтения
        self.assertTrue(wait_until(lambda: self.bridge.lastEvent.startswith('Состояние недоступно')))
        self.assertIn('нет доступа', self.bridge.lastEvent)
        self.assertEqual(self.bridge.serviceText, 'Состояние неизвестно')
        self.assertEqual(self.bridge.serviceTone, 'warn')
        self.assertFalse(self.bridge.canMutateFiles)
        self.assertEqual(self.bridge.revision, '')
        self.assertTrue(self.messages)
        self.assertIn('нет доступа', self.messages[0][1])

    def test_revision_none_disables_file_operations(self):
        broken = dict(SAMPLE, revision=None,
                      revision_error='Состояние прочитано не полностью: не удалось прочитать known-good.json')
        self.backend.snapshots = [broken]
        self.bridge.refresh()
        self.assertTrue(wait_until(lambda: self.bridge.revisionError != ''))
        self.assertFalse(self.bridge.canMutateFiles)
        self.assertIn('known-good.json', self.bridge.revisionError)

    def test_generation_guard_drops_stale_reply(self):
        self.bridge.refresh()
        self.assertTrue(wait_until(lambda: self.bridge.serviceText == 'Сервис работает'))
        self.bridge._snapshot_generation = 7  # newer generation in flight
        stale = dict(SAMPLE, service_state='failed', revision='e' * 64)
        self.bridge._on_snapshot_ready(1, stale, [])
        self.assertEqual(self.bridge.serviceText, 'Сервис работает')
        self.assertEqual(self.bridge.revision, 'a' * 64)

    def test_two_clients_conflict_shown_and_not_retried(self):
        self.bridge.refresh()
        self.assertTrue(wait_until(lambda: self.bridge.canMutateFiles))
        self.backend.request_results = [{'protocol': 1, 'ok': False, 'code': 'conflict',
                                         'message': '', 'data': None}]
        self.bridge.deleteProfile('home', 'a' * 64)
        self.wait_idle()
        self.assertEqual(len(self.backend.requests), 1)
        self.assertEqual(self.backend.requests[0],
                         {'action': 'profile-delete', 'value': 'home', 'revision': 'a' * 64})
        self.assertTrue(any(title == 'Настройки изменились' for title, _ in self.messages))
        # refresh после результата выполняется, но повторного запроса нет
        self.assertTrue(wait_until(lambda: not self.bridge.busy))
        time.sleep(0.05)
        QCoreApplication.processEvents()
        self.assertEqual(len(self.backend.requests), 1)

    def test_confirmation_uses_shown_revision_not_fresh(self):
        self.bridge.refresh()
        self.assertTrue(wait_until(lambda: self.bridge.canMutateFiles))
        # состояние изменится вне окна; в диалоге осталась старая revision
        self.backend.snapshots = [dict(SAMPLE, revision='c' * 64)]
        self.backend.request_results = [{'protocol': 1, 'ok': True, 'code': 'ok', 'message': '', 'data': None}]
        self.bridge.deleteProfile('home', 'a' * 64)
        self.wait_idle()
        self.assertEqual(self.backend.requests[0]['revision'], 'a' * 64)

    def test_service_actions_are_explicit_without_revision(self):
        for slot, action in [(self.bridge.startService, 'start'),
                             (self.bridge.stopService, 'stop'),
                             (self.bridge.restartService, 'restart'),
                             (self.bridge.enableAutostart, 'enable'),
                             (self.bridge.disableAutostart, 'disable')]:
            slot()
            self.wait_idle()
        self.assertEqual([r['action'] for r in self.backend.requests],
                         ['start', 'stop', 'restart', 'enable', 'disable'])
        self.assertTrue(all(r['revision'] is None for r in self.backend.requests))

    def test_busy_blocks_second_operation(self):
        self.bridge.refresh()
        self.assertTrue(wait_until(lambda: self.bridge.canMutateFiles))
        gate = threading.Event()
        self.backend.request_gate = gate
        self.assertTrue(self.bridge._run_operation('stop', 'т', 'stop', None, None))
        self.assertFalse(self.bridge._run_operation('start', 'т', 'start', None, None))
        gate.set()
        self.wait_idle()
        self.assertEqual(len(self.backend.requests), 1)

    def test_file_profile_operations_pass_names_and_revisions(self):
        self.bridge.refresh()
        self.assertTrue(wait_until(lambda: self.bridge.canMutateFiles))
        self.bridge.saveProfile('mobile', 'a' * 64)
        self.wait_idle()
        self.bridge.restoreProfile('home', 'a' * 64)
        self.wait_idle()
        self.bridge.replaceProfile('home', 'a' * 64)
        self.wait_idle()
        self.bridge.deleteProfile('broken', 'a' * 64)
        self.wait_idle()
        self.assertEqual([r['action'] for r in self.backend.requests],
                         ['profile-save', 'profile-restore', 'profile-replace', 'profile-delete'])
        self.assertEqual([r['value'] for r in self.backend.requests],
                         ['mobile', 'home', 'home', 'broken'])
        self.assertTrue(all(r['revision'] == 'a' * 64 for r in self.backend.requests))

    def test_strategy_filter_and_apply_use_shown_revision(self):
        self.bridge.refresh()
        self.assertTrue(wait_until(lambda: self.bridge.canMutateFiles))
        self.bridge.setStrategyFilter('alt10')
        self.assertEqual(self.bridge.strategies.rowCount(), 1)
        self.bridge.setStrategyFilter('')
        self.assertEqual(self.bridge.strategies.rowCount(), 3)
        self.bridge.applyStrategy('general_alt10.bat', 'a' * 64)
        self.wait_idle()
        self.assertEqual(self.backend.requests[-1],
                         {'action': 'strategy', 'value': 'general_alt10.bat', 'revision': 'a' * 64})

    def test_close_when_idle_quits_after_worker_finished(self):
        self.assertFalse(self.bridge.requestClose())
        self.assertTrue(wait_until(lambda: self.quit_calls == [1]))
        self.assertFalse(self.bridge._worker.isRunning())
        # повторный запрос во время закрытия не добавляет работу и не дублирует quit
        self.bridge.requestClose()
        QCoreApplication.processEvents()
        self.assertEqual(self.quit_calls, [1])

    def test_close_during_mutation_waits_for_worker_without_blocking(self):
        self.bridge.refresh()
        self.assertTrue(wait_until(lambda: self.bridge.canMutateFiles))
        gate = threading.Event()
        self.backend.request_gate = gate
        self.backend.request_results = [{'protocol': 1, 'ok': True, 'code': 'ok', 'message': '', 'data': None}]
        try:
            self.assertTrue(self.bridge._run_operation('stop', 'т', 'stop', None, None))
            # задаёмся моментом, когда запрос реально отправлен (записан), до requestClose
            self.assertTrue(wait_until(lambda: len(self.backend.requests) == 1))
            deadline = time.monotonic() + 2.0
            self.assertFalse(self.bridge.requestClose())
            self.assertLess(time.monotonic(), deadline, 'requestClose заблокировал GUI-поток')
            self.assertTrue(self.bridge.closing)
            self.assertFalse(self.bridge._timer.isActive())
            self.assertEqual(self.quit_calls, [])
            self.assertEqual(len(self.backend.requests), 1)  # запрос «в полёте», повторов нет
            # новые операции и refresh во время закрытия отклоняются
            self.assertFalse(self.bridge._run_operation('start', 'т', 'start', None, None))
            self.bridge.refresh()
            self.assertFalse(self.bridge._snapshot_pending)
        finally:
            gate.set()
        self.assertTrue(wait_until(lambda: self.quit_calls == [1]))
        self.assertFalse(self.bridge._worker.isRunning())
        self.assertEqual([r['action'] for r in self.backend.requests], ['stop'])

    def test_close_during_snapshot_read_waits_and_applies_result(self):
        gate = threading.Event()
        self.backend.snapshot_gate = gate
        try:
            self.bridge.refresh()
            self.assertFalse(self.bridge.requestClose())
            self.assertEqual(self.quit_calls, [])
        finally:
            gate.set()
        self.assertTrue(wait_until(lambda: self.quit_calls == [1]))
        self.assertEqual(self.bridge.serviceText, 'Сервис работает')
        self.assertFalse(self.bridge._worker.isRunning())

    def test_operation_failure_shown_via_message(self):
        self.bridge.refresh()
        self.assertTrue(wait_until(lambda: self.bridge.canMutateFiles))
        self.backend.request_results = [{'protocol': 1, 'ok': False, 'code': 'operation_failed',
                                         'message': 'Стратегия отсутствует', 'data': None}]
        self.bridge.applyStrategy('missing.bat', 'a' * 64)
        self.wait_idle()
        self.assertTrue(any('Стратегия отсутствует' in text for _, text in self.messages))

    def test_save_profile_name_validated_before_launcher(self):
        self.bridge.refresh()
        self.assertTrue(wait_until(lambda: self.bridge.canMutateFiles))
        for bad in ('', 'bad name', 'bad.name', 'профиль', 'a' * 49):
            self.bridge.saveProfile(bad, 'a' * 64)
            QCoreApplication.processEvents()
            self.assertEqual(self.backend.requests, [], repr(bad))
        self.assertTrue(self.messages)
        self.assertIn('имя', self.messages[-1][0].lower())
        self.bridge.saveProfile('mobile', 'a' * 64)
        self.wait_idle()
        self.assertEqual(self.backend.requests[-1]['value'], 'mobile')


@unittest.skipUnless(HAVE_PYSIDE, 'PySide6 не установлен: pip install ".[gui]"')
class QmlLoadTests(unittest.TestCase):
    def test_main_qml_loads_without_warnings(self):
        qgui_app()
        warnings = []
        engine = QQmlApplicationEngine()
        engine.warnings.connect(warnings.extend)
        bridge = BackendBridge(backend=FakeBackend(), quit_callback=lambda: None)
        engine.rootContext().setContextProperty('bridge', bridge)
        qml_main = Path(core.__file__).resolve().parent / 'gui' / 'qml' / 'Main.qml'
        try:
            engine.load(QUrl.fromLocalFile(str(qml_main)))
            self.assertTrue(engine.rootObjects(), 'QML не загрузился')
            self.assertEqual(warnings, [], 'предупреждения QML: ' + '\n'.join(
                w.toString() for w in warnings))
        finally:
            # мост останавливается до уничтожения QML: bindings не должны видеть null;
            # deleteLate вне цикла событий не работает — уничтожаем синхронно
            bridge.stop()
            del engine
            QCoreApplication.processEvents()


@unittest.skipUnless(HAVE_PYSIDE, 'PySide6 не установлен: pip install ".[gui]"')
class QmlWindowTests(unittest.TestCase):
    """Настоящее QML-окно: wiring закрытия, диалоги и пустое состояние."""

    def setUp(self):
        self.app = qgui_app()
        self.backend = FakeBackend()
        self.quit_calls = []
        self.warnings = []
        self.qt_warnings = []
        def capture_qt(kind, context, message):
            if kind in (QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg):
                self.qt_warnings.append(message)
            if self.previous_qt_handler is not None:
                self.previous_qt_handler(kind, context, message)
            else:
                print(message, file=sys.stderr)
        self.previous_qt_handler = qInstallMessageHandler(capture_qt)
        self.engine = QQmlApplicationEngine()
        self.engine.warnings.connect(self.warnings.extend)
        self.bridge = BackendBridge(backend=self.backend,
                                    quit_callback=lambda: self.quit_calls.append(1))
        self.engine.rootContext().setContextProperty('bridge', self.bridge)
        qml_main = Path(core.__file__).resolve().parent / 'gui' / 'qml' / 'Main.qml'
        self.engine.load(QUrl.fromLocalFile(str(qml_main)))
        self.assertTrue(self.engine.rootObjects(), 'QML не загрузился')
        self.window = self.engine.rootObjects()[0]

    def tearDown(self):
        self.bridge.stop()
        del self.engine
        QCoreApplication.processEvents()
        qInstallMessageHandler(self.previous_qt_handler)
        self.assertEqual(self.qt_warnings, [], "Qt warnings: " + "\n".join(self.qt_warnings))

    def find(self, object_name):
        return self.window.findChild(QObject, object_name)

    def wait_idle(self):
        self.assertTrue(wait_until(lambda: not self.bridge.busy))

    def prop(self, object_name, name):
        return self.find(object_name).property(name)

    def click(self, object_name):
        QMetaObject.invokeMethod(self.find(object_name), 'click')

    def assert_no_qml_warnings(self):
        self.assertEqual(self.warnings, [], 'предупреждения QML: ' + '\n'.join(
            w.toString() for w in self.warnings))

    def test_window_close_during_slow_mutation_waits_without_errors(self):
        self.bridge.refresh()
        self.assertTrue(wait_until(lambda: self.bridge.canMutateFiles))
        gate = threading.Event()
        self.backend.request_gate = gate
        self.backend.request_results = [{'protocol': 1, 'ok': True, 'code': 'ok', 'message': '', 'data': None}]
        self.bridge.stopService()
        self.assertTrue(wait_until(lambda: self.bridge.busy))
        self.window.close()  # настоящий путь onClosing → bridge.requestClose
        for _ in range(20):
            QCoreApplication.processEvents()
            time.sleep(0.01)
        self.assert_no_qml_warnings()
        self.assertTrue(self.window.isVisible(), 'окно закрылось во время операции')
        self.assertTrue(self.bridge.closing)
        self.assertEqual(len(self.backend.requests), 1)  # запрос «в полёте», повторов нет
        self.assertEqual([r['action'] for r in self.backend.requests], ['stop'])
        try:
            self.assertEqual(self.quit_calls, [])
        finally:
            gate.set()
        self.assertTrue(wait_until(lambda: self.quit_calls == [1]))
        self.assertFalse(self.bridge._worker.isRunning())
        self.assertEqual(len(self.backend.requests), 1)
        self.assert_no_qml_warnings()

    def test_idle_close_via_window_close_quits_after_worker_finished(self):
        self.bridge.refresh()
        self.assertTrue(wait_until(lambda: self.bridge.canMutateFiles))
        self.window.close()
        self.assertTrue(wait_until(lambda: self.quit_calls == [1]))
        self.assertFalse(self.bridge._worker.isRunning())
        self.assert_no_qml_warnings()
        self.window.close()
        QCoreApplication.processEvents()
        self.assertEqual(self.quit_calls, [1])

    def test_profiles_count_transitions_drive_empty_state(self):
        label = self.find('profilesEmptyLabel')
        nav = self.find('navProfiles')
        self.assertIsNotNone(label)
        self.assertIsNotNone(nav)
        self.bridge.refresh()
        self.assertTrue(wait_until(lambda: self.bridge.canMutateFiles))
        self.assertEqual(self.bridge.profilesModel.count, 2)
        QMetaObject.invokeMethod(nav, 'click')
        self.assertTrue(wait_until(lambda: label.property('visible') is False))
        self.backend.snapshots = [dict(SAMPLE, profiles=[])]
        self.bridge.refresh()
        self.assertTrue(wait_until(lambda: label.property('visible') is True))
        self.backend.snapshots = [dict(SAMPLE)]
        self.bridge.refresh()
        self.assertTrue(wait_until(lambda: label.property('visible') is False))
        self.assertEqual(self.bridge.profilesModel.count, 2)
        self.assert_no_qml_warnings()

    def test_save_dialog_blocks_empty_and_invalid_names(self):
        self.bridge.refresh()
        self.assertTrue(wait_until(lambda: self.bridge.canMutateFiles))
        dialog = self.find('saveDialog')
        field = self.find('saveNameField')
        accept = self.find('saveAcceptButton')
        self.assertIsNotNone(dialog)
        dialog.setProperty('baseRevision', self.bridge.revision)
        QMetaObject.invokeMethod(dialog, 'open')
        self.assertTrue(wait_until(lambda: dialog.property('visible')))
        self.assertFalse(accept.property('enabled'))  # пустое имя
        QMetaObject.invokeMethod(accept, 'click')
        QCoreApplication.processEvents()
        self.assertEqual(self.backend.requests, [])
        field.setProperty('text', 'bad name')
        QCoreApplication.processEvents()
        self.assertFalse(accept.property('enabled'))  # невалидное имя
        QMetaObject.invokeMethod(accept, 'click')
        QCoreApplication.processEvents()
        self.assertEqual(self.backend.requests, [])
        field.setProperty('text', 'mobile')
        self.assertTrue(wait_until(lambda: accept.property('enabled')))
        QMetaObject.invokeMethod(accept, 'click')
        self.wait_idle()
        self.assertEqual(self.backend.requests,
                         [{'action': 'profile-save', 'value': 'mobile', 'revision': 'a' * 64}])
        self.assert_no_qml_warnings()

    def test_select_strategy_button_switches_tab_without_mutation(self):
        select = self.find('selectStrategyButton')
        nav = self.find('navStrategies')
        self.assertIsNotNone(select)
        self.assertIsNotNone(nav)
        self.assertFalse(nav.property('checked'))
        self.assertEqual(self.backend.requests, [])
        QMetaObject.invokeMethod(select, 'click')
        QCoreApplication.processEvents()
        self.assertTrue(nav.property('checked'))
        self.assertEqual(self.backend.requests, [])  # переход вкладки без мутации

    def test_search_does_not_hide_current_strategy_card(self):
        self.bridge.refresh()
        self.assertTrue(wait_until(lambda: self.bridge.canMutateFiles))
        card = self.find('currentStrategyCard')
        nav = self.find('navStrategies')
        QMetaObject.invokeMethod(nav, 'click')
        self.assertTrue(wait_until(lambda: card.property('visible')))
        self.bridge.setStrategyFilter('нет-такой-стратегии')
        self.assertTrue(wait_until(lambda: self.bridge.strategiesModel.count == 0))
        self.assertTrue(card.property('visible'))  # фильтр не прячет карточку текущей стратегии
        self.assertEqual(self.bridge.strategy, 'general_alt11.bat')

    def test_narrow_window_uses_narrow_sidebar(self):
        sidebar = self.find('sidebar')
        self.assertIsNotNone(sidebar)
        self.assertEqual(sidebar.property('width'), 208)
        self.window.setProperty('width', 800)
        self.assertTrue(wait_until(lambda: sidebar.property('width') == 184))
        self.assertEqual(self.window.property('minimumWidth'), 800)
        self.window.setProperty('width', 1040)
        self.assertTrue(wait_until(lambda: sidebar.property('width') == 208))
        self.assert_no_qml_warnings()

    def test_inspection_pages_use_real_buttons_without_privilege_by_default(self):
        self.click('navDiagnostics')
        self.assertEqual(self.backend.inspection_calls, [])
        self.assertFalse(self.prop('diagnosticElevate', 'checked'))
        self.click('runDiagnosticsButton')
        self.assertTrue(wait_until(lambda: not self.bridge.busy))
        self.assertEqual(self.backend.inspection_calls[0][:2], ('diagnostic', False))
        self.assertIn('VPN', self.prop('diagnosticReportArea', 'text'))
        self.click('navJournal')
        self.click('refreshJournalButton')
        self.assertTrue(wait_until(lambda: not self.bridge.busy))
        self.assertEqual(self.backend.inspection_calls[-1][:2], ('journal', False))
        self.assertIn('<b>literal log entry</b>', self.prop('journalArea', 'text'))
        value, undefined = QQmlExpression(self.engine.rootContext(), self.find('journalArea'),
                                           'textFormat === 0').evaluate()
        self.assertFalse(undefined)
        self.assertTrue(value)  # PlainText, journal content cannot supply markup
        self.click('copyJournalButton')
        self.assertIn('literal log entry', self.app.clipboard().text())
        self.assertIn('недоступны', self.app.clipboard().text())
        self.assertEqual(self.backend.requests, [])
        self.window.setProperty('width', 800)
        self.window.setProperty('height', 560)
        QCoreApplication.processEvents()
        self.assertGreater(self.prop('journalArea', 'width'), 400)
        self.assert_no_qml_warnings()

    def visual_items(self):
        def walk(item):
            yield item
            for child in item.childItems():
                yield from walk(child)
        return list(walk(self.window.contentItem()))

    def test_file_buttons_disabled_with_incomplete_snapshot(self):
        self.bridge.refresh()
        self.assertTrue(wait_until(lambda: self.bridge.canMutateFiles))
        self.click('navProfiles')
        self.bridge._on_snapshot_ready(self.bridge._snapshot_generation,
                                      dict(SAMPLE, revision=None, revision_error='incomplete'),
                                      self.backend.strategy_names)
        QCoreApplication.processEvents()
        targets = {'saveCurrentButton', 'restoreProfileButton', 'replaceProfileButton', 'deleteProfileButton'}
        buttons = [item for item in self.visual_items() if item.objectName() in targets]
        self.assertEqual({item.objectName() for item in buttons}, targets)
        for item in buttons:
            self.assertFalse(item.property('enabled'), item.objectName())
            QMetaObject.invokeMethod(item, 'click')
        self.assertFalse(self.prop('saveDialog', 'visible'))
        self.assertFalse(self.prop('replaceDialog', 'visible'))
        self.assertFalse(self.prop('deleteDialog', 'visible'))
        self.assertEqual(self.backend.requests, [])
        self.assertTrue(self.prop('serviceActionButton', 'enabled'))

    def test_open_confirmation_disabled_when_revision_becomes_unavailable(self):
        self.bridge.refresh()
        self.assertTrue(wait_until(lambda: self.bridge.canMutateFiles))
        for dialog_name, accept_name in [('replaceDialog', 'replaceAcceptButton'),
                                         ('deleteDialog', 'deleteAcceptButton')]:
            dialog = self.find(dialog_name)
            dialog.setProperty('baseRevision', 'a' * 64)
            dialog.setProperty('targetName', 'home')
            QMetaObject.invokeMethod(dialog, 'open')
            self.bridge._shown_revision = None
            self.bridge.revisionChanged.emit()
            QCoreApplication.processEvents()
            self.assertFalse(self.prop(accept_name, 'enabled'))
            self.click(accept_name)
            self.assertEqual(self.prop(dialog_name, 'baseRevision'), 'a' * 64)
            self.assertEqual(self.backend.requests, [])
            QMetaObject.invokeMethod(dialog, 'reject')
            self.bridge._shown_revision = 'a' * 64
            self.bridge.revisionChanged.emit()

    def test_mutations_disabled_while_busy_and_closing_but_navigation_works(self):
        self.bridge.refresh()
        self.assertTrue(wait_until(lambda: self.bridge.canMutateFiles))
        self.bridge._busy = True
        self.bridge.busyChanged.emit()
        QCoreApplication.processEvents()
        for name in ['serviceActionButton', 'restartButton', 'autostartButton', 'saveCurrentButton']:
            self.assertFalse(self.prop(name, 'enabled'), name)
        self.click('navStrategies')
        self.assertTrue(self.prop('navStrategies', 'checked'))
        targets = {'restoreProfileButton', 'restoreProfileCompactButton', 'replaceProfileButton',
                   'deleteProfileButton', 'applyStrategyButton', 'saveCurrentEmptyButton'}
        for item in self.visual_items():
            if item.objectName() in targets:
                self.assertFalse(item.property('enabled'), item.objectName())
                QMetaObject.invokeMethod(item, 'click')
        self.bridge._busy = False
        self.bridge.busyChanged.emit()
        self.bridge.requestClose()
        for name in ['serviceActionButton', 'restartButton', 'autostartButton', 'saveCurrentButton']:
            self.assertFalse(self.prop(name, 'enabled'), name)
        self.assertEqual(self.backend.requests, [])

    def test_dialog_keyboard_cancel_focus_and_valid_submit(self):
        self.bridge.refresh()
        self.assertTrue(wait_until(lambda: self.bridge.canMutateFiles))
        self.window.requestActivate()
        self.find('navMain').forceActiveFocus(Qt.TabFocusReason)
        QTest.keyClick(self.window, Qt.Key_Tab)
        self.assertTrue(wait_until(lambda: self.prop('navProfiles', 'visualFocus')))
        QTest.keyClick(self.window, Qt.Key_Return)
        self.assertTrue(self.prop('navProfiles', 'checked'))
        save = self.find('saveDialog')
        save.setProperty('baseRevision', 'a' * 64)
        QMetaObject.invokeMethod(save, 'open')
        self.assertTrue(wait_until(lambda: self.prop('saveNameField', 'activeFocus')))
        QTest.keyClick(self.window, Qt.Key_Return)
        QCoreApplication.processEvents()
        self.assertEqual(self.backend.requests, [])
        QTest.keyClick(self.window, Qt.Key_Escape)
        self.assertTrue(wait_until(lambda: not self.prop('saveDialog', 'visible')))
        for dialog, cancel in [('replaceDialog', 'replaceCancelButton'), ('deleteDialog', 'deleteCancelButton')]:
            obj = self.find(dialog)
            obj.setProperty('targetName', 'home')
            obj.setProperty('baseRevision', 'a' * 64)
            QMetaObject.invokeMethod(obj, 'open')
            self.assertTrue(wait_until(lambda: self.prop(cancel, 'activeFocus')))
            QTest.keyClick(self.window, Qt.Key_Return)
            self.assertTrue(wait_until(lambda: not self.prop(dialog, 'visible')))
            self.assertEqual(self.backend.requests, [])
        QMetaObject.invokeMethod(save, 'open')
        self.assertTrue(wait_until(lambda: self.prop('saveNameField', 'activeFocus')))
        self.find('saveNameField').setProperty('text', 'mobile')
        QTest.keyClick(self.window, Qt.Key_Return)
        self.assertTrue(wait_until(lambda: len(self.backend.requests) == 1 and not self.bridge.busy))
        self.assertEqual(self.backend.requests[0]['revision'], 'a' * 64)
        self.assertEqual(self.backend.requests[0]['action'], 'profile-save')

    def test_button_text_fits_and_wide_cards_align(self):
        self.bridge.refresh()
        self.assertTrue(wait_until(lambda: self.bridge.canMutateFiles))
        self.click('navProfiles')
        QCoreApplication.processEvents()
        button = self.find('saveCurrentButton')
        label = button.property('contentItem')
        self.assertGreaterEqual(button.property('width') - button.property('leftPadding')
                                - button.property('rightPadding'), label.property('implicitWidth'))
        self.click('navMain')
        QCoreApplication.processEvents()
        left, right = self.find('connectionCard'), self.find('autostartCard')
        self.assertAlmostEqual(left.property('y'), right.property('y'), delta=1)
        self.assertGreater(left.property('width'), right.property('width'))
        self.assert_no_qml_warnings()

    def test_dialog_cancellations_send_nothing(self):
        self.bridge.refresh()
        self.assertTrue(wait_until(lambda: self.bridge.canMutateFiles))
        cases = [('replaceDialog', 'replaceAcceptButton', 'replaceCancelButton', 'profile-replace'),
                 ('deleteDialog', 'deleteAcceptButton', 'deleteCancelButton', 'profile-delete')]
        for dialog_name, accept_name, cancel_name, action in cases:
            before = len(self.backend.requests)
            dialog = self.find(dialog_name)
            dialog.setProperty('targetName', 'home')
            dialog.setProperty('baseRevision', self.bridge.revision)
            QMetaObject.invokeMethod(dialog, 'open')
            self.assertTrue(wait_until(lambda d=dialog: d.property('visible')), dialog_name)
            accept = self.find(accept_name)
            self.assertTrue(accept.property('enabled'))
            QMetaObject.invokeMethod(self.find(cancel_name), 'click')
            self.assertTrue(wait_until(lambda d=dialog: not d.property('visible')))
            self.assertEqual(self.backend.requests[before:], [], dialog_name)
            # подтверждение через QML уходит с базовой revision диалога
            dialog.setProperty('baseRevision', 'a' * 64)
            QMetaObject.invokeMethod(dialog, 'open')
            self.assertTrue(wait_until(lambda d=dialog: d.property('visible')))
            QMetaObject.invokeMethod(accept, 'click')
            self.wait_idle()
            self.assertEqual(self.backend.requests[before:],
                             [{'action': action, 'value': 'home', 'revision': 'a' * 64}])
        self.assert_no_qml_warnings()


ROOT = Path(__file__).resolve().parents[1]


class GuiCliTests(unittest.TestCase):
    def run_cli(self, *args, code=None):
        if code is None:
            env = dict(os.environ, PYTHONPATH=str(ROOT / 'src'), PYTHONHASHSEED='0')
            return subprocess.run([sys.executable, '-m', 'zapret_console', *args],
                                  env=env, capture_output=True, text=True, timeout=60)
        env = dict(os.environ, PYTHONHASHSEED='0')
        return subprocess.run([sys.executable, '-c', code, str(ROOT / 'src')],
                              env=env, capture_output=True, text=True, timeout=60)

    def test_gui_rejects_combined_modes(self):
        r = self.run_cli('--gui', '--status')
        self.assertEqual(r.returncode, 2)
        self.assertIn('--gui', r.stderr)

    def test_request_json_rejects_gui(self):
        r = self.run_cli('--request-json', '{}', '--gui')
        self.assertEqual(r.returncode, 1)
        result = json.loads(r.stdout)
        self.assertEqual(result['code'], 'invalid_request')

    @unittest.skipUnless(HAVE_PYSIDE, 'проверка корневого запуска требует модуль gui')
    def test_gui_refuses_root(self):
        r = self.run_cli(code=(
            'import os, sys\n'
            'sys.path.insert(0, sys.argv[1])\n'
            'os.geteuid = lambda: 0\n'
            'from zapret_console.gui.app import run_gui\n'
            'sys.exit(run_gui())\n'))
        self.assertEqual(r.returncode, 1)
        self.assertIn('root', r.stdout)

    def test_gui_without_pyside_prints_install_hint(self):
        r = self.run_cli(code=(
            'import sys\n'
            'sys.path.insert(0, sys.argv[1])\n'
            'sys.modules["PySide6"] = None\n'
            'sys.modules["PySide6.QtCore"] = None\n'
            'sys.modules["PySide6.QtGui"] = None\n'
            'sys.modules["PySide6.QtQml"] = None\n'
            'from zapret_console.gui.app import run_gui\n'
            'sys.exit(run_gui())\n'))
        if HAVE_PYSIDE:
            self.skipTest('PySide6 установлен в этой среде; подмена не действует')
        self.assertEqual(r.returncode, 1)
        self.assertIn('PySide6', r.stdout)
        self.assertIn('.[gui]', r.stdout)


    @unittest.skipUnless(HAVE_PYSIDE, 'PySide6 extra required')
    def test_actual_application_exec_exits_after_safe_window_close(self):
        code = r"""
import sys, threading
from pathlib import Path
from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickWindow
from test_gui import FakeBackend
from zapret_console.gui.bridge import BackendBridge
app=QGuiApplication([])
backend=FakeBackend()
pending=sys.argv[1]=='pending'
if pending:
    backend.request_gate=threading.Event()
bridge=BackendBridge(backend)
engine=QQmlApplicationEngine()
engine.rootContext().setContextProperty('bridge',bridge)
engine.load(QUrl.fromLocalFile(str(Path(sys.argv[2])/'src/zapret_console/gui/qml/Main.qml')))
window=engine.rootObjects()[0]
bridge.start()
def close():
    if pending:
        bridge.restartService()
        QTimer.singleShot(100, window.close)
        QTimer.singleShot(300, backend.request_gate.set)
    else:
        window.close()
QTimer.singleShot(200, close)
QTimer.singleShot(2000, lambda: app.exit(73))
result=app.exec()
assert not bridge._worker.isRunning()
assert bridge.requestClose() is True
assert len(backend.requests)==int(pending)
del engine
bridge.stop()
sys.exit(result)
"""
        for state in ('idle', 'pending'):
            with self.subTest(state=state):
                env=dict(os.environ, PYTHONPATH=os.pathsep.join([str(ROOT/'src'),str(ROOT/'tests')]), QT_QPA_PLATFORM='offscreen', QT_QUICK_BACKEND='software')
                result=subprocess.run([sys.executable,'-c',code,state,str(ROOT)],env=env,capture_output=True,text=True,timeout=15)
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertEqual(result.stderr,'')


class PackageDataTests(unittest.TestCase):
    def test_wheel_contains_qml_resources(self):
        try:
            import setuptools  # noqa: F401
        except ImportError:
            self.skipTest('setuptools недоступен для локальной сборки')
        probe = subprocess.run([sys.executable, '-m', 'pip', '--version'], capture_output=True)
        if probe.returncode != 0:
            self.skipTest('pip недоступен в этой среде; сборка проверяется в venv с extra gui')
        with tempfile.TemporaryDirectory() as out_dir:
            source = Path(out_dir) / 'source'
            source.mkdir()
            for name in ('pyproject.toml', 'README.md', 'LICENSE'):
                shutil.copy2(ROOT / name, source / name)
            shutil.copytree(ROOT / 'src', source / 'src',
                            ignore=shutil.ignore_patterns('__pycache__', '*.egg-info'))
            r = subprocess.run([sys.executable, '-m', 'pip', 'wheel', '--no-deps',
                                '--no-build-isolation', '-w', out_dir, str(source)],
                               capture_output=True, text=True, timeout=300)
            self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
            wheels = list(Path(out_dir).glob('*.whl'))
            self.assertTrue(wheels)
            import zipfile
            with zipfile.ZipFile(wheels[0]) as wheel:
                names = wheel.namelist()
            self.assertFalse(any('/tui/' in name for name in names), 'Removed Textual frontend must not enter the wheel')
            for resource in ('Main.qml', 'Theme.qml', 'GuiIcon.qml', 'AppButton.qml', 'qmldir'):
                self.assertIn(f'zapret_console/gui/qml/{resource}', names)


if __name__ == '__main__':
    unittest.main()
