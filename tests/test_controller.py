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


def enable_metadata(controller):
    controller._metadata_capabilities = {name: True for name in (
        "set_image_description", "set_image_description_excluded",
        "set_image_embedded_tag_excluded", "set_image_all_embedded_tags_excluded")}
    controller._update(tagReplaceAvailable=True, descriptionWriteAvailable=True, descriptionExclusionAvailable=True,
                       tagExclusionAvailable=True, allTagsExclusionAvailable=True)


def test_metadata_edits_are_local_and_apply_without_tags_or_ollama(controller):
    show_review(controller)
    enable_metadata(controller)
    controller._suggested.replace([])
    controller._update(tagWriteAvailable=False)
    controller.setDescription("A tree.")
    controller.setIgnoreEmbeddedDescription(True)
    controller.setEmbeddedTagIncluded("private", False)
    controller.setIgnoreAllEmbeddedTags(True)
    controller.setIgnoreAllEmbeddedTags(False)
    assert controller._metadata_draft["excluded_embedded_tags"] == ["private"]
    assert not any(command.kind == "apply" for command in controller.worker.commands)
    assert controller.canApply
    controller.applyChanges()
    payload = controller.worker.commands[-1].payload
    assert payload["metadata_draft"]["description"] == "A tree."
    assert payload["metadata_draft"]["exclude_embedded_description"]
    assert payload["tags"] == []


def test_skip_discards_metadata_without_writing(controller):
    show_review(controller, offset=2)
    enable_metadata(controller)
    controller.setDescription("draft")
    controller.setIgnoreEmbeddedDescription(True)
    controller.skipImage()
    assert controller.currentDescription == ""
    assert not controller.ignoreEmbeddedDescription
    assert not any(command.kind == "apply" for command in controller.worker.commands)


def test_description_editor_preserves_spaces_and_newlines(controller):
    show_review(controller)
    enable_metadata(controller)
    controller.setDescription("A tree \n")
    assert controller.currentDescription == "A tree \n"
    assert controller.proposedDescription == "A tree"


def test_new_review_waiting_for_ollama_restarts_analysis_after_restore(controller):
    show_review(controller)
    image = QImage(200, 100, QImage.Format.Format_RGB32)
    loaded = {"record": controller._record, "bytes": b"preview", "image": image}
    controller._display(loaded, None)
    document = controller._journal()
    assert document["analysis_pending"]
    controller._update(ollamaConnected=True, modelReady=True)
    controller._display(loaded, document)
    QTest.qWait(1)
    assert controller.flow.state == State.ANALYZING


def test_new_ai_description_is_only_a_draft_and_does_not_require_writer(controller):
    show_review(controller)
    controller._receive("analyzed", controller._token, {"tags": ["tree"], "description": "A tree."})
    assert controller.descriptionSuggestion == "A tree."
    assert controller.currentDescription == ""
    assert controller.canApply
    enable_metadata(controller)
    controller._receive("analyzed", controller._token, {"tags": ["tree"], "description": "A tree."})
    assert controller.currentDescription == "A tree."
    assert not any(command.kind == "apply" for command in controller.worker.commands)


@pytest.mark.parametrize("status", ["pending", "skipped", "applied"])
def test_description_generation_preserves_existing_tag_and_description_drafts(controller, status):
    show_review(controller, status)
    enable_metadata(controller)
    controller._update(ollamaConnected=True, modelReady=True)
    controller.setDescription("Manual description")
    tags = controller._suggested.values()
    controller.generateDescriptionSuggestion()
    command = controller.worker.commands[-1]
    assert command.kind == "analyze"
    assert command.payload["description_only"]
    assert controller._journal()["analysis_description_only"]
    controller._receive("analyzed", controller._token, {
        "tags": ["replacement tags"], "description": "A new description proposal.", "description_only": True,
    })
    assert controller._suggested.values() == tags
    assert controller.currentDescription == "Manual description"
    assert controller.descriptionSuggestion == "A new description proposal."
    assert not any(command.kind == "apply" for command in controller.worker.commands)


def test_deferred_description_generation_restores_its_scope(controller):
    show_review(controller)
    controller._update(ollamaConnected=True, modelReady=True)
    controller.generateDescriptionSuggestion()
    document = controller._journal()
    image = QImage(200, 100, QImage.Format.Format_RGB32)
    controller._display({"record": controller._record, "bytes": b"preview", "image": image}, document)
    QTest.qWait(1)
    assert controller.worker.commands[-1].payload["description_only"]


def test_description_generation_retry_preserves_its_scope(controller):
    show_review(controller)
    controller._update(ollamaConnected=True, modelReady=True)
    controller.generateDescriptionSuggestion()
    controller._receive("error", controller._token, {"operation": "analyze", "message": "timeout"})
    controller.retryLastOperation()
    assert controller.worker.commands[-1].kind == "analyze"
    assert controller.worker.commands[-1].payload["description_only"]


