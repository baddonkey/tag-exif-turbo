import argparse
import os
import sys
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QSettings, QStandardPaths, QTimer, QUrl
from PySide6.QtGui import QFont, QGuiApplication, QIcon
from PySide6.QtQml import QQmlApplicationEngine

from backend import __version__
from backend.app_controller import AppController
from backend.config import Config
from backend.desktop import SingleInstance, activate_window, set_windows_taskbar_identity
from backend.image_provider import ImageProvider


def show_startup_window(window) -> None:
    screen = window.screen()
    if screen is not None:
        available = screen.availableGeometry()
        window.setPosition(
            available.x() + (available.width() - window.width()) // 2,
            available.y() + (available.height() - window.height()) // 2,
        )
    window.showMaximized()


def main() -> int:
    parser = argparse.ArgumentParser(description="Exif Turbo AI Tagger")
    parser.add_argument("--version", action="version", version=f"Exif Turbo AI Tagger {__version__}")
    parser.add_argument("--smoke", action="store_true", help="Load QML and exit without network requests")
    parser.add_argument("--live-check", action="store_true", help="Read a real preview and analyze it, then exit without writing tags")
    parser.add_argument("--screenshot", type=Path, help="Capture the window at smoke/live-check completion")
    args = parser.parse_args()
    resource_directory = Path(__file__).parent
    if not (resource_directory / "qml").is_dir():
        resource_directory = resource_directory / "backend" / "resources"
    os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")
    set_windows_taskbar_identity()
    app = QGuiApplication(sys.argv)
    app.setOrganizationName("ExifTurbo")
    app.setApplicationName("AI Tagger")
    app.setApplicationVersion(__version__)
    try:
        instance = SingleInstance(Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)), app)
        primary = instance.start(activate=not (args.smoke or args.live_check))
    except (OSError, RuntimeError) as error:
        print(f"Cannot start Exif Turbo AI Tagger: {error}", file=sys.stderr)
        return 1
    if not primary:
        if args.smoke or args.live_check:
            print("Exif Turbo AI Tagger is already running. Close it before running diagnostics.", file=sys.stderr)
            return 1
        return 0
    app.aboutToQuit.connect(instance.close)
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256, 512, 1024):
        icon.addFile(str(resource_directory / "assets" / f"icon-{size}.png"))
    app.setWindowIcon(icon)
    app.setFont(QFont("Avenir Next", 12))
    settings = QSettings()
    config = Config.from_env()
    config = replace(config,
        mcp_url=os.getenv("MCP_URL") or settings.value("mcpUrl", config.mcp_url),
        ollama_url=os.getenv("OLLAMA_URL") or settings.value("ollamaUrl", config.ollama_url),
        model=os.getenv("OLLAMA_MODEL") or settings.value("modelName", config.model),
    )
    provider = ImageProvider()
    controller = AppController(config, provider)
    engine = QQmlApplicationEngine()
    engine.addImageProvider("preview", provider)
    engine.rootContext().setContextProperty("appController", controller)
    engine.load(QUrl.fromLocalFile(str(resource_directory / "qml" / "Main.qml")))
    if not engine.rootObjects():
        controller.shutdown()
        instance.close()
        return 1
    window = engine.rootObjects()[0]
    window.setIcon(icon)
    instance.activationRequested.connect(lambda: activate_window(window))
    show_startup_window(window)
    app.aboutToQuit.connect(controller.shutdown)
    controller.quitApproved.connect(app.quit)
    exit_code = 0

    def finish(code: int = 0) -> None:
        nonlocal exit_code
        exit_code = code
        window.setProperty("allowedToClose", True)
        if args.screenshot:
            args.screenshot.parent.mkdir(parents=True, exist_ok=True)
            if not window.grabWindow().save(str(args.screenshot)):
                print("Screenshot capture failed", file=sys.stderr)
                exit_code = 1
        app.quit()

    if args.smoke:
        QTimer.singleShot(1000, finish)
    else:
        QTimer.singleShot(0, controller.connectServices)
    if args.live_check:
        monitor = QTimer()
        monitor.setInterval(250)
        analysis_seen = False

        def observe_analysis() -> None:
            nonlocal analysis_seen
            if controller.workflowState == "ANALYZING":
                analysis_seen = True

        controller.changed.connect(observe_analysis)

        def check() -> None:
            if controller.errorMessage and not controller.busy:
                print("LIVE CHECK FAILED:", controller.errorMessage, file=sys.stderr)
                monitor.stop()
                finish(1)
            elif analysis_seen and controller.currentImageUrl and controller._suggested.rowCount() >= 5 and not controller.busy:
                print("LIVE CHECK:", controller.currentFilename, controller.currentDimensions, controller._suggested.values())
                monitor.stop()
                QTimer.singleShot(500, finish)
            elif not analysis_seen and controller.currentImageUrl and not controller.busy and controller.canAnalyze:
                controller.analyzeCurrentImage()
            elif controller.currentImageUrl and not controller.busy and not controller.modelReady:
                print("LIVE CHECK FAILED:", controller.modelStatus, file=sys.stderr)
                monitor.stop()
                finish(1)

        monitor.timeout.connect(check)
        monitor.start()
        QTimer.singleShot(240000, lambda: finish(1))
    app.exec()
    del engine
    instance.close()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())