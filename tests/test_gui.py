"""GUI tests: bridge logic, QML loading, CLI guards and package data.

PySide6-dependent tests are skipped when the gui extra is not installed;
they must be executed in the development venv (pip install ".[gui]").
"""
import json
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
    from PySide6.QtCore import QCoreApplication, QMetaObject, QObject, QUrl
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine
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
        self.bridge.refresh()
        self.assertTrue(wait_until(lambda: self.bridge.serviceText == 'Работает'))
        self.assertEqual(self.bridge.serviceTone, 'ok')
        self.assertTrue(self.bridge.serviceRunning)
        self.assertEqual(self.bridge.autostartText, 'Включён')
        self.assertEqual(self.bridge.interfaceName, 'any')
        self.assertEqual(self.bridge.strategy, 'general_alt11.bat')
        self.assertTrue(self.bridge.canMutateFiles)
        self.assertEqual(self.bridge.revision, 'a' * 64)
        self.assertEqual(self.bridge.profiles.rowCount(), 2)
        self.assertEqual(self.bridge.strategies.rowCount(), 3)

    def test_service_state_unknown_and_files_disabled_on_read_error(self):
        self.backend.snapshot_error = 'нет доступа'
        self.bridge.refresh()
        # 'Неизвестно' совпадает с начальным состоянием, ждём признак завершения чтения
        self.assertTrue(wait_until(lambda: self.bridge.lastEvent.startswith('Состояние недоступно')))
        self.assertIn('нет доступа', self.bridge.lastEvent)
        self.assertEqual(self.bridge.serviceText, 'Неизвестно')
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
        self.assertTrue(wait_until(lambda: self.bridge.serviceText == 'Работает'))
        self.bridge._snapshot_generation = 7  # newer generation in flight
        stale = dict(SAMPLE, service_state='failed', revision='e' * 64)
        self.bridge._on_snapshot_ready(1, stale, [])
        self.assertEqual(self.bridge.serviceText, 'Работает')
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
        self.assertTrue(any(title == 'Данные изменились' for title, _ in self.messages))
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
        self.assertEqual(self.bridge.serviceText, 'Работает')
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
            r = subprocess.run([sys.executable, '-m', 'pip', 'wheel', '--no-deps',
                                '--no-build-isolation', '-w', out_dir, str(ROOT)],
                               capture_output=True, text=True, timeout=300)
            self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
            wheels = list(Path(out_dir).glob('*.whl'))
            self.assertTrue(wheels)
            import zipfile
            with zipfile.ZipFile(wheels[0]) as wheel:
                names = wheel.namelist()
            self.assertIn('zapret_console/gui/qml/Main.qml', names)
            self.assertIn('zapret_console/gui/qml/Theme.qml', names)
            self.assertIn('zapret_console/gui/qml/qmldir', names)


if __name__ == '__main__':
    unittest.main()
