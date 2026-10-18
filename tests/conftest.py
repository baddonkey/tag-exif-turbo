import os
import re
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

import pytest
import httpx
import httpx2
from PySide6.QtCore import QObject, QSettings, Signal
from PySide6.QtGui import QFont, QFontDatabase, QGuiApplication

from backend.app_controller import AppController
from backend.config import Config
from backend.image_provider import ImageProvider


def capture_test_windows(nodeid):
    directory = os.environ.get("TAGGER_TEST_ARTIFACTS")
    app = QGuiApplication.instance()
    if directory and app:
        target = Path(directory)
        target.mkdir(parents=True, exist_ok=True)
        name = re.sub(r"[^A-Za-z0-9_.-]", "_", nodeid)
        for index, window in enumerate(app.topLevelWindows()):
            if window.isVisible() and hasattr(window, "grabWindow"):
                window.grabWindow().save(str(target / f"{name}-{index}.png"))


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if report.when == "call" and report.failed:
        capture_test_windows(item.nodeid)


@pytest.fixture
def record_ui_failure(request):
    def record():
        if sys.exc_info()[0] is not None:
            capture_test_windows(request.node.nodeid)

    return record


@pytest.fixture
def allow_http_endpoint():
    endpoints = set()

    def allow(url):
        endpoint = httpx.URL(url)
        assert endpoint.host in {"127.0.0.1", "::1", "localhost"}
        endpoints.add((endpoint.scheme, endpoint.host, endpoint.port))

    return endpoints, allow


@pytest.fixture(autouse=True)
def offline_http(monkeypatch, allow_http_endpoint):
    endpoints, _ = allow_http_endpoint

    def protect(module):
        original = module.AsyncClient.send

        async def guarded(client, request, *args, **kwargs):
            mocked = isinstance(client._transport, module.MockTransport)
            endpoint = (request.url.scheme, request.url.host, request.url.port)
            if not mocked and endpoint not in endpoints:
                raise AssertionError(f"Unexpected network request during offline tests: {request.url.host}")
            return await original(client, request, *args, **kwargs)

        monkeypatch.setattr(module.AsyncClient, "send", guarded)

    for module in (httpx, httpx2):
        protect(module)


@pytest.fixture(scope="session")
def gui():
    app = QGuiApplication.instance() or QGuiApplication([])
    app.setOrganizationName("ExifTurboTests")
    app.setApplicationName("TaggerTests")
    if os.name == "nt":
        font_path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "segoeui.ttf"
        if font_path.is_file():
            QFontDatabase.addApplicationFont(str(font_path))
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