from pathlib import Path
import tomllib

import pytest
from PySide6.QtGui import QImage
from PySide6.QtTest import QSignalSpy, QTest

from backend.state_manager import StateManager
from backend.workflow import State
from backend import __version__


def test_application_version_matches_manifest():
    with (Path(__file__).parents[1] / "pyproject.toml").open("rb") as manifest:
        assert __version__ == tomllib.load(manifest)["project"]["version"]


def show_review(controller, status="pending", offset=0, analysis_pending=False):
    image = QImage(200, 100, QImage.Format.Format_RGB32)
    image.fill("#50b088")
    controller._selected = {"id": 1, "name": "smoke-test", "member_count": 3}
    controller._sets = [controller._selected]
    controller._offset = offset
    controller._state(State.READY)
    controller._update(mcpConnected=True, totalImages=3, tagWriteAvailable=True)
    controller._display({"record": {"id": 42, "path": "/example.jpg", "filename": "example.jpg", "free_tags": ["existing"]}, "bytes": b"full-preview", "image": image}, {"status": status, "tags": ["tree", "sky", "grass", "cloud", "landscape"], "analysis_pending": analysis_pending})


def test_qt_properties_are_registered(controller):
    for name in ("mcpConnected", "imageSets", "currentImageUrl", "busy", "statusMessage", "currentDescription"):
        assert controller.metaObject().indexOfProperty(name) >= 0


def test_navigation_never_implies_approval(controller):
    show_review(controller)
    requested = QSignalSpy(controller.approvalRequested)
    controller.nextImage()
    assert requested.count() == 1
    assert controller.currentOffset == 0
    assert not any(command.kind in {"load", "apply"} for command in controller.worker.commands)
    controller.resolveApproval("cancel")
    assert controller.flow.unresolved
    controller.nextImage()
    controller.resolveApproval("skip")
    assert controller.worker.commands[-1].kind == "load"
    assert controller.worker.commands[-1].payload["offset"] == 1
    assert not any(command.kind == "apply" for command in controller.worker.commands)


def test_current_selected_image_is_a_single_image_target(controller):
    show_review(controller)
    controller._can_read_selected_image = True
    requested = QSignalSpy(controller.approvalRequested)
    controller.selectCurrentImage()
    assert requested.count() == 1
    controller.resolveApproval("skip")
    command = controller.worker.commands[-1]
    assert command.kind == "load"
    assert command.payload["selected_image"]
    assert controller.selectedImageSet == "Current selected image"
    assert controller.totalImages == 1
    assert not controller.canNext

    image = QImage(200, 100, QImage.Format.Format_RGB32)
    image.fill("#50b088")
    controller._receive("loaded", controller._token, {
        "loaded": {
            "record": {"id": 84, "path": "/selected.jpg", "filename": "selected.jpg", "free_tags": []},
            "bytes": b"selected-preview",
            "image": image,
        },
        "review": {"status": "pending", "tags": ["tree"]},
    })
    controller.applyTags()
    applied = controller.worker.commands[-1]
    assert applied.kind == "apply"
    assert applied.payload["selected_image"]
    assert applied.payload["journal"]["selected_image"]


@pytest.mark.parametrize("review", [None, {"status": "pending", "tags": [], "analysis_pending": False}])
def test_selected_image_generates_tags_for_new_or_empty_pending_review(controller, review):
    show_review(controller, "applied")
    controller._can_read_selected_image = True
    controller._update(ollamaConnected=True, modelReady=True)
    controller.selectCurrentImage()
    image = QImage(200, 100, QImage.Format.Format_RGB32)
    image.fill("#50b088")
    controller._receive("loaded", controller._token, {
        "loaded": {
            "record": {"id": 84, "path": "/selected.jpg", "filename": "selected.jpg"},
            "bytes": b"selected-preview",
            "image": image,
        },
        "review": review,
    })
    QTest.qWait(1)
    assert controller.flow.state == State.ANALYZING
    assert controller.worker.commands[-1].kind == "analyze"
    assert controller.worker.commands[-1].payload["bytes"] == b"selected-preview"
    tags = ["tree", "sky", "grass", "cloud", "landscape"]
    controller._receive("analyzed", controller._token, {"tags": tags})
    assert controller._suggested.values() == tags
    assert controller.flow.state == State.AWAITING_APPROVAL
    assert controller.canApply


