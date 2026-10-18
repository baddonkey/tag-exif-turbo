import asyncio
from contextlib import asynccontextmanager

import pytest

from backend.config import Config
from backend.worker import Command, Worker, error_text
from backend.metadata_model import metadata_values
from backend.state_manager import StateManager
from backend.ollama_client import Analysis, DescriptionRefinement


def test_refinement_deadline_reports_preserved_draft():
    assert "timed out" in error_text(TimeoutError())
    assert "draft were preserved" in error_text(TimeoutError())


@pytest.fixture
def controlled_services(monkeypatch):
    class ControlledOllama:
        def __init__(self, config):
            self.started = asyncio.Queue()
            self.release = asyncio.Event()
            self.cancelled = asyncio.Event()
            self.calls = []
            self.refinement_calls = []
            self.closed = False

        async def health(self):
            return {"connected": True, "ready": True, "message": "Ready"}

        async def analyze(self, image_bytes):
            self.calls.append(image_bytes)
            self.started.put_nowait(image_bytes)
            if image_bytes == b"old":
                try:
                    await self.release.wait()
                except asyncio.CancelledError:
                    self.cancelled.set()
                    raise
            return Analysis(tags=["tree", "grass", "sky", "cloud", "landscape"], description="A tree beneath clouds.")

        async def refine_description(self, image_bytes, sources):
            self.refinement_calls.append((image_bytes, dict(sources)))
            analysis = await self.analyze(image_bytes)
            return DescriptionRefinement(description=analysis.description, review_notes=["Supplied date needs review."])

        async def close(self):
            self.closed = True

    clients = []

    def make_ollama(config):
        client = ControlledOllama(config)
        clients.append(client)
        return client

    class ControlledMcp:
        can_write = False
        tools = {}

        async def list_sets(self):
            return [{"id": 1, "name": "smoke-test", "member_count": 3}]

        async def load_image(self, set_id, offset):
            return {"record": {"id": offset + 1, "path": f"/test-{offset}.jpg"}}

    @asynccontextmanager
    async def open_mcp(config):
        yield ControlledMcp()

    monkeypatch.setattr("backend.worker.OllamaClient", make_ollama)
    monkeypatch.setattr("backend.worker.McpClient.open", open_mcp)
    return clients


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["image", "refine"])
async def test_preview_loads_do_not_wait_for_inference_and_pending_work_is_coalesced(gui, tmp_path, controlled_services, mode):
    worker = Worker(Config(), str(tmp_path))
    events = {("connected", 1): asyncio.Event(), ("loaded", 3): asyncio.Event(), ("loaded", 5): asyncio.Event(), ("analyzed", 6): asyncio.Event()}
    errors = []
    analyses = []

    def receive(kind, token, payload):
        if kind == "error":
            errors.append(payload)
        if kind == "analyzed":
            analyses.append(payload)
        if (kind, token) in events:
            events[(kind, token)].set()

    worker.result.connect(receive)
    worker.submit(Command("connect", 1))
    running = asyncio.create_task(worker._run())
    try:
        await asyncio.wait_for(events[("connected", 1)].wait(), 1)
        client = controlled_services[-1]
        worker.submit(Command("analyze", 2, {"bytes": b"old"}))
        assert await asyncio.wait_for(client.started.get(), 1) == b"old"
        worker.submit(Command("load", 3, {"set_id": 1, "offset": 1}))
        worker.submit(Command("analyze", 4, {"bytes": b"middle"}))
        worker.submit(Command("load", 5, {"set_id": 1, "offset": 2}))
        worker.submit(Command("analyze", 6, {"bytes": b"latest", "description_only": True, "mode": mode, "sources": {"embedded": "Paris, 1962."}}))
        await asyncio.wait_for(events[("loaded", 3)].wait(), 1)
        await asyncio.wait_for(events[("loaded", 5)].wait(), 1)
        assert not client.release.is_set()
        assert client.calls == [b"old"]
        client.release.set()
        await asyncio.wait_for(events[("analyzed", 6)].wait(), 1)
        assert client.calls == [b"old", b"latest"]
        assert analyses[-1]["description"] == "A tree beneath clouds."
        assert analyses[-1]["description_only"]
        if mode == "refine":
            assert analyses[-1]["refinement"]
            assert "tags" not in analyses[-1]
            assert analyses[-1]["context_sources"] == {"embedded": "Paris, 1962."}
            assert analyses[-1]["review_notes"] == ["Supplied date needs review."]
        else:
            assert client.refinement_calls == []
        assert not errors
    finally:
        running.cancel()
        with pytest.raises(asyncio.CancelledError):
            await running
    assert all(client.closed for client in controlled_services)
    assert worker._analysis_task is None


