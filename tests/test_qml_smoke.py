from pathlib import Path

from PySide6.QtCore import QObject, QUrl
from PySide6.QtGui import QIcon, QImage
from PySide6.QtQml import QQmlApplicationEngine, QQmlEngine, QQmlExpression
from PySide6.QtTest import QTest
from shiboken6 import delete

from test_controller import show_review


def test_application_icon_assets(gui):
    assets = Path(__file__).parents[1] / "assets"
    for size in (16, 24, 32, 48, 64, 128, 256, 512, 1024):
        image = QImage(str(assets / f"icon-{size}.png"))
        assert not image.isNull()
        assert image.width() == image.height() == size
        assert not image.hasAlphaChannel()
        for horizontal, vertical in ((0, 0), (size - 1, 0), (0, size - 1), (size - 1, size - 1)):
            assert image.pixelColor(horizontal, vertical).name() == "#ffffff"
    for suffix in ("png", "ico", "icns"):
        icon = QIcon(str(assets / f"tag-exif-turbo.{suffix}"))
        assert not icon.pixmap(128, 128).isNull(), suffix


def test_qml_models_resize_and_dialogs(controller, gui):
    engine = QQmlApplicationEngine()
    warnings = []
    engine.warnings.connect(lambda errors: warnings.extend(error.toString() for error in errors))
    engine.addImageProvider("preview", controller.provider)
    engine.rootContext().setContextProperty("appController", controller)
    engine.load(QUrl.fromLocalFile(str(Path(__file__).parents[1] / "qml" / "Main.qml")))
    assert engine.rootObjects(), warnings
    window = engine.rootObjects()[0]
    try:
        show_review(controller)
        controller._receive("connected", controller._token, {
            "sets": [controller._selected, {"id": 2, "name": "other-test", "member_count": 1}],
            "selected": controller._selected,
            "offset": 0,
            "loaded": {
                "record": controller._record,
                "bytes": controller._bytes,
                "image": QImage(200, 100, QImage.Format.Format_RGB32),
            },
            "review": {"status": "pending", "tags": controller._suggested.values()},
            "can_write": True,
            "tools": {},
        })
        selector = window.findChild(QObject, "imageSetSelector")
        assert qml_value(selector, "count") == 3
        assert qml_value(selector, "currentIndex") == 1
        QTest.qWait(100)
        preview = window.findChild(QObject, "imagePreview")
        assert preview is not None
        assert preview.property("sourceSize").width() == 200
        for width, height in ((920, 640), (1600, 1000)):
            window.setWidth(width)
            window.setHeight(height)
            QTest.qWait(50)
            assert not window.grabWindow().isNull()
        controller._update(statusMessage="Loading next image")
        QTest.qWait(50)
        assert window.width() == 1600
        assert window.height() == 1000
        qml_value(window, "viewer.SplitView.preferredWidth = 980")
        QTest.qWait(50)
        panel_width = qml_value(window, "viewer.width")
        for image_id, set_name, image_width, image_height in (
            (43, "smoke-test", 100, 200),
            (44, "other-test", 300, 100),
        ):
            image = QImage(image_width, image_height, QImage.Format.Format_RGB32)
            image.fill("#50b088")
            controller._update(
                selectedImageSet=set_name,
                currentImageUrl=controller.provider.store(f"{image_id}/layout-test", image),
                currentFilename=f"image-{image_id}.jpg",
                currentOffset=1 if set_name == "smoke-test" else 0,
            )
            QTest.qWait(100)
            assert window.width() == 1600
            assert window.height() == 1000
            assert qml_value(window, "viewer.width") == panel_width
            assert qml_value(window, "viewer.height === split.height")
            assert preview.property("sourceSize").width() == image_width
            assert preview.width() == qml_value(window, "viewer.fitWidth")
            assert preview.height() == qml_value(window, "viewer.fitHeight")
        controller._update(selectedImageSet="smoke-test", currentOffset=0)
        selector = window.findChild(QObject, "imageSetSelector")
        for dark in (True, False):
            expression = QQmlExpression(QQmlEngine.contextForObject(selector), selector, f"Theme.dark = {'true' if dark else 'false'}")
            expression.evaluate()
            assert not expression.hasError()
            popup_open = QQmlExpression(QQmlEngine.contextForObject(selector), selector, "popup.open()")
            popup_open.evaluate()
            assert not popup_open.hasError()
            QTest.qWait(100)
            assert qml_value(selector, "popup.contentItem.itemAtIndex(0).contentItem.text") == "Current selected image"
            assert qml_value(selector, "popup.contentItem.itemAtIndex(2).contentItem.text") == "other-test"
            foreground = qml_value(selector, "popup.contentItem.itemAtIndex(2).contentItem.color")
            background = qml_value(selector, "popup.contentItem.itemAtIndex(2).background.color")
            assert contrast(foreground, background) >= 4.5
            QQmlExpression(QQmlEngine.contextForObject(selector), selector, "popup.close()").evaluate()
        reload_button = window.findChild(QObject, "reloadCurrentImageButton")
        assert not reload_button.property("visible")
        controller._selected_mode = True
        controller._can_read_selected_image = True
        controller.flow.resolve("skipped")
        controller._update(selectedImageSet="Current selected image")
        assert reload_button.property("visible")
        assert reload_button.property("enabled")
        qml_value(reload_button, "clicked()")
        assert controller.worker.commands[-1].kind == "load"
        assert controller.worker.commands[-1].payload["selected_image"]
        assert not reload_button.property("enabled")
        assert not warnings, "\n".join(warnings)
    finally:
        window.setProperty("allowedToClose", True)
        window.close()
        delete(engine)


def qml_value(scope, source):
    expression = QQmlExpression(QQmlEngine.contextForObject(scope), scope, source)
    value = expression.evaluate()
    assert not expression.hasError(), expression.error().toString()
    return value[0] if isinstance(value, tuple) else value


def contrast(foreground, background):
    def luminance(color):
        components = [color.redF(), color.greenF(), color.blueF()]
        linear = [value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4 for value in components]
        return sum(value * weight for value, weight in zip(linear, (0.2126, 0.7152, 0.0722)))

    values = sorted((luminance(foreground), luminance(background)))
    return (values[1] + 0.05) / (values[0] + 0.05)