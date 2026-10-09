"""QObject bridge between QML and the shared core/client layer.

The bridge owns no second backend implementation: all reads go through
client.snapshot/core.strategies and all changes through client.request with
mode='gui', executed on one background worker thread. Results come back as
Qt signals and are applied to properties and models only in the GUI thread.

Key contracts:
- file-changing actions are sent with the revision that was shown to the
  user (dialogs carry their own base revision), never with a freshly
  re-read one;
- an outdated or failed snapshot read leaves the current screen untouched
  (generation numbers), and revision=None disables file operations;
- busy blocks new mutations; conflicts are shown and refreshed, never
  retried automatically;
- requestClose() starts a safe shutdown: the timer stops, no new jobs are
  accepted, the worker receives its stop sentinel exactly once and the
  window quits only after the QThread has actually finished. Closing never
  blocks the GUI thread, never terminates the worker and never claims that
  a running operation was cancelled.
"""
import queue
import re

from PySide6.QtCore import Property, QAbstractListModel, QModelIndex, QObject, Qt, QThread, QTimer, Signal, Slot

from .. import client, core

REFRESH_INTERVAL_MS = 3000


class OperationWorker(QThread):
    """Single background thread for reads and client requests.

    Jobs report through signals, so nothing touches QML models off the GUI
    thread. An unexpected job error is reported as a failed signal instead of
    silently losing the result.
    """

    failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._queue = queue.Queue()
        self._shutdown_requested = False

    def run(self):
        while True:
            job = self._queue.get()
            if job is None:
                return
            try:
                job()
            except Exception as e:  # last-resort guard; jobs report their own errors
                self.failed.emit(f'Внутренняя ошибка: {e}')

    def submit(self, fn):
        if not self.isRunning():
            self.start()
        self._queue.put(fn)

    def begin_shutdown(self):
        """Queue the stop sentinel exactly once; pending jobs still finish."""
        if not self._shutdown_requested:
            self._shutdown_requested = True
            self._queue.put(None)

    def wait_finished(self, timeout_s):
        self.begin_shutdown()
        return self.wait(int(timeout_s * 1000))


class ProfilesModel(QAbstractListModel):
    NameRole = Qt.UserRole + 1
    StrategyRole = Qt.UserRole + 2
    InterfaceRole = Qt.UserRole + 3
    DamagedRole = Qt.UserRole + 4
    ErrorRole = Qt.UserRole + 5

    countChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows = []

    def get_count(self):
        return len(self._rows)
    count = Property(int, get_count, notify=countChanged)

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._rows)

    def data(self, index, role=Qt.DisplayRole):
        if not 0 <= index.row() < len(self._rows):
            return None
        row = self._rows[index.row()]
        if role == ProfilesModel.NameRole:
            return row['name']
        if role == ProfilesModel.StrategyRole:
            return row['strategy']
        if role == ProfilesModel.InterfaceRole:
            return row['interface']
        if role == ProfilesModel.DamagedRole:
            return row['damaged']
        if role == ProfilesModel.ErrorRole:
            return row['error']
        return None

    def roleNames(self):
        return {ProfilesModel.NameRole: b'name',
                ProfilesModel.StrategyRole: b'strategy',
                ProfilesModel.InterfaceRole: b'interface',
                ProfilesModel.DamagedRole: b'damaged',
                ProfilesModel.ErrorRole: b'error'}

    def set_rows(self, rows):
        if rows == self._rows:
            return
        old_count = len(self._rows)
        common = min(old_count, len(rows))
        if common:
            self._rows[:common] = rows[:common]
            self.dataChanged.emit(self.index(0), self.index(common - 1), list(self.roleNames()))
        if len(rows) < old_count:
            self.beginRemoveRows(QModelIndex(), len(rows), old_count - 1)
            del self._rows[len(rows):]
            self.endRemoveRows()
        elif len(rows) > old_count:
            self.beginInsertRows(QModelIndex(), old_count, len(rows) - 1)
            self._rows.extend(rows[old_count:])
            self.endInsertRows()
        if len(rows) != old_count:
            self.countChanged.emit()


