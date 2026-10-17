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