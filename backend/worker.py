import asyncio
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from threading import Lock

import httpx
from PySide6.QtCore import QThread, Signal

from .config import Config
from .mcp_client import McpClient
from .metadata_model import metadata_matches, metadata_operations, metadata_values, normalize_description
from .ollama_client import OllamaClient
from .state_manager import StateManager


@dataclass(frozen=True)
class Command:
    kind: str
    token: int
    payload: dict = field(default_factory=dict)


def error_text(error: BaseException) -> str:
    if isinstance(error, BaseExceptionGroup):
        return "; ".join(error_text(item) for item in error.exceptions)
    if isinstance(error, httpx.TimeoutException):
        return "The service request timed out. Your image and draft were preserved. Check Ollama's loaded models and available memory, then retry."
    return str(error) or type(error).__name__


def select_startup_set(sets: list[dict], preferred: str = "", saved: dict | None = None) -> dict:
    if saved:
        matches = [item for item in sets if item["id"] == saved["set_id"] and item["name"] == saved["set_name"]]
        if len(matches) != 1:
            raise ValueError("Saved image set changed. Reset local progress in Settings before continuing.")
        return matches[0]
    if preferred:
        matches = [item for item in sets if item["name"] == preferred]
        if len(matches) != 1:
            raise ValueError("The configured initial image set is missing or ambiguous.")
        return matches[0]
    if not sets:
        raise ValueError("No image sets are available. Create an image set in Exif Turbo first.")
    return sets[0]


