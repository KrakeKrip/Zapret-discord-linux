"""--gui entry point: a QML window over the shared client.

PySide6 is imported here and only here; the CLI, core and client keep
working without the gui extra. The application never runs with root: the
privileged helper asks for authorization through polkit on demand.
"""
import os
import sys
from pathlib import Path

INSTALL_HINT = ('GUI-пакет не установлен (PySide6). Для разработки:\n'
                '  python3 -m venv .venv\n'
                '  .venv/bin/pip install ".[gui]"\n'
                '  .venv/bin/python -m zapret_console --gui')


def run_gui():
    """Open the window; returns the process exit code."""
    if os.geteuid() == 0:
        print('GUI не запускается с правами root. Запусти обычным пользователем:\n'
              '  python -m zapret_console --gui')
        return 1
    try:
        import PySide6  # noqa: F401
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtQml import QQmlApplicationEngine
    except ImportError:
        print(INSTALL_HINT)
        return 1

    app = QGuiApplication(sys.argv[:1])
    app.setApplicationName('Zapret Manager')
    app.setDesktopFileName('zapret-console')
    from PySide6.QtGui import QIcon
    app.setWindowIcon(QIcon.fromTheme('zapret-console'))
    engine = QQmlApplicationEngine()
    from .bridge import BackendBridge, RealBackend
    bridge = BackendBridge(RealBackend(mode='gui'))
    engine.rootContext().setContextProperty('bridge', bridge)
    qml_main = Path(__file__).resolve().parent / 'qml' / 'Main.qml'
    engine.load(QUrl.fromLocalFile(str(qml_main)))
    if not engine.rootObjects():
        print('Не удалось загрузить QML-интерфейс.', file=sys.stderr)
        return 1
    bridge.start()
    exit_code = app.exec()
    # QML-объекты уничтожаются раньше моста; worker к этому моменту уже
    # завершён потоком закрытия (worker.finished → quit).
    del engine
    bridge.stop()
    return exit_code