class StrategiesModel(QAbstractListModel):
    NameRole = Qt.UserRole + 1
    CurrentRole = Qt.UserRole + 2

    countChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows = []

    def get_count(self):
        return len(self._rows)
    count = Property(int, get_count, notify=countChanged)

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._rows)

    def data(self, index, role=Qt.DisplayRole):
        if not 0 <= index.row() < len(self._rows):
            return None
        row = self._rows[index.row()]
        if role == StrategiesModel.NameRole:
            return row['name']
        if role == StrategiesModel.CurrentRole:
            return row['current']
        return None

    def roleNames(self):
        return {StrategiesModel.NameRole: b'name',
                StrategiesModel.CurrentRole: b'current'}

    def set_rows(self, rows):
        if rows == self._rows:
            return
        old_count = len(self._rows)
        common = min(old_count, len(rows))
        if common:
            self._rows[:common] = rows[:common]
            self.dataChanged.emit(self.index(0), self.index(common - 1), list(self.roleNames()))
        if len(rows) < old_count:
            self.beginRemoveRows(QModelIndex(), len(rows), old_count - 1)
            del self._rows[len(rows):]
            self.endRemoveRows()
        elif len(rows) > old_count:
            self.beginInsertRows(QModelIndex(), old_count, len(rows) - 1)
            self._rows.extend(rows[old_count:])
            self.endInsertRows()
        if len(rows) != old_count:
            self.countChanged.emit()


class RealBackend(client.Backend):
    """GUI-compatible name for the shared UI-free adapter."""

    def __init__(self, mode="gui"):
        super().__init__(mode=mode)


STATE_TEXT = {'active': 'Сервис работает', 'activating': 'Запускается', 'deactivating': 'Останавливается',
              'inactive': 'Сервис остановлен', 'failed': 'Сбой сервиса', 'reloading': 'Перезагрузка',
              'maintenance': 'Обслуживание', 'unknown': 'Состояние неизвестно'}
STATE_TONE = {'active': 'ok', 'failed': 'error', 'unknown': 'warn'}
STATE_CHIP = {'active': 'Запущен', 'activating': 'Запускается', 'deactivating': 'Останавливается',
              'inactive': 'Остановлен', 'failed': 'Сбой', 'reloading': 'Перезагрузка',
              'maintenance': 'Обслуживание', 'unknown': 'Неизвестно'}
AUTOSTART_TEXT = {'enabled': 'Включён', 'disabled': 'Выключен', 'static': 'Статический',
                  'linked': 'Подключён', 'masked': 'Замаскирован', 'unknown': 'Неизвестно'}


def _describe_result(result):
    code = result.get('code')
    message = str(result.get('message') or '')
    if code == 'busy':
        return ('Занято', 'Другое изменение уже выполняется. Дождись его завершения и повтори действие.')
    if code == 'auth_cancelled':
        return ('Авторизация отменена', 'Операция не выполнена: запрос пароля отменён.')
    if code == 'auth_failed':
        return ('Авторизация не выполнена', 'Операция не выполнена: не удалось авторизоваться.')
    if code == 'permission_denied':
        return ('Недостаточно прав', message or 'Операция требует прав администратора.')
    if code == 'invalid_request':
        return ('Некорректный запрос', message)
    return ('Ошибка операции', message or 'Операция не выполнена.')