@pytest.mark.asyncio
async def test_refinement_failure_never_falls_back_to_image_analysis(gui, tmp_path):
    class Ollama:
        async def health(self):
            return {"ready": True}

        async def refine_description(self, image_bytes, sources):
            raise RuntimeError("Refinement unavailable")

        async def analyze(self, image_bytes):
            pytest.fail("Refinement must not fall back to image-only generation")

    worker = Worker(Config(), str(tmp_path))
    worker._queue = asyncio.Queue()
    events = []
    worker.result.connect(lambda kind, token, payload: events.append((kind, token, payload)))
    await worker._analyze(Command("analyze", 7, {"mode": "refine", "bytes": b"image", "sources": {"custom": "Context"}}), Ollama())
    assert not any(kind == "analyzed" for kind, _, _ in events)
    assert events[-1] == ("error", 7, {"operation": "analyze", "message": "Refinement unavailable"})


@pytest.mark.asyncio
async def test_shutdown_cancels_background_analysis(gui, tmp_path, controlled_services):
    worker = Worker(Config(), str(tmp_path))
    worker.submit(Command("analyze", 1, {"bytes": b"old"}))
    running = asyncio.create_task(worker._run())
    try:
        async with asyncio.timeout(1):
            while not controlled_services:
                await asyncio.sleep(0)
            client = controlled_services[-1]
            assert await client.started.get() == b"old"
    finally:
        running.cancel()
        with pytest.raises(asyncio.CancelledError):
            await running
    assert client.cancelled.is_set()
    assert client.closed
    assert worker._analysis_task is None


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_at", ["tags", "description", "exclusion", "readback"])
async def test_unified_apply_partial_write_requires_read_only_reconciliation(gui, tmp_path, fail_at):
    class Client:
        can_write = True
        metadata_capabilities = {"set_image_description": True, "set_image_description_excluded": True}

        def __init__(self):
            self.record = {"id": 1, "path": "/a.jpg", "free_tags": [], "description": "old"}
            self.calls = []
            self.fail = True

        async def fetch_record(self, *args):
            if self.fail and fail_at == "readback" and self.record.get("exclude_embedded_description"):
                raise TimeoutError("readback interrupted")
            return dict(self.record), None

        def validate_call(self, *args):
            pass

        async def apply_tags(self, record, tags):
            self.calls.append("tags")
            self.record["free_tags"] = tags
            if self.fail and fail_at == "tags":
                raise TimeoutError("tag acknowledgement interrupted")

        async def apply_metadata(self, record, name, arguments):
            self.calls.append(name)
            if name == "set_image_description":
                self.record["description"] = arguments["description"]
                if self.fail and fail_at == "description":
                    raise TimeoutError("description acknowledgement interrupted")
            elif self.fail and fail_at == "exclusion":
                raise TimeoutError("interrupted")
            else:
                self.record["exclude_embedded_description"] = arguments["excluded"]

    client = Client()
    worker = Worker(Config(), str(tmp_path))
    journal = StateManager(str(tmp_path))
    baseline = metadata_values(client.record)
    draft = {**baseline, "description": "new", "exclude_embedded_description": True}
    document = {"endpoint": "test", "set_id": 1, "image_id": 1, "path": "/a.jpg", "metadata_draft": draft}
    payload = {"set_id": 1, "offset": 0, "record": client.record.copy(), "tags": ["tree"],
               "baseline": baseline, "metadata_draft": draft, "journal": document}
    try:
        with pytest.raises(TimeoutError):
            await worker._apply_review(client, payload, journal)
        assert journal.restore("test")["status"] == "uncertain"
        before = list(client.calls)
        client.fail = False
        actual = await worker._read_target(client, payload)
        assert client.calls == before
        assert actual["description"] == ("old" if fail_at == "tags" else "new")
        payload["baseline"] = metadata_values(actual)
        client.fail = False
        result = await worker._apply_review(client, payload, journal)
        assert result["exclude_embedded_description"]
        assert client.calls.count("tags") == 1
        assert client.calls.count("set_image_description") == 1
        assert journal.restore("test")["status"] == "applied"
    finally:
        journal.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("problem", ["identity", "external-edit", "missing-writer"])
