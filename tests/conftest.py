import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

import pytest
from PySide6.QtCore import QObject, QSettings, Signal
from PySide6.QtGui import QFont, QGuiApplication

from backend.app_controller import AppController
from backend.config import Config
from backend.image_provider import ImageProvider


@pytest.fixture(scope="session")
def gui():
    app = QGuiApplication.instance() or QGuiApplication([])
    app.setOrganizationName("ExifTurboTests")
    app.setApplicationName("TaggerTests")
    app.setFont(QFont("Avenir Next", 12))
    return app


class RecordingWorker(QObject):
    result = Signal(str, int, object)

    def __init__(self, config, directory, parent=None):
        super().__init__(parent)
        self.commands = []

    def start(self):
        pass

    def submit(self, command):
        self.commands.append(command)

    def stop(self):
        pass

    def wait(self, milliseconds=None):
        return True


@pytest.fixture
def controller(gui, monkeypatch, tmp_path):
    monkeypatch.setattr("backend.app_controller.Worker", RecordingWorker)
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))
    control = AppController(Config(), ImageProvider())
    yield control
    control.shutdown()