def test_metadata_draft_restores_and_regeneration_never_clobbers_edits(controller):
    show_review(controller)
    enable_metadata(controller)
    controller.setDescription("Manual draft")
    document = controller._journal()
    image = QImage(200, 100, QImage.Format.Format_RGB32)
    controller._display({"record": controller._record, "bytes": b"preview", "image": image}, document)
    assert controller.currentDescription == "Manual draft"
    controller._receive("analyzed", controller._token, {"tags": ["tree"], "description": "AI proposal"})
    assert controller.currentDescription == "Manual draft"
    assert controller.descriptionSuggestion == "AI proposal"
    controller.setDescription("")
    controller._receive("analyzed", controller._token, {"tags": ["tree"], "description": "Another proposal"})
    assert controller.currentDescription == ""


def test_reconcile_preserves_intended_metadata_and_requires_fresh_apply(controller):
    show_review(controller)
    enable_metadata(controller)
    controller.setDescription("desired")
    controller.setIgnoreEmbeddedDescription(True)
    controller.applyChanges()
    controller._receive("error", controller._token, {"operation": "apply", "message": "timeout"})
    assert not controller.canApply
    actual = {**controller._record, "description": "desired"}
    controller.retryLastOperation()
    controller._receive("reconciled", controller._token, {"tags": ["existing"], "record": actual})
    assert controller.currentDescription == "desired"
    assert controller.ignoreEmbeddedDescription
    assert controller._baseline["description"] == "desired"
    assert controller.canApply
    assert controller.worker.commands[-1].kind == "save"


def test_saved_tag_removal_stages_replace_and_can_restore(controller):
    show_review(controller)
    enable_metadata(controller)
    assert controller.tagMode == "merge"
    controller._record["free_tags"] = ["existing", "keep"]
    controller._existing.replace(["existing", "keep"])
    controller._tag_baseline = ["existing", "keep"]
    controller.setSavedTagIncluded("existing", False)
    assert controller.tagMode == "replace"
    assert "keep" in controller.proposedCustomTags
    assert controller.removedCustomTags == ["existing"]
    assert not any(command.kind == "apply" for command in controller.worker.commands)
    controller.setSavedTagIncluded("existing", True)
    assert controller.removedCustomTags == []
    controller.setSavedTagIncluded("existing", False)
    controller.applyChanges()
    payload = controller.worker.commands[-1].payload
    assert payload["tag_mode"] == "replace"
    assert "existing" not in payload["tags"]
    assert "keep" in payload["tags"]


def test_explicit_replace_uses_reviewed_tags_and_merge_restores_saved_tags(controller):
    show_review(controller)
    enable_metadata(controller)
    controller.setTagMode("replace")
    assert set(controller.proposedCustomTags) == set(controller._suggested.values())
    assert controller.removedCustomTags == ["existing"]
    controller.setTagMode("merge")
    assert "existing" in controller.proposedCustomTags
    assert controller.removedCustomTags == []


def test_removing_last_saved_custom_tag_allows_explicit_clear(controller):
    show_review(controller)
    enable_metadata(controller)
    controller._suggested.replace([])
    controller.setSavedTagIncluded("existing", False)
    assert controller.canApply
    controller.applyChanges()
    assert controller.worker.commands[-1].payload["tags"] == []
    assert controller.worker.commands[-1].payload["tag_mode"] == "replace"


def test_tag_replacement_draft_restores_and_skip_discards_it(controller):
    show_review(controller)
    enable_metadata(controller)
    controller.setSavedTagIncluded("existing", False)
    document = controller._journal()
    image = QImage(200, 100, QImage.Format.Format_RGB32)
    controller._display({"record": controller._record, "bytes": b"preview", "image": image}, document)
    assert controller.tagMode == "replace"
    assert controller.removedCustomTags == ["existing"]
    controller.skipImage()
    assert controller.tagMode == "merge"
    assert controller.removedCustomTags == []


def test_replacement_reconciliation_preserves_target(controller):
    show_review(controller)
    enable_metadata(controller)
    controller.setTagMode("replace")
    target = controller.proposedCustomTags
    controller.applyChanges()
    controller._receive("error", controller._token, {"operation": "apply", "message": "timeout"})
    controller.retryLastOperation()
    controller._receive("reconciled", controller._token, {"tags": target, "record": {**controller._record, "free_tags": target}})
    assert controller.proposedCustomTags == target
    assert controller.canApply
    controller.applyChanges()
    assert controller.worker.commands[-1].payload["tag_baseline"] == target


