"""Graphical interface package (PySide6 / Qt Quick).

Importing this package must stay cheap: Qt is imported only by gui.app and
gui.bridge, which are loaded solely for --gui. The core, client and CLI work
without PySide6 installed.
"""
