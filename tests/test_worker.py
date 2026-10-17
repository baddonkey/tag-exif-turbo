import asyncio
from contextlib import asynccontextmanager

import pytest

from backend.config import Config
from backend.worker import Command, Worker


@pytest.fixture
def controlled_services(monkeypatch):
    class ControlledOllama:
        def __init__(self, config):
            self.started = asyncio.Queue()
            self.release = asyncio.Event()
            self.cancelled = asyncio.Event()
            self.calls = []
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
            return ["tree", "grass", "sky", "cloud", "landscape"]

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
async def test_preview_loads_do_not_wait_for_inference_and_pending_work_is_coalesced(gui, tmp_path, controlled_services):
    worker = Worker(Config(), str(tmp_path))
    events = {("connected", 1): asyncio.Event(), ("loaded", 3): asyncio.Event(), ("loaded", 5): asyncio.Event(), ("analyzed", 6): asyncio.Event()}
    errors = []

    def receive(kind, token, payload):
        if kind == "error":
            errors.append(payload)
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
        worker.submit(Command("analyze", 6, {"bytes": b"latest"}))
        await asyncio.wait_for(events[("loaded", 3)].wait(), 1)
        await asyncio.wait_for(events[("loaded", 5)].wait(), 1)
        assert not client.release.is_set()
        assert client.calls == [b"old"]
        client.release.set()
        await asyncio.wait_for(events[("analyzed", 6)].wait(), 1)
        assert client.calls == [b"old", b"latest"]
        assert not errors
    finally:
        running.cancel()
        with pytest.raises(asyncio.CancelledError):
            await running
    assert all(client.closed for client in controlled_services)
    assert worker._analysis_task is None


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