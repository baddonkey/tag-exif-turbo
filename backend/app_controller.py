import json
from dataclasses import replace

from PySide6.QtCore import QObject, Property, QSettings, QStandardPaths, QTimer, Qt, Signal, Slot

from .config import Config
from .image_model import ImageModel
from .image_provider import ImageProvider
from .tag_model import TagModel
from .worker import Command, Worker
from .workflow import State, Workflow


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
    discoveredTools = exposed("discoveredTools", str, "", changed)
    darkTheme = exposed("darkTheme", bool, True, changed)
    windowWidth = exposed("windowWidth", int, 1280, changed)
    windowHeight = exposed("windowHeight", int, 820, changed)
    splitRatio = exposed("splitRatio", float, 0.65, changed)

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
        self._record = None
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
        return bool(self._record and not self.busy and self.flow.unresolved and self.mcpConnected and self.tagWriteAvailable and self._suggested.rowCount() and not self._uncertain)

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

    @Property(str, constant=True)
    def currentDescription(self) -> str:
        return ""

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
            "tags": self._suggested.values(), "status": status,
            "analysis_pending": self.flow.state == State.ANALYZING,
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
            self._update(selectedImageSet=self._selected["name"], totalImages=self._selected["member_count"])
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
        self._submit("load", {"set_id": self._selected["id"], "offset": offset})

    @Slot(str)
    def resolveApproval(self, decision: str) -> None:
        if decision == "cancel":
            self._target = None
            self.changed.emit()
        elif decision == "apply":
            self.applyTags()
        elif decision == "skip" and self.canSkip:
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
            self.flow.resolve("skipped")
            self._update(reviewStatus="skipped", errorMessage="")
            self._save_draft()
            self._advance()

    def _advance(self) -> None:
        if self._target:
            self._execute_target(self._target)
        elif self.currentOffset + 1 < self.totalImages:
            self._execute_target(("load", self.currentOffset + 1))
        else:
            self._state(State.COMPLETED, "Image set complete")

    @Slot()
    def analyzeCurrentImage(self) -> None:
        if not self.canAnalyze:
            return
        self.flow.unresolved = True
        self._state(State.ANALYZING, "Analyzing image with Ollama…")
        self._update(errorMessage="")
        self._submit("analyze", {"bytes": self._bytes})

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

    def _edited(self) -> None:
        self.flow.unresolved = True
        self._state(State.AWAITING_APPROVAL, "Review suggested tags")
        self._update(reviewStatus="pending")
        self._draft_timer.start()

    @Slot()
    def applyTags(self) -> None:
        if not self.canApply:
            return
        self._draft_timer.stop()
        payload = {
            "set_id": self._selected["id"], "offset": self.currentOffset,
            "record": {"id": self._record["id"], "path": self._record["path"]},
            "tags": self._suggested.values(), "journal": self._journal("uncertain"),
        }
        self._state(State.APPLYING_TAGS, "Applying approved tags…")
        self._update(errorMessage="")
        self._submit("apply", payload)

    @Slot()
    def retryLastOperation(self) -> None:
        if self.busy:
            return
        if self._uncertain and self._record:
            self._update(busy=True, errorMessage="", statusMessage="Reconciling image tags; no write will be retried…")
            self._submit("reconcile", {"set_id": self._selected["id"], "offset": self.currentOffset, "record": self._record})
        elif not self.mcpConnected or self._last_operation == "connect":
            self.connectServices()
        elif self._last_operation == "analyze":
            self.analyzeCurrentImage()
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
            self._update(errorMessage="A previous write was interrupted. Retry reconciles tags without writing.")
        elif review is None or review.get("analysis_pending", False):
            self._save_draft()
            if self.canAnalyze:
                QTimer.singleShot(0, self.analyzeCurrentImage)

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
            self._offset = payload["offset"]
            self.flow.unresolved = False
            self._state(State.READY, "Connected")
            self._update(mcpConnected=True, imageSets=[item["name"] for item in self._sets], selectedImageSet=self._selected["name"], totalImages=self._selected["member_count"], tagWriteAvailable=payload["can_write"], discoveredTools=json.dumps(payload["tools"], indent=2))
            self._display(payload["loaded"], payload["review"])
        elif kind == "loaded":
            self._display(payload["loaded"], payload["review"])
        elif kind == "analyzed":
            self._suggested.replace(payload["tags"])
            self.flow.unresolved = True
            self._state(State.AWAITING_APPROVAL, "Review suggested tags before applying")
            self._update(reviewStatus="pending")
            self._save_draft()
        elif kind == "applied":
            self._existing.replace(payload["tags"])
            self.flow.resolve("applied")
            self._state(State.READY, "Tags applied")
            self._update(reviewStatus="applied")
            self._advance()
        elif kind == "reconciled":
            self._existing.replace(payload["tags"])
            self._uncertain = False
            self._state(State.AWAITING_APPROVAL, "Tags reconciled. Review before explicitly applying again.")
            self._update(errorMessage="", busy=False)
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