@pytest.mark.parametrize("decision", ["cancel", "skip", "apply"])
def test_reload_current_image_resolves_review_before_loading_latest_selection(controller, decision):
    show_review(controller)
    controller._selected_mode = True
    controller._can_read_selected_image = True
    requested = QSignalSpy(controller.approvalRequested)
    assert controller.canReloadCurrentImage
    before = len(controller.worker.commands)
    controller.reloadCurrentImage()
    assert requested.count() == 1
    assert len(controller.worker.commands) == before
    controller.resolveApproval(decision)
    if decision == "cancel":
        assert len(controller.worker.commands) == before
        assert controller.flow.unresolved
        return
    if decision == "apply":
        assert controller.worker.commands[-1].kind == "apply"
        assert controller.worker.commands[-1].payload["record"]["id"] == 42
        controller._receive("applied", controller._token, {"tags": ["tree"]})
    command = controller.worker.commands[-1]
    assert command.kind == "load"
    assert command.payload["selected_image"]
    assert command.payload["offset"] == 0
    image = QImage(200, 100, QImage.Format.Format_RGB32)
    image.fill("#50b088")
    controller._update(ollamaConnected=True, modelReady=True)
    controller._receive("loaded", controller._token, {
        "loaded": {
            "record": {"id": 84, "path": "/new-selection.jpg", "filename": "new-selection.jpg"},
            "bytes": b"new-selection-preview", "image": image,
        },
        "review": None,
    })
    QTest.qWait(1)
    assert controller.currentFilename == "new-selection.jpg"
    assert controller.worker.commands[-1].kind == "analyze"
    assert controller.worker.commands[-1].payload["bytes"] == b"new-selection-preview"


@pytest.mark.parametrize("blocked", ["set-mode", "busy", "uncertain", "disconnected"])
def test_reload_current_image_is_guarded(controller, blocked):
    show_review(controller, "applied")
    controller._selected_mode = blocked != "set-mode"
    controller._can_read_selected_image = True
    if blocked == "busy":
        controller._state(State.LOADING_IMAGE)
    elif blocked == "uncertain":
        controller._uncertain = True
    elif blocked == "disconnected":
        controller._update(mcpConnected=False)
    before = len(controller.worker.commands)
    assert not controller.canReloadCurrentImage
    controller.reloadCurrentImage()
    assert len(controller.worker.commands) == before


def test_empty_pending_review_reports_unavailable_model_and_retry_reconnects(controller):
    show_review(controller)
    controller._update(ollamaConnected=True, modelReady=False, modelStatus="Model missing")
    image = QImage(200, 100, QImage.Format.Format_RGB32)
    image.fill("#50b088")
    controller._display({
        "record": controller._record, "bytes": b"preview", "image": image,
    }, {"status": "pending", "tags": []})
    assert "Model missing" in controller.errorMessage
    assert not any(command.kind == "analyze" for command in controller.worker.commands)
    controller._last_operation = "load"
    controller.retryLastOperation()
    assert controller.worker.commands[-1].kind == "connect"


def test_explicit_apply_snapshots_and_prevents_duplicate_write(controller):
    show_review(controller)
    controller.applyTags()
    command = controller.worker.commands[-1]
    assert command.kind == "apply"
    assert command.payload["record"] == {"id": 42, "path": "/example.jpg"}
    assert command.payload["journal"]["status"] == "uncertain"
    controller.addTag("late edit")
    controller.applyTags()
    assert len([item for item in controller.worker.commands if item.kind == "apply"]) == 1
    assert "late edit" not in command.payload["tags"]


def test_missing_writer_disables_apply(controller):
    show_review(controller)
    controller._update(tagWriteAvailable=False)
    controller.applyTags()
    assert not controller.canApply
    assert not any(command.kind == "apply" for command in controller.worker.commands)


def test_uncertain_write_retries_only_reconciliation(controller):
    show_review(controller)
    controller.applyTags()
    controller._receive("error", controller._token, {"operation": "apply", "message": "timeout"})
    assert not controller.canApply
    assert not controller.canSkip
    controller.retryLastOperation()
    assert controller.worker.commands[-1].kind == "reconcile"
    controller._receive("reconciled", controller._token, {"tags": ["existing", "tree"]})
    assert controller.canApply
    assert controller.flow.unresolved
    assert controller._existing.values() == ["existing", "tree"]


