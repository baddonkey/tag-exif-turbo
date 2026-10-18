from pathlib import Path

from PySide6.QtCore import QDeadlineTimer, QObject, Qt, QUrl
from PySide6.QtGui import QIcon, QImage, QWindow
from PySide6.QtQml import QQmlApplicationEngine, QQmlEngine, QQmlExpression
from PySide6.QtTest import QTest
from shiboken6 import delete

from test_controller import enable_metadata, show_review
from main import show_startup_window


def wait_for_preview(preview, width):
    deadline = QDeadlineTimer(3000)
    while preview.property("sourceSize").width() != width and not deadline.hasExpired():
        QTest.qWait(10)
    assert preview.property("sourceSize").width() == width


def test_startup_centers_window_before_maximizing(gui, monkeypatch):
    window = QWindow()
    window.resize(920, 640)
    available = window.screen().availableGeometry()
    expected = (available.x() + (available.width() - 920) // 2,
                available.y() + (available.height() - 640) // 2)
    positions = []
    maximize = window.showMaximized

    def record_maximize():
        positions.append((window.x(), window.y()))
        maximize()

    monkeypatch.setattr(window, "showMaximized", record_maximize)
    try:
        show_startup_window(window)
        assert positions == [expected]
        assert window.windowState() == Qt.WindowState.WindowMaximized
        assert window.isVisible()
    finally:
        window.close()


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


def test_qml_models_resize_and_dialogs(controller, gui, record_ui_failure):
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
        preview = window.findChild(QObject, "imagePreview")
        assert preview is not None
        wait_for_preview(preview, 200)
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
            wait_for_preview(preview, image_width)
            assert window.width() == 1600
            assert window.height() == 1000
            assert qml_value(window, "viewer.width") == panel_width
            assert qml_value(window, "viewer.height === split.height")
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
        record_ui_failure()
        window.setProperty("allowedToClose", True)
        window.close()
        delete(engine)


def qml_value(scope, source):
    expression = QQmlExpression(QQmlEngine.contextForObject(scope), scope, source)
    value = expression.evaluate()
    assert not expression.hasError(), expression.error().toString()
    return value[0] if isinstance(value, tuple) else value


def test_unified_metadata_controls_and_description_typing(controller, gui, tmp_path, record_ui_failure):
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
        enable_metadata(controller)
        controller._record["metadata"] = {"XMP-dc:Subject": ["private", "tree"], "IFD0:ImageDescription": "Embedded caption"}
        controller._update(descriptionSuggestion="A tree beneath clouds.")
        tabs = window.findChild(QObject, "metadataTabs")
        underline = window.findChild(QObject, "activeMetadataTabUnderline")
        for dark in (True, False):
            qml_value(tabs, f"Theme.dark = {'true' if dark else 'false'}")
            for index in range(3):
                tabs.setProperty("currentIndex", index)
                QTest.qWait(1)
                assert underline.property("height") == 3
                assert underline.property("width") == qml_value(tabs, "currentItem.width")
                assert underline.property("x") == qml_value(tabs, "leftPadding + currentItem.x")
                assert underline.property("y") == tabs.property("height") - 3
                assert underline.property("color") == qml_value(tabs, "Theme.accent")
                assert contrast(underline.property("color"), qml_value(tabs, "Theme.surface")) >= 3
        tabs.setProperty("currentIndex", 1)
        QTest.qWait(50)
        draft = window.findChild(QObject, "descriptionDraft")
        assert draft.property("enabled")
        qml_value(draft, "forceActiveFocus()")
        qml_value(draft, 'insert(length, "Manual ")')
        QTest.keyClick(window, Qt.Key.Key_Return)
        qml_value(draft, 'insert(length, "description")')
        assert controller.currentDescription == "Manual \ndescription"
        assert draft.property("text") == controller.currentDescription
        exclude_description = window.findChild(QObject, "ignoreEmbeddedDescription")
        qml_value(exclude_description, "toggle(); toggled()")
        assert controller.ignoreEmbeddedDescription
        assert controller.proposedDescription == "Manual \ndescription"
        assert window.findChild(QObject, "useDescriptionContext") is None
        assert window.findChild(QObject, "embeddedContextEditor") is None
        refine = window.findChild(QObject, "regenerateDescriptionWithEmbeddedContext")
        generate_description = window.findChild(QObject, "generateDescriptionSuggestion")
        assert refine.property("text") == generate_description.property("text") + " with embedded Context"
        previous_suggestion = controller.descriptionSuggestion
        controller._update(descriptionSuggestion="")
        assert generate_description.property("text") == "Generate suggestion"
        assert refine.property("text") == "Generate suggestion with embedded Context"
        controller._update(descriptionSuggestion=previous_suggestion)
        assert refine.property("text") == "Regenerate suggestion with embedded Context"
        assert not refine.property("enabled")
        controller._update(ollamaConnected=True, modelReady=True)
        assert refine.property("enabled")
        tags_before_refinement = controller._suggested.values()
        qml_value(refine, "clicked()")
        request = controller.worker.commands[-1]
        assert request.payload["mode"] == "refine"
        assert request.payload["sources"] == {"embedded": "Embedded caption"}
        assert controller.ignoreEmbeddedDescription
        assert not refine.property("enabled")
        controller._receive("analyzed", controller._token, {
            "refinement": True, "description": "Refined caption", "review_notes": ["Date is supplied context."],
            "context_sources": request.payload["sources"],
        })
        assert controller.currentDescription == "Manual \ndescription"
        assert controller._suggested.values() == tags_before_refinement
        assert window.findChild(QObject, "refinementProvenance").property("visible")
        assert controller.descriptionReviewNotes == ["Date is supplied context."]
        original_width, original_height = window.width(), window.height()
        description_scroll = window.findChild(QObject, "descriptionReviewScroll")
        for dark in (True, False):
            qml_value(tabs, f"Theme.dark = {'true' if dark else 'false'}")
            for width, height in ((920, 640), (1600, 1000)):
                window.setWidth(width)
                window.setHeight(height)
                QTest.qWait(50)
                offset = qml_value(refine, "mapToItem(null, 0, 0).y") - qml_value(description_scroll, "mapToItem(null, 0, 0).y")
                qml_value(description_scroll, f"contentItem.contentY = Math.max(0, contentItem.contentY + {offset})")
                QTest.qWait(20)
                assert refine.property("width") <= description_scroll.property("width")
                assert refine.property("y") == generate_description.property("y")
                assert refine.property("x") >= generate_description.property("x") + generate_description.property("width")
                assert refine.property("x") + refine.property("width") <= refine.parentItem().width() + 1
                assert window.grabWindow().save(str(tmp_path / f"refinement-{width}-{'dark' if dark else 'light'}.png"))
        window.setWidth(original_width)
        window.setHeight(original_height)
        controller._update(ollamaConnected=False, modelReady=False)
        tabs.setProperty("currentIndex", 0)
        QTest.qWait(50)
        mode = window.findChild(QObject, "tagModeSelector")
        current_heading = window.findChild(QObject, "currentCustomTagsHeading")
        suggestion_editor = window.findChild(QObject, "tagSuggestionEditor")
        assert current_heading.property("y") < mode.property("y") < suggestion_editor.property("y")
        custom_preview = window.findChild(QObject, "customTagsSaveRepeater")
        derivative_preview = window.findChild(QObject, "proposedMetadataPreview")
        derivative_heading = window.findChild(QObject, "proposedDerivativeTagsHeading")
        assert derivative_preview.property("visible")
        assert derivative_heading.property("visible")
        assert derivative_preview.property("text") == ", ".join(controller.proposedTags)
        tabs.setProperty("currentIndex", 2)
        assert not derivative_preview.property("visible")
        assert not derivative_heading.property("visible")
        tabs.setProperty("currentIndex", 0)
        assert qml_value(custom_preview, "count") == len(controller.proposedCustomTags)
        assert "existing" in [qml_value(custom_preview, f"itemAt({index}).label") for index in range(qml_value(custom_preview, "count"))]
        assert "private" not in [qml_value(custom_preview, f"itemAt({index}).label") for index in range(qml_value(custom_preview, "count"))]
        merge_mode = window.findChild(QObject, "mergeTagMode")
        replace_mode = window.findChild(QObject, "replaceTagMode")
        replace_all_mode = window.findChild(QObject, "replaceAllTagMode")
        assert merge_mode.property("checked")
        assert not replace_mode.property("checked")
        assert not replace_all_mode.property("checked")
        assert replace_all_mode.property("enabled")
        qml_value(replace_all_mode, "clicked()")
        assert replace_all_mode.property("checked")
        assert not merge_mode.property("checked")
        assert not replace_mode.property("checked")
        assert controller.tagMode == "replace_all"
        assert not controller.ignoreAllEmbeddedTags
        assert "private" in controller.proposedTags
        qml_value(replace_mode, "clicked()")
        assert controller.tagMode == "replace"
        assert not controller.ignoreAllEmbeddedTags
        assert not replace_all_mode.property("checked")
        assert replace_mode.property("checked")
        assert not merge_mode.property("checked")
        assert controller.removedCustomTags == ["existing"]
        assert "existing" not in [qml_value(custom_preview, f"itemAt({index}).label") for index in range(qml_value(custom_preview, "count"))]
        qml_value(merge_mode, "clicked()")
        assert controller.removedCustomTags == []
        assert "existing" in [qml_value(custom_preview, f"itemAt({index}).label") for index in range(qml_value(custom_preview, "count"))]
        saved_tags = window.findChild(QObject, "savedCustomTagRepeater")
        qml_value(saved_tags, "itemAt(0).removeRequested()")
        assert controller.tagMode == "replace"
        assert replace_mode.property("checked")
        assert not merge_mode.property("checked")
        assert not qml_value(saved_tags, "itemAt(0).included")
        qml_value(window.findChild(QObject, "applyChangesButton"), "clicked()")
        removal = window.findChild(QObject, "removeCustomTagsConfirmation")
        assert removal.property("visible")
        assert not any(command.kind == "apply" for command in controller.worker.commands)
        qml_value(removal, "reject()")
        qml_value(saved_tags, "itemAt(0).removeRequested()")
        assert controller.removedCustomTags == []
        qml_value(merge_mode, "clicked()")
        keywords = window.findChild(QObject, "embeddedTagRepeater")
        assert qml_value(keywords, "itemAt(0).label") == "private"
        tag_scroll = window.findChild(QObject, "tagReviewScroll")
        QTest.qWait(200)
        qml_value(tag_scroll, "contentItem.contentY = Math.max(0, contentItem.contentHeight - contentItem.height)")
        QTest.qWait(50)
        for included, target in ((False, "padding"), (True, "label"), (False, "button")):
            QTest.qWait(50)
            pill = qml_value(keywords, "itemAt(0)")
            assert pill.width() > 0
            toggle = pill.findChild(QObject, "tagChipToggle")
            assert toggle.property("text") == "\u00d7"
            if target == "button":
                point = qml_value(toggle, "mapToItem(null, width / 2, height / 2)")
            elif target == "label":
                label = pill.findChild(QObject, "tagChipLabel")
                point = qml_value(label, "mapToItem(null, width / 2, height / 2)")
            else:
                point = qml_value(pill, "mapToItem(null, 4, height / 2)")
            assert qml_value(tag_scroll, "mapToItem(null, 0, 0).y") <= point.y() < qml_value(tag_scroll, "mapToItem(null, 0, height).y")
            QTest.mouseClick(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point.toPoint())
            assert qml_value(keywords, "itemAt(0).included") is included
            pill = qml_value(keywords, "itemAt(0)")
            assert pill.findChild(QObject, "tagChipLabel").property("font").strikeOut() is not included
        assert controller._existing.values() == ["existing"]
        assert not any(command.kind == "apply" for command in controller.worker.commands)
        ignore_all = window.findChild(QObject, "ignoreAllEmbeddedTags")
        qml_value(ignore_all, "toggle(); toggled()")
        assert controller.ignoreAllEmbeddedTags
        assert not qml_value(keywords, "itemAt(1).included")
        assert not qml_value(keywords, "itemAt(0).enabled")
        qml_value(ignore_all, "toggle(); toggled()")
        assert not controller.ignoreAllEmbeddedTags
        assert qml_value(keywords, "itemAt(1).included")
        assert controller._metadata_draft["excluded_embedded_tags"] == ["private"]
        assert derivative_preview.property("text") == ", ".join(controller.proposedTags)
        assert "private" not in derivative_preview.property("text")
        controller._update(ollamaConnected=True, modelReady=True)
        tags_before = controller._suggested.values()
        generate = window.findChild(QObject, "generateDescriptionSuggestion")
        assert generate.property("enabled")
        qml_value(generate, "clicked()")
        assert controller.worker.commands[-1].payload["description_only"]
        controller._receive("analyzed", controller._token, {"tags": ["different"], "description": "New proposal", "description_only": True})
        assert controller._suggested.values() == tags_before
        assert controller.descriptionSuggestion == "New proposal"
        controller.setDescription("Long draft " * 100)
        assert not any(command.kind == "apply" for command in controller.worker.commands)
        for width, height in ((920, 640), (1600, 1000)):
            window.setWidth(width)
            window.setHeight(height)
            tabs.setProperty("currentIndex", 0)
            QTest.qWait(50)
            qml_value(tag_scroll, "contentItem.contentY = 0")
            QTest.qWait(20)
            assert mode.property("width") > 0
            assert mode.property("width") <= window.width()
            assert replace_all_mode.property("x") + replace_all_mode.property("width") <= mode.property("width") + 1
            clear_control = window.findChild(QObject, "clearSuggestedTagsButton")
            generate_control = window.findChild(QObject, "generateSuggestedTagsButton")
            assert generate_control.property("x") >= clear_control.property("x") + clear_control.property("width")
            assert generate_control.property("x") + generate_control.property("width") <= generate_control.parentItem().width() + 1
            assert derivative_heading.property("y") > window.findChild(QObject, "customTagsSavePreview").property("y")
            assert derivative_preview.property("y") > derivative_heading.property("y")
            assert window.grabWindow().save(str(tmp_path / f"tags-{width}.png"))
            tabs.setProperty("currentIndex", 1)
            QTest.qWait(50)
            preview = window.findChild(QObject, "proposedMetadataPreview")
            assert preview.property("width") > 0
            assert draft.property("width") <= window.width()
            assert window.grabWindow().save(str(tmp_path / f"metadata-{width}.png"))
        controller._baseline["description"] = "Saved description"
        controller.setDescription("")
        button = window.findChild(QObject, "applyChangesButton")
        qml_value(button, "clicked()")
        confirmation = window.findChild(QObject, "clearDescriptionConfirmation")
        assert confirmation.property("visible")
        assert not any(command.kind == "apply" for command in controller.worker.commands)
        qml_value(confirmation, "reject()")
        controller.setDescription("Manual \ndescription")
        clear_tags = window.findChild(QObject, "clearSuggestedTagsButton")
        assert clear_tags.property("enabled")
        qml_value(clear_tags, "clicked()")
        assert controller._suggested.values() == []
        assert controller._existing.values() == ["existing"]
        assert not clear_tags.property("enabled")
        assert controller.tagMode == "merge"
        assert qml_value(custom_preview, "count") == 1
        assert qml_value(custom_preview, "itemAt(0).label") == "existing"
        controller.setTagMode("replace")
        assert qml_value(custom_preview, "count") == 0
        tabs.setProperty("currentIndex", 0)
        assert window.findChild(QObject, "emptyCustomTagsPreview").property("visible")
        controller.setTagMode("merge")
        generate_tags = window.findChild(QObject, "generateSuggestedTagsButton")
        assert generate_tags.property("enabled")
        qml_value(generate_tags, "clicked()")
        assert controller.worker.commands[-1].kind == "analyze"
        assert not controller.worker.commands[-1].payload["description_only"]
        assert not generate_tags.property("enabled")
        controller._receive("analyzed", controller._token, {"tags": ["fresh suggestion"], "description": "Fresh description proposal"})
        assert controller._suggested.values() == ["fresh suggestion"]
        assert controller.currentDescription == "Manual \ndescription"
        qml_value(saved_tags, "itemAt(0).removeRequested()")
        button = window.findChild(QObject, "applyChangesButton")
        assert button.property("text") == "Apply Changes"
        qml_value(button, "clicked()")
        assert removal.property("visible")
        qml_value(removal, "accept()")
        assert controller.worker.commands[-1].kind == "apply"
        assert controller.worker.commands[-1].payload["tag_mode"] == "replace"
        assert "existing" not in controller.worker.commands[-1].payload["tags"]
        assert controller.worker.commands[-1].payload["metadata_draft"]["description"] == "Manual \ndescription"
        assert not warnings, "\n".join(warnings)
    finally:
        record_ui_failure()
        window.setProperty("allowedToClose", True)
        window.close()
        delete(engine)


def contrast(foreground, background):
    def luminance(color):
        components = [color.redF(), color.greenF(), color.blueF()]
        linear = [value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4 for value in components]
        return sum(value * weight for value, weight in zip(linear, (0.2126, 0.7152, 0.0722)))

    values = sorted((luminance(foreground), luminance(background)))
    return (values[1] + 0.05) / (values[0] + 0.05)