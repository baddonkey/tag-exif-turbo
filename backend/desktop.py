import ctypes
import hashlib
import sys
from pathlib import Path

from PySide6.QtCore import QLockFile, QObject, Qt, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket


APP_ID = "ExifTurbo.AITagger"


class SingleInstance(QObject):
    activationRequested = Signal()

    def __init__(self, directory: Path, parent=None) -> None:
        super().__init__(parent)
        directory.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(str(directory.resolve()).encode("utf-8")).hexdigest()[:24]
        self._name = f"tag-exif-turbo-{digest}"
        self._lock = QLockFile(str(directory / "instance.lock"))
        self._lock.setStaleLockTime(0)
        self._owns_lock = False
        self._server = QLocalServer(self)
        self._server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self._server.newConnection.connect(self._activate_connections)

    def start(self, activate: bool = True) -> bool:
        if self._owns_lock:
            return True
        if not self._lock.tryLock(0):
            if self._lock.error() != QLockFile.LockError.LockFailedError:
                raise RuntimeError("Cannot acquire the application instance lock.")
            if activate:
                socket = QLocalSocket()
                socket.connectToServer(self._name)
                if socket.waitForConnected(1000):
                    socket.write(b"activate")
                    socket.waitForBytesWritten(1000)
                socket.disconnectFromServer()
            return False
        self._owns_lock = True
        QLocalServer.removeServer(self._name)
        if not self._server.listen(self._name):
            error = self._server.errorString()
            self.close()
            raise RuntimeError(f"Cannot listen for application activation: {error}")
        return True

    def _activate_connections(self) -> None:
        while self._server.hasPendingConnections():
            connection = self._server.nextPendingConnection()
            self.activationRequested.emit()
            connection.close()
            connection.deleteLater()

    def close(self) -> None:
        if self._owns_lock:
            self._server.close()
            self._lock.unlock()
            self._owns_lock = False


def set_windows_taskbar_identity() -> None:
    if sys.platform != "win32":
        return
    setter = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID
    setter.argtypes = [ctypes.c_wchar_p]
    setter.restype = ctypes.c_long
    result = setter(APP_ID)
    if result != 0:
        raise OSError(f"Cannot set the Windows taskbar identity (HRESULT {result:#x}).")


def activate_window(window) -> None:
    if window.windowState() == Qt.WindowState.WindowMinimized:
        window.showMaximized()
    else:
        window.show()
    window.raise_()
    window.requestActivate()