def test_removing_saved_tag_also_removes_case_variant_suggestion_not_embedded_tag(controller):
    show_review(controller)
    enable_metadata(controller)
    controller.addTag("EXISTING")
    controller._record["metadata"] = {"XMP-dc:Subject": ["existing"]}
    controller.setSavedTagIncluded("existing", False)
    assert "EXISTING" not in controller._suggested.values()
    assert "existing" not in controller.proposedCustomTags
    assert "existing" in controller.proposedTags
    assert controller.removedCustomTags == ["existing"]


@pytest.mark.parametrize("previous_ignore", [False, True])
def test_replace_all_keeps_embedded_exclusions_independent(controller, previous_ignore):
    show_review(controller)
    enable_metadata(controller)
    controller._record["metadata"] = {"XMP-dc:Subject": ["embedded only"]}
    controller.setDescription("Keep description")
    controller.setEmbeddedTagIncluded("private", False)
    controller.setIgnoreAllEmbeddedTags(previous_ignore)
    controller.setTagMode("replace_all")
    assert controller.tagMode == "replace_all"
    assert controller.ignoreAllEmbeddedTags is previous_ignore
    assert "existing" not in controller.proposedCustomTags
    assert ("embedded only" not in controller.proposedTags) is previous_ignore
    assert controller.currentDescription == "Keep description"
    assert not controller.ignoreEmbeddedDescription
    assert controller._metadata_draft["excluded_embedded_tags"] == ["private"]
    assert not any(command.kind == "apply" for command in controller.worker.commands)
    controller.setTagMode("replace")
    assert controller.ignoreAllEmbeddedTags is previous_ignore
    controller.setTagMode("replace_all")
    controller.applyChanges()
    command = controller.worker.commands[-1]
    assert command.payload["tag_mode"] == "replace"
    assert command.payload["metadata_draft"]["exclude_all_embedded_tags"] is previous_ignore
    assert command.payload["journal"]["tag_mode"] == "replace_all"


def test_replace_all_restore_and_embedded_toggles_are_independent(controller):
    show_review(controller)
    enable_metadata(controller)
    controller.setTagMode("replace_all")
    document = controller._journal()
    document["replace_all_previous_ignore"] = True
    image = QImage(200, 100, QImage.Format.Format_RGB32)
    controller._display({"record": controller._record, "bytes": b"preview", "image": image}, document)
    assert controller.tagMode == "replace_all"
    assert not controller.ignoreAllEmbeddedTags
    controller.setSavedTagIncluded("existing", True)
    assert controller.tagMode == "replace_all"
    controller.setTagMode("merge")
    assert not controller.ignoreAllEmbeddedTags
    controller.setTagMode("replace_all")
    controller.setIgnoreAllEmbeddedTags(True)
    assert controller.tagMode == "replace_all"
    controller.setIgnoreAllEmbeddedTags(False)
    assert controller.tagMode == "replace_all"
    assert not controller.ignoreAllEmbeddedTags
    controller.setIgnoreAllEmbeddedTags(True)
    controller.setTagMode("merge")
    assert controller.ignoreAllEmbeddedTags


def test_replace_all_does_not_require_embedded_exclusion_capability(controller):
    show_review(controller)
    controller._update(tagReplaceAvailable=True)
    controller.setTagMode("replace_all")
    assert controller.tagMode == "replace_all"
    assert not controller.ignoreAllEmbeddedTags
    assert controller.canApply


def test_clear_suggested_tags_is_local_and_restores_empty_draft(controller):
    show_review(controller)
    enable_metadata(controller)
    controller.setDescription("Keep description")
    controller.setIgnoreEmbeddedDescription(True)
    assert controller.canClearSuggestedTags
    controller.clearSuggestedTags()
    assert controller._suggested.values() == []
    assert controller._existing.values() == ["existing"]
    assert controller.tagMode == "merge"
    assert controller.currentDescription == "Keep description"
    assert controller.ignoreEmbeddedDescription
    assert not controller.canClearSuggestedTags
    assert not any(command.kind == "apply" for command in controller.worker.commands)
    document = controller._journal()
    image = QImage(200, 100, QImage.Format.Format_RGB32)
    controller._display({"record": controller._record, "bytes": b"preview", "image": image}, document)
    QTest.qWait(1)
    assert controller._suggested.values() == []
    assert not any(command.kind == "analyze" for command in controller.worker.commands)


@pytest.mark.parametrize("blocked", ["busy", "uncertain", "empty", "no-image"])
def test_clear_suggested_tags_guards(controller, blocked):
    show_review(controller)
    if blocked == "busy":
        controller._state(State.ANALYZING)
    elif blocked == "uncertain":
        controller._uncertain = True
    elif blocked == "empty":
        controller._suggested.replace([])
    else:
        controller._record = None
    before = controller._suggested.values()
    assert not controller.canClearSuggestedTags
    controller.clearSuggestedTags()
    assert controller._suggested.values() == before