class Worker(QThread):
    result = Signal(str, int, object)

    def __init__(self, config: Config, data_directory: str, parent=None) -> None:
        super().__init__(parent)
        self.config = config
        self.data_directory = data_directory
        self._loop = None
        self._queue = None
        self._task = None
        self._initial: list[Command] = []
        self._stopping = False
        self._startup_lock = Lock()
        self._analysis_task: asyncio.Task | None = None
        self._analysis_token: int | None = None
        self._pending_analysis: Command | None = None

    def submit(self, command: Command) -> None:
        with self._startup_lock:
            if self._stopping:
                return
            if self._loop is None:
                self._initial.append(command)
            else:
                self._loop.call_soon_threadsafe(self._queue.put_nowait, command)

    def stop(self) -> None:
        self._stopping = True
        if self._loop is not None and self._task is not None:
            self._loop.call_soon_threadsafe(self._task.cancel)

    def run(self) -> None:
        try:
            asyncio.run(self._run())
        except asyncio.CancelledError:
            pass

    def _start_analysis(self, command: Command, ollama: OllamaClient) -> None:
        self._analysis_token = command.token
        self._analysis_task = asyncio.create_task(self._analyze(command, ollama))

    async def _analyze(self, command: Command, ollama: OllamaClient) -> None:
        try:
            health = await ollama.health()
            self.result.emit("health", command.token, health)
            if not health["ready"]:
                raise RuntimeError(health["message"])
            analysis = await ollama.analyze(command.payload["bytes"])
            self.result.emit("analyzed", command.token, {**analysis.model_dump(), "description_only": command.payload.get("description_only", False)})
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.result.emit("error", command.token, {"operation": "analyze", "message": error_text(error)})
        finally:
            self._queue.put_nowait(Command("analysis_finished", command.token))

    async def _cancel_analysis(self) -> None:
        self._pending_analysis = None
        if self._analysis_task is not None:
            self._analysis_task.cancel()
            await asyncio.gather(self._analysis_task, return_exceptions=True)
        self._analysis_task = None
        self._analysis_token = None

    async def _read_target(self, client, payload: dict) -> dict:
        if payload.get("selected_image"):
            record = (await client.fetch_selected_image(False))["record"]
        else:
            record, _ = await client.fetch_record(payload["set_id"], payload["offset"], False)
        if record is None or record["id"] != payload["record"]["id"] or record["path"] != payload["record"]["path"]:
            raise ValueError("Selected target changed. Refusing to write to an unverified image.")
        return record

    async def _apply_review(self, client, payload: dict, journal: StateManager) -> dict:
        document = {**payload["journal"], "status": "uncertain", "confirmed_operations": []}
        journal.save(document)
        record = await self._read_target(client, payload)
        baseline = payload.get("baseline", metadata_values(record))
        draft = payload.get("metadata_draft", metadata_values(record))
        draft = {**draft, "description": normalize_description(draft["description"])}
        current = metadata_values(record)
        for key in draft:
            if draft[key] != baseline[key] and current[key] != baseline[key]:
                raise ValueError("Saved metadata changed outside this review. Reconcile before applying again.")
        desired = {key: draft[key] if draft[key] != baseline[key] else current[key] for key in draft}
        operations = metadata_operations(current, desired)
        existing = {tag.casefold() for tag in record.get("free_tags", [])}
        replace_tags = payload.get("tag_mode", "merge") == "replace"
        expected_tags = {tag.casefold() for tag in payload["tags"]}
        baseline_tags = {tag.casefold() for tag in payload.get("tag_baseline", record.get("free_tags", []))}
        if replace_tags and existing != baseline_tags and existing != expected_tags:
            raise ValueError("Saved custom tags changed outside this review. Reconcile before replacing them.")
        tags = payload["tags"] if replace_tags else [tag for tag in payload["tags"] if tag.casefold() not in existing]
        write_tags = existing != expected_tags if replace_tags else bool(tags)
        for name, arguments in operations:
            if not client.metadata_capabilities.get(name, False):
                raise ValueError(f"Required MCP capability is unavailable: {name}")
            client.validate_call(name, {"image_id": record["id"], "path": record["path"], **arguments})
        if write_tags and not (getattr(client, "can_replace_tags", False) if replace_tags else client.can_write):
            raise ValueError("No identity-addressed tag-writing capability is available.")
        if write_tags:
            client.validate_call("set_custom_tags_batch", {"updates": [{"image_id": record["id"], "path": record["path"], "tags": tags, "mode": "replace" if replace_tags else "append"}]})
            record = await self._read_target(client, payload)
            if replace_tags:
                fresh_tags = {tag.casefold() for tag in record.get("free_tags", [])}
                if fresh_tags != existing:
                    raise ValueError("Saved custom tags changed while applying. Reconcile before replacing them.")
                await client.apply_tags(record, tags, "replace")
            else:
                await client.apply_tags(record, tags)
            document["confirmed_operations"].append("tags")
            journal.save(document)
        for name, arguments in operations:
            record = await self._read_target(client, payload)
            await client.apply_metadata(record, name, arguments)
            document["confirmed_operations"].append({"tool": name, "arguments": arguments})
            journal.save(document)
        record = await self._read_target(client, payload)
        saved_tags = {tag.casefold() for tag in record.get("free_tags", [])}
        tags_confirmed = saved_tags == expected_tags if replace_tags else expected_tags <= saved_tags
        if not tags_confirmed or not metadata_matches(metadata_values(record), desired):
            raise RuntimeError("MCP readback did not confirm all changes. Reconcile before retrying.")
        journal.save({**document, "status": "applied", "baseline": metadata_values(record), "metadata_draft": metadata_values(record)})
        return record

    async def _run(self) -> None:
        self._queue = asyncio.Queue()
        self._task = asyncio.current_task()
        with self._startup_lock:
            for command in self._initial:
                self._queue.put_nowait(command)
            self._initial = []
            self._loop = asyncio.get_running_loop()
        journal = StateManager(self.data_directory)
        stack = AsyncExitStack()
        client = None
        ollama = OllamaClient(self.config)
        try:
            while not self._stopping:
                command = await self._queue.get()
                try:
                    if command.kind == "analysis_finished":
                        if command.token == self._analysis_token:
                            self._analysis_task = None
                            self._analysis_token = None
                            if self._pending_analysis is not None:
                                pending = self._pending_analysis
                                self._pending_analysis = None
                                self._start_analysis(pending, ollama)
                        continue
                    if command.kind not in {"save", "analyze"}:
                        self._pending_analysis = None
                    if command.kind == "save":
                        journal.save(command.payload)
                        continue
                    if command.kind == "connect":
                        await self._cancel_analysis()
                        await stack.aclose()
                        stack = AsyncExitStack()
                        client = None
                        await ollama.close()
                        self.config = command.payload.get("config", self.config)
                        ollama = OllamaClient(self.config)
                        try:
                            health = await ollama.health()
                        except Exception as error:
                            health = {"connected": False, "ready": False, "message": error_text(error)}
                        self.result.emit("health", command.token, health)
                        for attempt in range(3):
                            try:
                                client = await stack.enter_async_context(McpClient.open(self.config))
                                break
                            except Exception:
                                await stack.aclose()
                                stack = AsyncExitStack()
                                if attempt == 2:
                                    raise
                                await asyncio.sleep(0.5 * 2 ** attempt)
                        sets = await client.list_sets()
                        saved = journal.restore(self.config.mcp_url)
                        selected_image = bool(saved and saved.get("selected_image"))
                        if selected_image:
                            selected = {"id": 0, "name": "Current selected image", "member_count": 1}
                            offset = 0
                            image = await client.load_selected_image()
                        else:
                            selected = select_startup_set(sets, self.config.default_set, saved)
                            offset = saved["offset"] if saved else 0
                            image = await client.load_image(selected["id"], offset)
                        if saved:
                            if image is None or image["record"]["id"] != saved["image_id"] or image["record"]["path"] != saved["path"]:
                                raise ValueError("Saved image identity no longer matches the selected target. Reset local progress in Settings.")
                        self.result.emit("connected", command.token, {
                            "sets": sets, "selected": selected, "offset": offset, "loaded": image,
                            "review": saved, "can_write": client.can_write,
                            "can_replace_tags": getattr(client, "can_replace_tags", False),
                            "metadata_capabilities": getattr(client, "metadata_capabilities", {}),
                            "selected_image": selected_image,
                            "can_read_selected_image": getattr(client, "can_read_selected_image", False),
                            "tools": {name: tool.input_schema for name, tool in client.tools.items()},
                        })
                    elif command.kind == "reset":
                        await self._cancel_analysis()
                        with journal.connection:
                            journal.connection.execute("DELETE FROM progress WHERE endpoint=?", (self.config.mcp_url,))
                            journal.connection.execute("DELETE FROM reviews")
                        self.result.emit("reset", command.token, {})
                    elif command.kind == "load":
                        if client is None:
                            raise ConnectionError("Reconnect MCP before loading images.")
                        if command.payload.get("selected_image"):
                            loaded = await client.load_selected_image()
                            set_id = 0
                        else:
                            loaded = await client.load_image(command.payload["set_id"], command.payload["offset"])
                            set_id = command.payload["set_id"]
                        saved = journal.review(self.config.mcp_url, set_id, loaded["record"]) if loaded else None
                        self.result.emit("loaded", command.token, {"loaded": loaded, "review": saved})
                    elif command.kind == "analyze":
                        if self._analysis_task is None:
                            self._start_analysis(command, ollama)
                        else:
                            self._pending_analysis = command
                    elif command.kind in {"apply", "reconcile"}:
                        if client is None:
                            raise ConnectionError("Reconnect MCP before writing tags.")
                        payload = command.payload
                        if command.kind == "reconcile":
                            record = await self._read_target(client, payload)
                            self.result.emit("reconciled", command.token, {"tags": record.get("free_tags", []), "record": record})
                        else:
                            record = await self._apply_review(client, payload, journal)
                            self.result.emit("applied", command.token, {"tags": record.get("free_tags", []), "record": record})
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    self.result.emit("error", command.token, {"operation": command.kind, "message": error_text(error)})
        finally:
            try:
                await self._cancel_analysis()
                while not self._queue.empty():
                    pending = self._queue.get_nowait()
                    if pending.kind == "save":
                        journal.save(pending.payload)
            finally:
                try:
                    await stack.aclose()
                finally:
                    await ollama.close()
                    journal.close()
                    self._loop = None