def test_stale_results_cannot_replace_draft(controller):
    show_review(controller)
    before = controller._suggested.values()
    controller._token = 5
    controller._receive("analyzed", 4, {"tags": ["stale"]})
    assert controller._suggested.values() == before


def test_revisit_restores_resolved_review_without_analysis(controller):
    show_review(controller, "applied")
    assert not controller.flow.unresolved
    assert not controller.canApply
    assert not any(command.kind == "analyze" for command in controller.worker.commands)
    controller.addTag("new suggestion")
    assert controller.flow.unresolved
    assert controller.canApply


def test_progress_round_trip_and_identity(tmp_path):
    document = {"endpoint": "one", "set_id": 1, "set_name": "smoke-test", "offset": 2, "image_id": 42, "path": "/a.jpg", "tags": ["tree"], "status": "pending"}
    state = StateManager(str(tmp_path))
    state.save(document)
    state.close()
    restored = StateManager(str(tmp_path))
    assert restored.restore("one") == document
    assert restored.review("one", 1, {"id": 42, "path": "/different.jpg"}) is None
    assert restored.restore("other") is None
    restored.close()


def test_settings_change_uses_approval_guard(controller):
    show_review(controller)
    requested = QSignalSpy(controller.approvalRequested)
    controller.configure("http://127.0.0.1:9999/mcp", controller.ollamaUrl, controller.modelName, False)
    assert requested.count() == 1
    assert controller.config.mcp_url.endswith(":8765/mcp")
    assert not controller.darkTheme
    controller.resolveApproval("skip")
    assert controller.config.mcp_url.endswith(":9999/mcp")
    assert controller.worker.commands[-1].kind == "connect"


def test_completed_progress_restores_and_can_regenerate(controller):
    show_review(controller, "applied", offset=2)
    assert controller.flow.state == State.COMPLETED
    controller._update(ollamaConnected=True, modelReady=True)
    controller.analyzeCurrentImage()
    assert controller.flow.state == State.ANALYZING


@pytest.mark.parametrize("direction, offset", [("next", 2), ("previous", 0)])
def test_navigation_during_analysis_discards_stale_results(controller, direction, offset):
    show_review(controller, offset=1)
    controller._update(ollamaConnected=True, modelReady=True)
    controller.analyzeCurrentImage()
    analysis_token = controller._token
    requested = QSignalSpy(controller.approvalRequested)
    assert controller.busy
    assert controller.canPrevious
    assert controller.canNext
    getattr(controller, f"{direction}Image")()
    assert requested.count() == 0
    assert controller.flow.state == State.LOADING_IMAGE
    assert controller.worker.commands[-1].kind == "load"
    assert controller.worker.commands[-1].payload["offset"] == offset
    saved = [command.payload for command in controller.worker.commands if command.kind == "save"][-1]
    assert saved["status"] == "pending"
    assert saved["analysis_pending"]
    assert not any(command.kind == "apply" for command in controller.worker.commands)
    before = controller._suggested.values()
    controller._receive("analyzed", analysis_token, {"tags": ["obsolete"]})
    controller._receive("error", analysis_token, {"operation": "analyze", "message": "obsolete error"})
    controller._receive("health", analysis_token, {"connected": False, "ready": False, "message": "obsolete health"})
    assert controller._suggested.values() == before
    assert not controller.errorMessage
    assert controller.modelReady
    assert controller.flow.state == State.LOADING_IMAGE


def test_navigation_stays_blocked_during_metadata_write(controller):
    show_review(controller, offset=1)
    controller.applyTags()
    before = len(controller.worker.commands)
    assert not controller.canPrevious
    assert not controller.canNext
    controller.nextImage()
    controller.previousImage()
    assert len(controller.worker.commands) == before


def test_revisiting_deferred_analysis_restarts_without_losing_draft(controller):
    controller._update(ollamaConnected=True, modelReady=True)
    show_review(controller, analysis_pending=True)
    before = controller._suggested.values()
    QTest.qWait(1)
    assert controller.flow.state == State.ANALYZING
    assert controller.worker.commands[-1].kind == "analyze"
    assert controller._suggested.values() == before
    assert controller.flow.unresolved