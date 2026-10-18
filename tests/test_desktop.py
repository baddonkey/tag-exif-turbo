import ctypes
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QWindow
from PySide6.QtTest import QSignalSpy

from backend import desktop


def test_windows_taskbar_identity(monkeypatch):
    setter = Mock(return_value=0)
    monkeypatch.setattr(desktop, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(desktop, "ctypes", SimpleNamespace(
        windll=SimpleNamespace(shell32=SimpleNamespace(SetCurrentProcessExplicitAppUserModelID=setter)),
        c_wchar_p="wide-string", c_long="hresult",
    ))
    desktop.set_windows_taskbar_identity()
    setter.assert_called_once_with(desktop.APP_ID)
    assert setter.argtypes == ["wide-string"]
    assert setter.restype == "hresult"
    setter.return_value = -1
    with pytest.raises(OSError, match="taskbar identity"):
        desktop.set_windows_taskbar_identity()


def test_taskbar_identity_is_windows_only(monkeypatch):
    monkeypatch.setattr(desktop, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(desktop, "ctypes", None)
    desktop.set_windows_taskbar_identity()


def test_activate_existing_window_restores_minimized_window(gui):
    window = QWindow()
    try:
        window.showMinimized()
        desktop.activate_window(window)
        assert window.windowState() == Qt.WindowState.WindowMaximized
        assert window.isVisible()
        window.showNormal()
        desktop.activate_window(window)
        assert window.windowState() == Qt.WindowState.WindowNoState
    finally:
        window.close()


def test_single_instance_activates_primary_and_releases_lock(gui, tmp_path):
    primary = desktop.SingleInstance(tmp_path)
    secondary = desktop.SingleInstance(tmp_path)
    diagnostic = desktop.SingleInstance(tmp_path)
    try:
        assert primary.start()
        activated = QSignalSpy(primary.activationRequested)
        assert not secondary.start()
        assert activated.count() or activated.wait(1000)
        assert activated.count() == 1
        secondary.close()
        assert not diagnostic.start(activate=False)
        assert activated.count() == 1
        primary.close()
        assert secondary.start()
        assert not primary.start(activate=False)
    finally:
        primary.close()
        secondary.close()
        diagnostic.close()
    assert not (tmp_path / "instance.lock").exists()


def test_instance_lock_is_scoped_to_user_directory(gui, tmp_path):
    first = desktop.SingleInstance(tmp_path / "first-user")
    second = desktop.SingleInstance(tmp_path / "second-user")
    try:
        assert first.start()
        assert second.start()
    finally:
        first.close()
        second.close()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows taskbar identity API")
def test_windows_reports_the_application_identity():
    desktop.set_windows_taskbar_identity()
    get_identity = ctypes.windll.shell32.GetCurrentProcessExplicitAppUserModelID
    get_identity.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
    get_identity.restype = ctypes.c_long
    free_identity = ctypes.windll.ole32.CoTaskMemFree
    free_identity.argtypes = [ctypes.c_void_p]
    free_identity.restype = None
    value = ctypes.c_void_p()
    assert get_identity(ctypes.byref(value)) == 0
    try:
        assert ctypes.wstring_at(value) == desktop.APP_ID
    finally:
        free_identity(value)


def test_single_instance_across_processes_and_crash_recovery(gui, tmp_path):
    primary_code = """
import sys
from pathlib import Path
from PySide6.QtCore import QCoreApplication, QTimer
from backend.desktop import SingleInstance
app = QCoreApplication([])
instance = SingleInstance(Path(sys.argv[1]), app)
assert instance.start()
instance.activationRequested.connect(lambda: print('activated', flush=True))
QTimer.singleShot(10000, app.quit)
print('ready', flush=True)
app.exec()
instance.close()
"""
    secondary_code = """
import sys
from pathlib import Path
from PySide6.QtCore import QCoreApplication
from backend.desktop import SingleInstance
app = QCoreApplication([])
instance = SingleInstance(Path(sys.argv[1]), app)
assert not instance.start()
print('secondary exited')
"""
    process = subprocess.Popen([sys.executable, "-c", primary_code, str(tmp_path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    replacement = desktop.SingleInstance(tmp_path)
    try:
        assert process.stdout.readline().strip() == "ready"
        secondary = subprocess.run([sys.executable, "-c", secondary_code, str(tmp_path)], capture_output=True, text=True, timeout=5)
        assert secondary.returncode == 0, secondary.stderr
        assert process.stdout.readline().strip() == "activated"
        assert not replacement.start(activate=False)
        process.kill()
        process.wait(timeout=5)
        assert replacement.start()
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=5)
        replacement.close()