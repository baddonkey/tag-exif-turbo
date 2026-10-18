import json
from dataclasses import replace

from PySide6.QtCore import QObject, Property, QSettings, QStandardPaths, QTimer, Qt, Signal, Slot

from .config import Config
from .image_model import ImageModel
from .image_provider import ImageProvider
from .metadata_model import (
    embedded_description, embedded_tags, included_tags, merge_tags, metadata_operations,
    metadata_values, normalize_description, proposed_description,
)
from .tag_model import TagModel
from .worker import Command, Worker
from .workflow import State, Workflow

CURRENT_IMAGE_LABEL = "Current selected image"


def exposed(name: str, kind, default, notify):
    return Property(kind, lambda self: self._values.get(name, default), notify=notify)


class AppController(QObject):
    changed = Signal()
    approvalRequested = Signal()
    quitApproved = Signal()

    mcpConnected = exposed("mcpConnected", bool, False, changed)
    ollamaConnected = exposed("ollamaConnected", bool, False, changed)
    modelReady = exposed("modelReady", bool, False, changed)
    imageSets = exposed("imageSets", "QStringList", [], changed)
    selectedImageSet = exposed("selectedImageSet", str, "", changed)
    currentImageUrl = exposed("currentImageUrl", str, "", changed)
    currentFilename = exposed("currentFilename", str, "", changed)
    currentOffset = exposed("currentOffset", int, 0, changed)
    totalImages = exposed("totalImages", int, 0, changed)
    busy = exposed("busy", bool, False, changed)
    statusMessage = exposed("statusMessage", str, "", changed)
    errorMessage = exposed("errorMessage", str, "", changed)
    workflowState = exposed("workflowState", str, "DISCONNECTED", changed)
    currentDimensions = exposed("currentDimensions", str, "", changed)
    previewDimensions = exposed("previewDimensions", str, "", changed)
    currentMetadata = exposed("currentMetadata", str, "", changed)
    modelStatus = exposed("modelStatus", str, "Not checked", changed)
    tagWriteAvailable = exposed("tagWriteAvailable", bool, False, changed)
    tagReplaceAvailable = exposed("tagReplaceAvailable", bool, False, changed)
    discoveredTools = exposed("discoveredTools", str, "", changed)
    darkTheme = exposed("darkTheme", bool, True, changed)
    windowWidth = exposed("windowWidth", int, 1280, changed)
    windowHeight = exposed("windowHeight", int, 820, changed)
    splitRatio = exposed("splitRatio", float, 0.65, changed)
    descriptionSuggestion = exposed("descriptionSuggestion", str, "", changed)
    descriptionWriteAvailable = exposed("descriptionWriteAvailable", bool, False, changed)
    descriptionExclusionAvailable = exposed("descriptionExclusionAvailable", bool, False, changed)
    tagExclusionAvailable = exposed("tagExclusionAvailable", bool, False, changed)
    allTagsExclusionAvailable = exposed("allTagsExclusionAvailable", bool, False, changed)

    def __init__(self, config: Config, provider: ImageProvider, parent=None) -> None:
        super().__init__(parent)
        self.config = config
        self.provider = provider
        self.settings = QSettings()
        self.flow = Workflow()
        self._values = {
            "statusMessage": "Connect to Exif Turbo and Ollama to begin",
            "windowWidth": self.settings.value("windowWidth", 1280, int),
            "windowHeight": self.settings.value("windowHeight", 820, int),
            "splitRatio": self.settings.value("splitRatio", 0.65, float),
            "darkTheme": self.settings.value("darkTheme", True, bool),
        }
        self._existing = TagModel(self)
        self._suggested = TagModel(self)
        self._images = ImageModel(self)
        self._sets: list[dict] = []
        self._selected = None
        self._selected_mode = False
        self._can_read_selected_image = False
        self._record = None
        self._tag_mode = "merge"
        self._tag_baseline = []
        self._saved_tag_draft = []
        self._baseline = metadata_values({})
        self._metadata_draft = metadata_values({})
        self._description_touched = False
        self._analysis_description_only = False
        self._metadata_capabilities = {}
        self._bytes = b""
        self._token = 0
        self._offset = 0
        self._target = None
        self._last_operation = "connect"
        self._uncertain = False
        self._closed = False
        self._draft_timer = QTimer(self)
        self._draft_timer.setInterval(200)
        self._draft_timer.setSingleShot(True)
        self._draft_timer.timeout.connect(self._save_draft)
        directory = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
        self.worker = Worker(config, directory, self)
        self.worker.result.connect(self._receive, Qt.ConnectionType.QueuedConnection)
        self.worker.start()

    def _update(self, **values) -> None:
        self._values.update(values)
        self.changed.emit()

    def _state(self, state: State, message: str = "") -> None:
        self.flow.transition(state)
        self._update(workflowState=state.value, busy=self.flow.busy, statusMessage=message or self.statusMessage)

    def _submit(self, kind: str, payload=None) -> None:
        self._token += 1
        self._last_operation = kind
        self.worker.submit(Command(kind, self._token, payload or {}))

    @Property(QObject, constant=True)
    def existingTags(self):
        return self._existing

    @Property(QObject, constant=True)
    def suggestedTags(self):
        return self._suggested

    @Property(QObject, constant=True)
    def imageModel(self):
        return self._images

    @Property(bool, notify=changed)
    def canApply(self) -> bool:
        if not (self._record and type(self._record.get("id")) is int and self._record["id"] > 0 and not self.busy and self.flow.unresolved and self.mcpConnected and not self._uncertain):
            return False
        existing = {tag.casefold() for tag in self._existing.values()}
        proposed = {tag.casefold() for tag in self.proposedCustomTags}
        needs_tags = proposed != existing if self._tag_mode != "merge" else bool(proposed - existing)
        operations = metadata_operations(self._baseline, self._metadata_draft)
        return bool((self._suggested.rowCount() or needs_tags or operations or self._tag_mode != "merge" or self._values.get("reconciledReview", False))
                and (not needs_tags or (self.tagReplaceAvailable if self._tag_mode != "merge" else self.tagWriteAvailable))
                    and all(self._metadata_capabilities.get(name, False) for name, _ in operations))

    @Property(bool, notify=changed)
    def canAnalyze(self) -> bool:
        return bool(self._bytes and self.ollamaConnected and self.modelReady and not self.busy and not self._uncertain)

    @Property(bool, notify=changed)
    def canPrevious(self) -> bool:
        return bool(self._record and self.mcpConnected and (not self.busy or self.flow.state == State.ANALYZING) and self.currentOffset > 0 and not self._uncertain)

    @Property(bool, notify=changed)
    def canNext(self) -> bool:
        return bool(self._record and self.mcpConnected and (not self.busy or self.flow.state == State.ANALYZING) and self.currentOffset + 1 < self.totalImages and not self._uncertain)

    @Property(bool, notify=changed)
    def canSkip(self) -> bool:
        return bool(self._record and not self.busy and not self._uncertain)

    @Property(bool, notify=changed)
    def canClearSuggestedTags(self) -> bool:
        return bool(self.canSkip and self._suggested.rowCount())

    @Property(bool, notify=changed)
    def canReloadCurrentImage(self) -> bool:
        return bool(self._selected_mode and self.mcpConnected and self._can_read_selected_image and not self.busy and not self._uncertain)

    @Property(str, notify=changed)
    def currentDescription(self) -> str:
        return self._metadata_draft["description"] if self._record else ""

    @Property(str, notify=changed)
    def embeddedDescription(self) -> str:
        return embedded_description(self._record.get("metadata") or {}) if self._record else ""

    @Property(bool, notify=changed)
    def ignoreEmbeddedDescription(self) -> bool:
        return self._metadata_draft["exclude_embedded_description"]

    @Property(bool, notify=changed)
    def ignoreAllEmbeddedTags(self) -> bool:
        return self._metadata_draft["exclude_all_embedded_tags"]

    @Property("QVariantList", notify=changed)
    def embeddedTagRows(self) -> list[dict]:
        if not self._record:
            return []
        excluded = {tag.casefold() for tag in self._metadata_draft["excluded_embedded_tags"]}
        return [{"label": tag, "included": not self.ignoreAllEmbeddedTags and tag.casefold() not in excluded}
                for tag in embedded_tags(self._record.get("metadata") or {})]

    @Property(str, notify=changed)
    def proposedDescription(self) -> str:
        return proposed_description(self._record.get("metadata") or {}, self._metadata_draft) if self._record else ""

    @Property("QStringList", notify=changed)
    def proposedCustomTags(self) -> list[str]:
        return merge_tags(self._saved_tag_draft if self._tag_mode != "merge" else self._existing.values(), self._suggested.values())

    @Property(str, notify=changed)
    def tagMode(self) -> str:
        return self._tag_mode

    @Property("QStringList", notify=changed)
    def removedCustomTags(self) -> list[str]:
        proposed = {tag.casefold() for tag in self.proposedCustomTags}
        return [tag for tag in self._existing.values() if tag.casefold() not in proposed]

    @Property("QVariantList", notify=changed)
    def savedTagRows(self) -> list[dict]:
        proposed = {tag.casefold() for tag in self.proposedCustomTags}
        return [{"label": tag, "included": tag.casefold() in proposed} for tag in self._existing.values()]

    @Slot(str)
    def setTagMode(self, mode: str) -> None:
        if mode not in {"merge", "replace", "replace_all"} or mode == self._tag_mode or not self.canSkip:
            return
        if mode != "merge" and not self.tagReplaceAvailable:
            return
        was_replacing = self._tag_mode != "merge"
        self._tag_mode = mode
        if mode == "merge":
            self._saved_tag_draft = self._existing.values()
        elif not was_replacing:
            self._saved_tag_draft = []
        self._edited()

    @Slot(str, bool)
    def setSavedTagIncluded(self, tag: str, included: bool) -> None:
        if not self.canSkip or not self.tagReplaceAvailable:
            return
        label = next((value for value in self._existing.values() if value.casefold() == tag.casefold()), None)
        if label is None:
            return
        retained = self._existing.values() if self._tag_mode == "merge" else self._saved_tag_draft
        if self._tag_mode == "merge":
            self._tag_mode = "replace"
        self._saved_tag_draft = [value for value in retained if value.casefold() != label.casefold()]
        if included:
            self._saved_tag_draft = merge_tags(self._saved_tag_draft, [label])
        else:
            for suggested in self._suggested.values():
                if suggested.casefold() == label.casefold():
                    self._suggested.remove(suggested)
        self._edited()

    @Property("QStringList", notify=changed)
    def proposedTags(self) -> list[str]:
        return merge_tags(self.proposedCustomTags, included_tags(self._record.get("metadata") or {}, self._metadata_draft)) if self._record else []

    @Property(bool, notify=changed)
    def descriptionWillClear(self) -> bool:
        return bool(self._baseline["description"] and not normalize_description(self.currentDescription))

    @Slot(str)
    def setDescription(self, text: str) -> None:
        if self.busy or self._uncertain or not self._record or not self.descriptionWriteAvailable:
            return
        try:
            normalize_description(text)
        except ValueError as error:
            self._update(errorMessage=str(error))
            return
        self._description_touched = True
        self._metadata_draft = {**self._metadata_draft, "description": text}
        self._edited()

    @Slot(bool)
    def useDescriptionSuggestion(self, append: bool) -> None:
        text = self.descriptionSuggestion
        if text:
            self.setDescription("\n\n".join(part for part in (self.currentDescription, text) if part) if append else text)

    @Slot(bool)
    def setIgnoreEmbeddedDescription(self, excluded: bool) -> None:
        self._set_exclusion("exclude_embedded_description", excluded, self.descriptionExclusionAvailable)

    @Slot(bool)
    def setIgnoreAllEmbeddedTags(self, excluded: bool) -> None:
        self._set_exclusion("exclude_all_embedded_tags", excluded, self.allTagsExclusionAvailable)

    def _set_exclusion(self, field: str, value, available: bool) -> None:
        if self._record and available and not self.busy and not self._uncertain:
            self._metadata_draft = {**self._metadata_draft, field: value}
            self._edited()

    @Slot(str, bool)
    def setEmbeddedTagIncluded(self, tag: str, included: bool) -> None:
        if self.ignoreAllEmbeddedTags:
            return
        tags = [value for value in self._metadata_draft["excluded_embedded_tags"] if value.casefold() != tag.casefold()]
        if not included:
            tags.append(tag)
        self._set_exclusion("excluded_embedded_tags", tags, self.tagExclusionAvailable)

    def _discard_metadata(self) -> None:
        self._tag_mode = "merge"
        self._tag_baseline = self._existing.values()
        self._saved_tag_draft = self._existing.values()
        self._metadata_draft = metadata_values(self._record or {})
        self._baseline = metadata_values(self._record or {})
        self._description_touched = False
        self._update(descriptionSuggestion="", analysisNeeded=False)

    @Property(str, notify=changed)
    def modelName(self) -> str:
        return self.config.model

    @Property(str, notify=changed)
    def mcpUrl(self) -> str:
        return self.config.mcp_url

    @Property(str, notify=changed)
    def ollamaUrl(self) -> str:
        return self.config.ollama_url

    @Slot()
    def connectServices(self) -> None:
        if self.busy:
            return
        if self.flow.unresolved and not self._uncertain:
            self._save_draft()
        self._update(busy=True, errorMessage="", statusMessage="Connecting to services…")
        self._submit("connect", {"config": self.config})

    def _journal(self, status: str = "pending") -> dict:
        return {
            "endpoint": self.config.mcp_url, "set_id": self._selected["id"],
            "set_name": self._selected["name"], "offset": self.currentOffset,
            "image_id": self._record["id"], "path": self._record["path"],
            "selected_image": self._selected_mode,
            "tags": self._suggested.values(), "status": status,
            "tag_mode": self._tag_mode, "tag_baseline": self._tag_baseline,
            "saved_tag_draft": self._saved_tag_draft, "tag_target": self.proposedCustomTags,
            "analysis_pending": self.flow.state == State.ANALYZING or self._values.get("analysisNeeded", False),
            "analysis_description_only": self._analysis_description_only,
            "baseline": self._baseline, "metadata_draft": self._metadata_draft,
            "description_touched": self._description_touched,
            "description_suggestion": self.descriptionSuggestion,
        }

    @Slot()
    def _save_draft(self) -> None:
        self._draft_timer.stop()
        if self._record and self._selected:
            status = "uncertain" if self._uncertain else "pending" if self.flow.unresolved else self._values.get("reviewStatus", "pending")
            self.worker.submit(Command("save", self._token, self._journal(status)))

    @Slot(str)
    def selectImageSet(self, name: str) -> None:
        selected = next((item for item in self._sets if item["name"] == name), None)
        if selected and (self._selected is None or selected["id"] != self._selected["id"]):
            self._navigate(("set", selected))

    @Slot()
    def selectCurrentImage(self) -> None:
        if not self._can_read_selected_image:
            self._update(errorMessage="The connected Exif Turbo server does not expose get_selected_image.")
            return
        self._navigate(("selected", None))

    @Slot()
    def reloadCurrentImage(self) -> None:
        if self.canReloadCurrentImage:
            self.selectCurrentImage()

    @Slot(int)
    def loadImage(self, offset: int) -> None:
        if self._selected and 0 <= offset < self.totalImages:
            self._navigate(("load", offset))

    def _navigate(self, target) -> None:
        leave_analysis = self.flow.state == State.ANALYZING and target[0] == "load"
        if (self.busy and not leave_analysis) or self._uncertain:
            return
        if leave_analysis:
            self._save_draft()
            self._token += 1
            self.flow.unresolved = False
        elif self.flow.unresolved:
            self._target = target
            self.approvalRequested.emit()
            return
        self._execute_target(target)

    def _execute_target(self, target) -> None:
        self._target = None
        if target[0] == "quit":
            self.quitApproved.emit()
            return
        if target[0] == "configure":
            self._save_draft()
            self.config = target[1]
            self._record = None
            self._bytes = b""
            self._existing.replace([])
            self._suggested.replace([])
            for key, value in {"mcpUrl": self.config.mcp_url, "ollamaUrl": self.config.ollama_url, "modelName": self.config.model}.items():
                self.settings.setValue(key, value)
            self._update(currentImageUrl="", currentFilename="", currentMetadata="", currentDimensions="", totalImages=0, mcpConnected=False, ollamaConnected=False, modelReady=False)
            self.connectServices()
            return
        if target[0] == "set":
            self._selected = target[1]
            self._selected_mode = False
            self._update(selectedImageSet=self._selected["name"], totalImages=self._selected["member_count"])
            offset = 0
        elif target[0] == "selected":
            self._selected = {"id": 0, "name": CURRENT_IMAGE_LABEL, "member_count": 1}
            self._selected_mode = True
            self._update(selectedImageSet=CURRENT_IMAGE_LABEL, totalImages=1)
            offset = 0
        else:
            offset = target[1]
        if not self._selected or not self.totalImages:
            self._record = None
            self._bytes = b""
            self._existing.replace([])
            self._suggested.replace([])
            self._update(currentImageUrl="", currentFilename="", currentMetadata="", currentDimensions="")
            self._state(State.COMPLETED, "This image set is empty")
            return
        self._offset = offset
        self._state(State.LOADING_IMAGE, "Loading image preview…")
        self._update(errorMessage="")
        self._submit("load", {
            "set_id": self._selected["id"], "offset": offset,
            "selected_image": self._selected_mode,
        })

    @Slot(str)
    def resolveApproval(self, decision: str) -> None:
        if decision == "cancel":
            self._target = None
            self.changed.emit()
        elif decision == "apply":
            self.applyTags()
        elif decision == "skip" and self.canSkip:
            self._discard_metadata()
            self.flow.resolve("skipped")
            self._update(reviewStatus="skipped")
            self._save_draft()
            target = self._target
            if target:
                self._execute_target(target)

    @Slot()
    def nextImage(self) -> None:
        if self.canNext:
            self.loadImage(self.currentOffset + 1)

    @Slot()
    def previousImage(self) -> None:
        if self.canPrevious:
            self.loadImage(self.currentOffset - 1)

    @Slot()
    def skipImage(self) -> None:
        if self.canSkip:
            self._discard_metadata()
            self.flow.resolve("skipped")
            self._update(reviewStatus="skipped", errorMessage="")
            self._save_draft()
            self._advance()

    def _advance(self) -> None:
        if self._target:
            self._execute_target(self._target)
        elif self.currentOffset + 1 < self.totalImages:
            self._execute_target(("load", self.currentOffset + 1))
        elif self._selected_mode:
            self._state(State.COMPLETED, "Selected image complete")
        else:
            self._state(State.COMPLETED, "Image set complete")

    @Slot()
    def analyzeCurrentImage(self) -> None:
        self._analyze(False)

    @Slot()
    def generateDescriptionSuggestion(self) -> None:
        self._analyze(True)

    def _analyze(self, description_only: bool) -> None:
        if not self.canAnalyze:
            return
        self._analysis_description_only = description_only
        self.flow.unresolved = True
        self._state(State.ANALYZING, "Analyzing image with Ollama…")
        self._update(errorMessage="")
        self._submit("analyze", {"bytes": self._bytes, "description_only": description_only})

    @Slot()
    def regenerateTags(self) -> None:
        self.analyzeCurrentImage()

    @Slot(str)
    def addTag(self, tag: str) -> None:
        if self.busy or not self._record or self._uncertain:
            return
        try:
            if self._suggested.add(tag):
                self._edited()
        except ValueError as error:
            self._update(errorMessage=str(error))

    @Slot(str)
    def removeTag(self, tag: str) -> None:
        if not self.busy and not self._uncertain and self._suggested.remove(tag):
            self._edited()

    @Slot()
    def clearSuggestedTags(self) -> None:
        if self.canClearSuggestedTags:
            self._suggested.replace([])
            self._edited()

    def _edited(self) -> None:
        self.flow.unresolved = True
        self._state(State.AWAITING_APPROVAL, "Review proposed changes")
        self._update(reviewStatus="pending", analysisNeeded=False)
        self._draft_timer.start()

    @Slot()
    def applyChanges(self) -> None:
        self.applyTags()

    @Slot()
    def applyTags(self) -> None:
        if not self.canApply:
            return
        self._draft_timer.stop()
        payload = {
            "set_id": self._selected["id"], "offset": self.currentOffset,
            "selected_image": self._selected_mode,
            "record": {"id": self._record["id"], "path": self._record["path"]},
            "tags": self.proposedCustomTags if self._tag_mode != "merge" else self._suggested.values(), "journal": self._journal("uncertain"),
            "tag_mode": "replace" if self._tag_mode != "merge" else "merge", "tag_baseline": self._tag_baseline,
            "baseline": self._baseline, "metadata_draft": self._metadata_draft,
        }
        self._state(State.APPLYING_TAGS, "Applying approved metadata changes…")
        self._update(errorMessage="")
        self._submit("apply", payload)

    @Slot()
    def retryLastOperation(self) -> None:
        if self.busy:
            return
        if self._uncertain and self._record:
            self._update(busy=True, errorMessage="", statusMessage="Reconciling image metadata; no write will be retried…")
            self._submit("reconcile", {
                "set_id": self._selected["id"], "offset": self.currentOffset,
                "selected_image": self._selected_mode, "record": self._record,
            })
        elif not self.mcpConnected or self._last_operation == "connect":
            self.connectServices()
        elif self._bytes and (not self.ollamaConnected or not self.modelReady):
            self.connectServices()
        elif self._last_operation == "analyze":
            self._analyze(self._analysis_description_only)
        else:
            self._navigate(("load", self._offset))

    @Slot()
    def requestQuit(self) -> None:
        if self.busy:
            self._update(errorMessage="Wait for the current operation to finish before quitting.")
        elif self._uncertain:
            self.quitApproved.emit()
        else:
            self._navigate(("quit", None))

    @Slot(bool, int, int, float)
    def saveUi(self, dark: bool, width: int, height: int, ratio: float) -> None:
        for name, value in {"darkTheme": dark, "windowWidth": width, "windowHeight": height, "splitRatio": max(0.25, min(0.8, ratio))}.items():
            self.settings.setValue(name, value)
        self.settings.sync()

    @Slot(str, str, str, bool)
    def configure(self, mcp_url: str, ollama_url: str, model: str, dark: bool) -> None:
        self.settings.setValue("darkTheme", dark)
        self._update(darkTheme=dark)
        if self.busy or self._uncertain:
            self._update(errorMessage="Finish or reconcile the current operation before changing service settings.")
            return
        try:
            config = replace(self.config, mcp_url=mcp_url.strip(), ollama_url=ollama_url.strip().rstrip("/"), model=model.strip())
        except ValueError as error:
            self._update(errorMessage=str(error))
            return
        if config != self.config:
            self._navigate(("configure", config))

    @Slot()
    def resetProgress(self) -> None:
        if not self.busy:
            self.flow.unresolved = False
            self._uncertain = False
            self._record = None
            self._update(busy=True)
            self._submit("reset")

    def _display(self, loaded: dict | None, review: dict | None) -> None:
        if loaded is None:
            self._record = None
            self._bytes = b""
            self.flow.unresolved = False
            self._update(currentImageUrl="", currentFilename="")
            self._state(State.COMPLETED, "No more images")
            return
        self._record = loaded["record"]
        pending = review and review["status"] in {"pending", "uncertain"}
        self._tag_mode = review.get("tag_mode", "merge") if pending else "merge"
        self._tag_baseline = list(review.get("tag_baseline", self._record.get("free_tags", [])) if pending else self._record.get("free_tags", []))
        self._saved_tag_draft = list(review.get("saved_tag_draft", self._tag_baseline) if pending else self._tag_baseline)
        self._baseline = metadata_values(review.get("baseline", self._record) if pending else self._record)
        self._metadata_draft = metadata_values(review.get("metadata_draft", self._record) if pending else self._record)
        self._description_touched = bool(pending and review.get("description_touched", False))
        self._analysis_description_only = bool(review and review.get("analysis_description_only", False))
        needs_analysis = review is None or review.get("analysis_pending", False) or (review["status"] == "pending" and not review.get("tags") and "metadata_draft" not in review)
        self._update(descriptionSuggestion=review.get("description_suggestion", "") if pending else "", reconciledReview=False, analysisNeeded=needs_analysis)
        self._bytes = loaded["bytes"]
        self._images.show(self._record)
        self._existing.replace(self._record.get("free_tags", []))
        self._suggested.replace(review.get("tags", []) if review else [])
        self._uncertain = bool(review and review["status"] == "uncertain")
        self.flow.unresolved = review is None or review["status"] in {"pending", "uncertain"}
        image = loaded["image"]
        metadata = self._record.get("metadata") or {}
        width = metadata.get("ExifIFD:ExifImageWidth", image.width())
        height = metadata.get("ExifIFD:ExifImageHeight", image.height())
        source = self.provider.store(f"{self._record['id']}/{self._token}", image)
        self._update(
            currentImageUrl=source, currentFilename=self._record["filename"],
            currentOffset=self._offset, currentDimensions=f"{width} × {height}",
            previewDimensions=f"{image.width()} × {image.height()}",
            currentMetadata=json.dumps(metadata, indent=2, ensure_ascii=False),
            reviewStatus=review["status"] if review else "pending", errorMessage="",
        )
        target_state = State.AWAITING_APPROVAL if self.flow.unresolved else State.COMPLETED if self.currentOffset + 1 >= self.totalImages else State.READY
        self._state(target_state, "Review restored" if review else "Preview loaded")
        if self._uncertain:
            self._update(errorMessage="A previous write was interrupted. Retry reconciles metadata without writing.")
        elif needs_analysis:
            self._save_draft()
            if self.canAnalyze:
                QTimer.singleShot(0, self.generateDescriptionSuggestion if self._analysis_description_only else self.analyzeCurrentImage)
            else:
                self._update(
                    statusMessage="Tag suggestions are waiting for Ollama",
                    errorMessage=f"Cannot generate tag suggestions: {self.modelStatus}. Check Ollama and the configured vision model, then Retry.",
                )

    @Slot(str, int, object)
    def _receive(self, kind: str, token: int, payload: dict) -> None:
        if token != self._token or self._closed:
            return
        if kind == "health":
            self._update(ollamaConnected=payload["connected"], modelReady=payload["ready"], modelStatus=payload["message"])
            return
        if kind == "error":
            if payload["operation"] == "apply":
                self._uncertain = True
                self._save_draft()
            if payload["operation"] == "connect":
                self._update(mcpConnected=False)
            self._state(State.ERROR, "Operation failed; your review has been preserved")
            self._update(errorMessage=payload["message"])
            return
        if kind == "connected":
            self._sets = payload["sets"]
            self._selected = payload["selected"]
            self._selected_mode = payload.get("selected_image", False)
            self._can_read_selected_image = payload.get("can_read_selected_image", False)
            self._offset = payload["offset"]
            self.flow.unresolved = False
            self._state(State.READY, "Connected")
            self._update(
                mcpConnected=True,
                imageSets=[item["name"] for item in self._sets],
                selectedImageSet=self._selected["name"],
                totalImages=self._selected["member_count"],
                tagWriteAvailable=payload["can_write"],
                tagReplaceAvailable=payload.get("can_replace_tags", False),
                discoveredTools=json.dumps(payload["tools"], indent=2),
            )
            self._metadata_capabilities = payload.get("metadata_capabilities", {})
            self._update(
                descriptionWriteAvailable=self._metadata_capabilities.get("set_image_description", False),
                descriptionExclusionAvailable=self._metadata_capabilities.get("set_image_description_excluded", False),
                tagExclusionAvailable=self._metadata_capabilities.get("set_image_embedded_tag_excluded", False),
                allTagsExclusionAvailable=self._metadata_capabilities.get("set_image_all_embedded_tags_excluded", False),
            )
            self._display(payload["loaded"], payload["review"])
        elif kind == "loaded":
            self._display(payload["loaded"], payload["review"])
        elif kind == "analyzed":
            if not payload.get("description_only", False):
                self._suggested.replace(payload["tags"])
            suggestion = payload.get("description", "")
            if suggestion and not self.currentDescription and not self._description_touched and self.descriptionWriteAvailable:
                self._metadata_draft = {**self._metadata_draft, "description": suggestion}
            self._update(descriptionSuggestion=suggestion, analysisNeeded=False)
            self.flow.unresolved = True
            self._state(State.AWAITING_APPROVAL, "Review proposed tags and description before applying")
            self._update(reviewStatus="pending")
            self._save_draft()
        elif kind == "applied":
            if "record" in payload:
                self._record = payload["record"]
                self._baseline = metadata_values(self._record)
                self._metadata_draft = metadata_values(self._record)
            self._existing.replace(payload["tags"])
            self._tag_baseline = list(payload["tags"])
            self._saved_tag_draft = list(payload["tags"])
            self._tag_mode = "merge"
            self.flow.resolve("applied")
            self._state(State.READY, "Changes applied")
            self._update(reviewStatus="applied")
            self._advance()
        elif kind == "reconciled":
            if "record" in payload:
                actual = metadata_values(payload["record"])
                self._metadata_draft = {key: value if value != self._baseline[key] else actual[key]
                                        for key, value in self._metadata_draft.items()}
                self._baseline = actual
                self._record = payload["record"]
            self._existing.replace(payload["tags"])
            self._tag_baseline = list(payload["tags"])
            self._uncertain = False
            self._state(State.AWAITING_APPROVAL, "Metadata reread. Some changes may already be saved; review and Apply to finish.")
            self._update(errorMessage="", busy=False, reconciledReview=True)
            self._save_draft()
        elif kind == "reset":
            self._update(busy=False)
            self.connectServices()

    def shutdown(self) -> None:
        if self._closed:
            return
        self._draft_timer.stop()
        if self._record and self.flow.state == State.APPLYING_TAGS:
            self._uncertain = True
        self._save_draft()
        self._closed = True
        self.worker.stop()
        if not self.worker.wait(15000):
            self.worker.wait()