class BackendBridge(QObject):
    """QML-facing state and actions; one worker thread, GUI-thread-only models."""

    serviceStateChanged = Signal()
    autostartChanged = Signal()
    connectionChanged = Signal()
    lastEventChanged = Signal()
    busyChanged = Signal()
    closingChanged = Signal()
    revisionChanged = Signal()
    loadingChanged = Signal()
    messageRaised = Signal(str, str)
    operationStarted = Signal(str)
    snapshotReady = Signal(int, object, object)
    readFailed = Signal(int, str)
    operationFinished = Signal(str, object)
    inspectionFinished = Signal(str, object)
    inspectionProgress = Signal(str)
    inspectionChanged = Signal()

    def __init__(self, backend=None, quit_callback=None, parent=None):
        super().__init__(parent)
        self._backend = backend if backend is not None else RealBackend(mode='gui')
        self._quit_callback = quit_callback
        self._worker = OperationWorker(self)
        self._worker.failed.connect(self._on_worker_failed)
        self._worker.finished.connect(self._on_worker_finished)
        self.snapshotReady.connect(self._on_snapshot_ready)
        self.readFailed.connect(self._on_read_failed)
        self.operationFinished.connect(self._on_operation_finished)
        self.inspectionFinished.connect(self._on_inspection_finished)
        self.inspectionProgress.connect(self._on_inspection_progress)
        self._inspection_pending = False
        self._inspection_text = ''
        self._diagnostic_report = ''
        self._diagnostic_status = 'Проверка ещё не запускалась'
        self._diagnostic_tone = 'muted'
        self._journal_text = ''
        self._journal_warning = ''
        self._journal_status = 'Журнал ещё не загружен'
        self._timer = QTimer(self)
        self._timer.setInterval(REFRESH_INTERVAL_MS)
        self._timer.timeout.connect(self.refresh)
        self._snapshot_generation = 0
        self._snapshot_pending = False
        self._loading = True
        self._event_tone = 'muted'
        self._strategy_installed = False
        self._first_snapshot_done = False
        self._manual_refresh = False
        self._read_problem = False
        self._busy = False
        self._busy_text = ''
        self._closing = False
        self._close_finished = False
        self._service_state = 'unknown'
        self._service_text = STATE_TEXT['unknown']
        self._service_tone = 'warn'
        self._service_chip = STATE_CHIP['unknown']
        self._autostart_text = AUTOSTART_TEXT['unknown']
        self._autostart_tone = 'warn'
        self._autostart_active = False
        self._interface = '—'
        self._strategy = '—'
        self._shown_revision = None
        self._revision_error = ''
        self._config_error = ''
        self._last_event = 'Читаем состояние…'
        self._strategy_filter = ''
        self._strategy_all = []
        self._strategy_current = ''
        self.profiles = ProfilesModel(self)
        self.strategies = StrategiesModel(self)

    # -- properties -------------------------------------------------------
    def get_service_text(self):
        return self._service_text
    serviceText = Property(str, get_service_text, notify=serviceStateChanged)

    def get_service_tone(self):
        return self._service_tone
    serviceTone = Property(str, get_service_tone, notify=serviceStateChanged)

    def get_service_running(self):
        return self._service_state == 'active'
    serviceRunning = Property(bool, get_service_running, notify=serviceStateChanged)

    def get_autostart_text(self):
        return self._autostart_text
    autostartText = Property(str, get_autostart_text, notify=autostartChanged)

    def get_autostart_tone(self):
        return self._autostart_tone
    autostartTone = Property(str, get_autostart_tone, notify=autostartChanged)

    def get_autostart_active(self):
        return self._autostart_active
    autostartActive = Property(bool, get_autostart_active, notify=autostartChanged)

    def get_service_chip(self):
        return self._service_chip
    serviceChip = Property(str, get_service_chip, notify=serviceStateChanged)

    def get_loading(self):
        return self._loading
    loading = Property(bool, get_loading, notify=loadingChanged)

    def get_event_tone(self):
        return self._event_tone
    eventTone = Property(str, get_event_tone, notify=lastEventChanged)

    def get_strategy_installed(self):
        return self._strategy_installed
    strategyInstalled = Property(bool, get_strategy_installed, notify=connectionChanged)

    def get_interface(self):
        return self._interface
    interfaceName = Property(str, get_interface, notify=connectionChanged)

    def get_strategy(self):
        return self._strategy
    strategy = Property(str, get_strategy, notify=connectionChanged)

    def get_can_mutate_files(self):
        return self._shown_revision is not None
    canMutateFiles = Property(bool, get_can_mutate_files, notify=revisionChanged)

    def get_revision(self):
        return self._shown_revision or ''
    revision = Property(str, get_revision, notify=revisionChanged)

    def get_revision_error(self):
        return self._revision_error
    revisionError = Property(str, get_revision_error, notify=revisionChanged)

    def get_config_error(self):
        return self._config_error
    configError = Property(str, get_config_error, notify=revisionChanged)

    def get_busy(self):
        return self._busy or self._inspection_pending
    busy = Property(bool, get_busy, notify=busyChanged)

    def get_busy_text(self):
        return self._inspection_text if self._inspection_pending else self._busy_text
    busyText = Property(str, get_busy_text, notify=busyChanged)

    def get_closing(self):
        return self._closing
    closing = Property(bool, get_closing, notify=closingChanged)

    def get_last_event(self):
        return self._last_event
    lastEvent = Property(str, get_last_event, notify=lastEventChanged)

    def get_profile_name_hint(self):
        return core.PROFILE_NAME_HINT
    profileNameHint = Property(str, get_profile_name_hint, constant=True)

    def get_profiles_model(self):
        return self.profiles
    profilesModel = Property(QObject, get_profiles_model, constant=True)

    def get_strategies_model(self):
        return self.strategies
    strategiesModel = Property(QObject, get_strategies_model, constant=True)

    diagnosticReport = Property(str, lambda self: self._diagnostic_report, notify=inspectionChanged)
    diagnosticStatus = Property(str, lambda self: self._diagnostic_status, notify=inspectionChanged)
    diagnosticTone = Property(str, lambda self: self._diagnostic_tone, notify=inspectionChanged)
    journalText = Property(str, lambda self: self._journal_text, notify=inspectionChanged)
    journalWarning = Property(str, lambda self: self._journal_warning, notify=inspectionChanged)
    journalStatus = Property(str, lambda self: self._journal_status, notify=inspectionChanged)

    @Slot(bool)
    def runDiagnostics(self, privileged=False):
        self._start_inspection('diagnostic', privileged)

    @Slot()
    def refreshJournal(self):
        self._start_inspection('journal')

    @Slot(str)
    def copyText(self, text):
        from PySide6.QtGui import QGuiApplication
        QGuiApplication.clipboard().setText(text)
        self._set_last_event('Текст скопирован.', 'muted')

    def _start_inspection(self, kind, privileged=False):
        if self.busy or self._closing:
            return
        self._inspection_pending = True
        self._inspection_text = 'Проверяем Discord…' if kind == 'diagnostic' else 'Читаем журнал…'
        self.busyChanged.emit()
        backend = self._backend
        def job():
            try:
                data = backend.diagnose(privileged=privileged, progress=self.inspectionProgress.emit) if kind == 'diagnostic' else backend.journal()
                self.inspectionFinished.emit(kind, {'ok': True, 'data': data})
            except Exception as e:
                self.inspectionFinished.emit(kind, {'ok': False, 'error': str(e), 'code': getattr(e, 'code', None)})
        self._worker.submit(job)

    def _on_inspection_progress(self, message):
        if self._inspection_pending:
            self._inspection_text = message
            self.busyChanged.emit()

    def _on_inspection_finished(self, kind, result):
        self._inspection_pending = False
        self._inspection_text = ''
        self.busyChanged.emit()
        if not result['ok']:
            message = result['error']
            if kind == 'diagnostic':
                self._diagnostic_status = ('Проверка отменена: ' if result.get('code') == 'auth_cancelled' else 'Проверка не завершена: ') + message
                self._diagnostic_tone = 'muted' if result.get('code') == 'auth_cancelled' else 'error'
            else:
                self._journal_status = 'Не удалось прочитать журнал'
                self._journal_warning = message
            self._set_last_event(message, 'muted' if result.get('code') == 'auth_cancelled' else 'error')
        elif kind == 'diagnostic':
            data = result['data']
            self._diagnostic_report = data['report']
            self._diagnostic_status = 'Сетевые проверки прошли' if data['network_ok'] else 'Часть сетевых проверок не прошла'
            # Network success alone never proves zapret/VPN/voice participation.
            self._diagnostic_tone = 'warn' if not data['network_ok'] or data['route_interface'] != data['configured_interface'] else 'muted'
            self._set_last_event('Диагностика завершена.', self._diagnostic_tone)
        else:
            data = result['data']
            self._journal_text = data['text']
            self._journal_warning = data['warning']
            self._journal_status = ('Журнал обновлён' if data['text'].strip() else 'Доступных записей нет') if data['ok'] else 'Не удалось прочитать журнал'
            self._set_last_event(self._journal_status, 'warn' if data['warning'] or not data['ok'] else 'muted')
        self.inspectionChanged.emit()

    # -- lifecycle --------------------------------------------------------
    def start(self):
        self._timer.start()
        self.refresh()

    def stop(self):
        """Test/cleanup helper: joins the worker with a bounded wait."""
        self._timer.stop()
        self._worker.wait_finished(5.0)

    @Slot(result=bool)
    def requestClose(self):
        """Begin the safe shutdown; False keeps the window in a waiting state.

        The timer stops, no new jobs are accepted and the worker receives its
        stop sentinel exactly once. The quit callback fires only after the
        QThread has actually finished (worker.finished), so closing never
        destroys a running thread and never claims a running operation was
        cancelled. Closing does not block the GUI thread.
        """
        if not self._closing:
            self._closing = True
            self._timer.stop()
            self._set_last_event('Закрытие: ожидание завершения операции…', 'muted')
            self.closingChanged.emit()
            self._worker.begin_shutdown()
            if not self._worker.isRunning():
                # Поток не запускался или уже завершился.
                self._on_worker_finished()
        return False

    # -- reads ------------------------------------------------------------
    @Slot()
    def refreshManual(self):
        if self._closing:
            return
        self._manual_refresh = True
        self.refresh()

    @Slot()
    def refresh(self):
        """Request one snapshot+strategies read; overlapping requests are skipped."""
        if self._closing or self._snapshot_pending:
            return
        self._snapshot_pending = True
        self._snapshot_generation += 1
        generation = self._snapshot_generation
        backend = self._backend

        def job():
            try:
                snap = backend.snapshot()
                strategies = backend.strategies()
            except Exception as e:
                self.readFailed.emit(generation, str(e))
                return
            self.snapshotReady.emit(generation, snap, strategies)

        self._worker.submit(job)

    def _on_snapshot_ready(self, generation, snap, strategies):
        if generation != self._snapshot_generation:
            return
        self._snapshot_pending = False
        self._loading = False
        self.loadingChanged.emit()
        # Polling updates state, not the user's last operation result. A read
        # problem takes priority; recovery and explicit refresh are new events.
        if snap.get('revision') is None:
            self._set_last_event('Состояние прочитано не полностью.', 'warn')
        elif not self._first_snapshot_done or self._manual_refresh or self._read_problem:
            self._set_last_event('Настройки прочитаны.', 'accent')
        self._first_snapshot_done = True
        self._manual_refresh = False
        self._read_problem = snap.get('revision') is None
        self._service_state = str(snap.get('service_state') or 'unknown')
        self._service_text = STATE_TEXT.get(self._service_state, self._service_state)
        self._service_tone = STATE_TONE.get(self._service_state, 'warn')
        self._service_chip = STATE_CHIP.get(self._service_state, self._service_state)
        self._autostart_text = AUTOSTART_TEXT.get(str(snap.get('autostart') or 'unknown'), 'Неизвестно')
        self._autostart_tone = 'warn' if self._autostart_text == 'Неизвестно' else 'ok'
        self._autostart_active = str(snap.get('autostart') or '') == 'enabled'
        config = snap.get('config')
        self._interface = config['interface'] if config else '—'
        self._strategy = config['strategy'] if config else '—'
        self._strategy_current = config['strategy'] if config else ''
        self._strategy_installed = bool(self._strategy_current) and self._strategy_current in (strategies or [])
        self._shown_revision = snap.get('revision')
        self._revision_error = snap.get('revision_error') or ''
        self._config_error = snap.get('config_error') or ''
        self.profiles.set_rows(self._profile_rows(snap))
        self._apply_strategies(strategies)
        self.serviceStateChanged.emit()
        self.autostartChanged.emit()
        self.connectionChanged.emit()
        self.revisionChanged.emit()

    @staticmethod
    def _profile_rows(snap):
        rows = []
        for entry in snap.get('profiles') or []:
            data = entry.get('config')
            error = entry.get('error')
            rows.append({'name': entry.get('name', ''),
                         'strategy': data['strategy'] if data else '—',
                         'interface': data['interface'] if data else '—',
                         'damaged': data is None,
                         'error': error or ''})
        return rows

    def _on_read_failed(self, generation, message):
        if generation != self._snapshot_generation:
            return
        self._snapshot_pending = False
        self._loading = False
        self.loadingChanged.emit()
        self._service_state = 'unknown'
        self._service_text = STATE_TEXT['unknown']
        self._service_tone = 'warn'
        self._service_chip = STATE_CHIP['unknown']
        self._autostart_text = 'Неизвестно'
        self._autostart_tone = 'warn'
        self._autostart_active = False
        self._shown_revision = None
        self._strategy_installed = False
        self.serviceStateChanged.emit()
        self.autostartChanged.emit()
        self.connectionChanged.emit()
        self.revisionChanged.emit()
        self._manual_refresh = False
        self._read_problem = True
        self._set_last_event(f'Состояние недоступно: {message}', 'error')
        self.messageRaised.emit('Состояние недоступно',
                                f'Не удалось прочитать состояние: {message}')

    def _apply_strategies(self, strategies):
        self._strategy_all = list(strategies)
        self._rebuild_strategies()

    def _rebuild_strategies(self):
        wanted = self._strategy_filter.strip().lower()
        self.strategies.set_rows([{'name': name, 'current': name == self._strategy_current}
                                  for name in self._strategy_all
                                  if not wanted or wanted in name.lower()])

    @Slot(str)
    def setStrategyFilter(self, text):
        self._strategy_filter = str(text or '')
        self._rebuild_strategies()

    # -- mutations --------------------------------------------------------
    @Slot()
    def startService(self):
        self._run_operation('start', 'Запуск сервиса', 'start', None, None)

    @Slot()
    def stopService(self):
        self._run_operation('stop', 'Остановка сервиса', 'stop', None, None)

    @Slot()
    def restartService(self):
        self._run_operation('restart', 'Перезапуск сервиса', 'restart', None, None)

    @Slot()
    def enableAutostart(self):
        self._run_operation('enable', 'Включение автозапуска', 'enable', None, None)

    @Slot()
    def disableAutostart(self):
        self._run_operation('disable', 'Выключение автозапуска', 'disable', None, None)

    @Slot(str, str)
    def saveProfile(self, name, revision):
        # Имя проверяется до отправки в privileged helper: диалог не должен
        # запускать авторизацию ради заведомо некорректного ввода.
        if not isinstance(name, str) or not re.fullmatch(core.PROFILE_NAME, name):
            self.messageRaised.emit('Некорректное имя профиля', core.PROFILE_NAME_HINT)
            return
        self._run_operation('profile-save', f'Сохранение профиля «{name}»', 'profile-save', name, revision)

    @Slot(str, str)
    def restoreProfile(self, name, revision):
        self._run_operation('profile-restore', f'Восстановление профиля {name}', 'profile-restore', name, revision)

    @Slot(str, str)
    def replaceProfile(self, name, revision):
        self._run_operation('profile-replace', f'Замена профиля {name}', 'profile-replace', name, revision)

    @Slot(str, str)
    def deleteProfile(self, name, revision):
        self._run_operation('profile-delete', f'Удаление профиля {name}', 'profile-delete', name, revision)

    @Slot(str, str)
    def applyStrategy(self, name, revision):
        self._run_operation('strategy', f'Применение стратегии {name}', 'strategy', name, revision)

    def _run_operation(self, kind, description, action, value, revision):
        if self._busy or self._inspection_pending or self._closing:
            return False
        self._busy = True
        self._busy_text = description + '…'
        self.busyChanged.emit()
        self.operationStarted.emit(description)
        backend = self._backend

        def job():
            try:
                result = backend.request(action, value, revision or None)
            except Exception as e:
                self.operationFinished.emit(kind, {'protocol': 1, 'ok': False, 'code': 'transport_error',
                                                   'message': f'Внутренняя ошибка клиента: {e}', 'data': None})
                return
            self.operationFinished.emit(kind, result)

        self._worker.submit(job)
        return True

    # -- result handling --------------------------------------------------
    def _on_operation_finished(self, kind, result):
        self._busy = False
        self._busy_text = ''
        self.busyChanged.emit()
        ok = bool(result.get('ok'))
        code = result.get('code')
        if ok:
            self._set_last_event('Готово.', 'ok')
        elif code == 'conflict':
            self._set_last_event('Настройки изменились в другом окне; операция не повторена.', 'warn')
            if not self._closing:
                self.messageRaised.emit('Настройки изменились',
                                        'Настройки изменились в другом окне. Обновите данные и повторите действие.')
        else:
            title, text = _describe_result(result)
            self._set_last_event(f'{title}: {text}',
                                 'muted' if code == 'auth_cancelled' else 'warn' if code == 'busy' else 'error')
            if not self._closing:
                self.messageRaised.emit(title, text)
        # при закрытии quit придёт от worker.finished — сначала завершится поток
        if not self._closing:
            self.refresh()

    def _on_worker_failed(self, message):
        self._set_last_event(message, 'error')
        if not self._closing:
            self.messageRaised.emit('Ошибка', message)

    def _on_worker_finished(self):
        """QThread.finished: поток реально завершился — теперь можно закрывать."""
        if self._close_finished:
            return
        self._close_finished = True
        if self._quit_callback is not None:
            self._quit_callback()
        else:
            from PySide6.QtCore import QCoreApplication
            QCoreApplication.quit()

    def _set_last_event(self, text, tone='muted'):
        self._last_event = text
        self._event_tone = tone
        self.lastEventChanged.emit()