async def test_unified_apply_preflight_never_writes_on_conflict(gui, tmp_path, problem):
    class Client:
        can_write = False
        metadata_capabilities = {"set_image_description": problem != "missing-writer"}

        async def fetch_record(self, *args):
            return {"id": 2 if problem == "identity" else 1, "path": "/a.jpg", "description": "external" if problem == "external-edit" else "old"}, None

        def validate_call(self, *args):
            pass

        async def apply_metadata(self, *args):
            pytest.fail("Conflicted reviews must not write")

    journal = StateManager(str(tmp_path))
    baseline = metadata_values({"description": "old"})
    payload = {"set_id": 1, "offset": 0, "record": {"id": 1, "path": "/a.jpg"}, "tags": [],
               "baseline": baseline, "metadata_draft": {**baseline, "description": "new"},
               "journal": {"endpoint": "test", "set_id": 1, "image_id": 1, "path": "/a.jpg"}}
    try:
        with pytest.raises(ValueError):
            await Worker(Config(), str(tmp_path))._apply_review(Client(), payload, journal)
        assert journal.restore("test")["status"] == "uncertain"
    finally:
        journal.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("target", [[], ["kept", "new"]])
async def test_tag_replace_exact_result_and_no_replay(gui, tmp_path, target):
    class Client:
        can_replace_tags = True

        def __init__(self):
            self.record = {"id": 1, "path": "/a.jpg", "free_tags": ["kept", "removed"]}
            self.writes = 0

        async def fetch_record(self, *args):
            return dict(self.record), None

        def validate_call(self, *args):
            pass

        async def apply_tags(self, record, tags, mode):
            assert mode == "replace"
            self.writes += 1
            self.record["free_tags"] = list(tags)
            raise TimeoutError("Write succeeded but acknowledgement was lost")

    client = Client()
    worker = Worker(Config(), str(tmp_path))
    journal = StateManager(str(tmp_path))
    payload = {"set_id": 1, "offset": 0, "record": {"id": 1, "path": "/a.jpg"},
               "tags": target, "tag_mode": "replace", "tag_baseline": ["kept", "removed"],
               "journal": {"endpoint": "test", "set_id": 1, "image_id": 1, "path": "/a.jpg", "tag_mode": "replace", "tag_target": target}}
    try:
        with pytest.raises(TimeoutError):
            await worker._apply_review(client, payload, journal)
        assert journal.restore("test")["tag_target"] == target
        result = await worker._apply_review(client, payload, journal)
        assert result["free_tags"] == target
        assert client.writes == 1
    finally:
        journal.close()


@pytest.mark.asyncio
async def test_tag_replace_rejects_changed_baseline(gui, tmp_path):
    class Client:
        async def fetch_record(self, *args):
            return {"id": 1, "path": "/a.jpg", "free_tags": ["external addition"]}, None

    journal = StateManager(str(tmp_path))
    try:
        with pytest.raises(ValueError, match="custom tags changed"):
            await Worker(Config(), str(tmp_path))._apply_review(Client(), {
                "set_id": 1, "offset": 0, "record": {"id": 1, "path": "/a.jpg"}, "tags": [],
                "tag_mode": "replace", "tag_baseline": ["original"],
                "journal": {"endpoint": "test", "set_id": 1, "image_id": 1, "path": "/a.jpg"},
            }, journal)
    finally:
        journal.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("supported", [True, False])
async def test_tag_replace_requires_capability_and_exact_readback(gui, tmp_path, supported):
    class Client:
        can_replace_tags = supported

        async def fetch_record(self, *args):
            return {"id": 1, "path": "/a.jpg", "free_tags": ["old", "new"]}, None

        def validate_call(self, *args):
            pass

        async def apply_tags(self, record, tags, mode):
            assert supported
            assert mode == "replace"
            return ["old", "new"]

    journal = StateManager(str(tmp_path))
    try:
        with pytest.raises(RuntimeError if supported else ValueError):
            await Worker(Config(), str(tmp_path))._apply_review(Client(), {
                "set_id": 1, "offset": 0, "record": {"id": 1, "path": "/a.jpg"},
                "tags": ["new"], "tag_mode": "replace", "tag_baseline": ["old", "new"],
                "journal": {"endpoint": "test", "set_id": 1, "image_id": 1, "path": "/a.jpg"},
            }, journal)
    finally:
        journal.close()