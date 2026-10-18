import base64
import json
import socket
import threading
from contextlib import contextmanager
from dataclasses import replace
from types import SimpleNamespace

import httpx
import pytest
import uvicorn
from mcp.server import MCPServer
from mcp.types import CallToolResult, TextContent
from PySide6.QtCore import QBuffer, QByteArray, QIODevice
from PySide6.QtGui import QImage
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from backend.config import Config
from backend.mcp_client import McpClient
from backend.metadata_model import metadata_values
from backend.ollama_client import OllamaClient
from backend.state_manager import StateManager
from backend.worker import Worker


@pytest.fixture
def local_http_server(allow_http_endpoint):
    _, allow = allow_http_endpoint

    @contextmanager
    def serve(application):
        ready = threading.Event()

        class Server(uvicorn.Server):
            async def startup(self, sockets=None):
                await super().startup(sockets)
                ready.set()

        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        url = f"http://127.0.0.1:{listener.getsockname()[1]}"
        allow(url)
        server = Server(uvicorn.Config(application, host="127.0.0.1", log_level="critical", lifespan="on", timeout_graceful_shutdown=1))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        try:
            assert ready.wait(10), "Local fixture server did not start"
            assert server.started
            yield url
        finally:
            server.should_exit = True
            thread.join(5)
            if thread.is_alive():
                server.force_exit = True
                thread.join(3)
            listener.close()
            assert not thread.is_alive(), "Local fixture server did not stop"

    return serve


@pytest.fixture
def mcp_service(local_http_server):
    @contextmanager
    def service(modern=True):
        image = QImage(32, 24, QImage.Format.Format_RGB32)
        image.fill(0xFF448855)
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        assert image.save(buffer, "JPEG")
        buffer.close()
        preview = base64.b64encode(bytes(data)).decode("ascii")
        state = SimpleNamespace(
            record={"id": 42, "path": "/fixture/image.png", "filename": "image.png", "free_tags": ["saved"],
                    "description": "Saved caption", "excluded_embedded_tags": [],
                    "exclude_all_embedded_tags": False, "exclude_embedded_description": False,
                    "metadata": {"XMP-dc:Subject": ["private"], "IFD0:ImageDescription": "Fixture caption"}},
            selected_changed=False, fail_description=False, writes=[],
        )
        server = MCPServer(name="exif-turbo", log_level="ERROR")

        def check_identity(image_id, path):
            if image_id != state.record["id"] or path != state.record["path"]:
                raise ValueError("Fixture identity mismatch")

        @server.tool()
        def list_image_sets() -> dict:
            return {"sets": [{"id": 1, "name": "fixture-set", "member_count": 1}]}

        @server.tool()
        def get_image_set_images(set_id: int, offset: int = 0, limit: int = 1, include_previews: bool = False) -> dict:
            record = {**state.record, **({"preview_jpeg_base64": preview} if include_previews else {})}
            return {"images": [record] if set_id == 1 and offset == 0 else [], "next_offset": None}

        @server.tool()
        def get_selected_image(include_preview: bool = True) -> dict:
            record = dict(state.record)
            record["image_id"] = record.pop("id")
            if state.selected_changed:
                record.update(image_id=99, path="/fixture/other.png", filename="other.png")
            if include_preview:
                record["preview_jpeg_base64"] = preview
            return record

        @server.tool()
        def set_custom_tags_batch(updates: list[dict]) -> dict:
            results = []
            for update in updates:
                check_identity(update["image_id"], update["path"])
                state.writes.append("tags")
                tags = [] if update["mode"] == "replace" else list(state.record["free_tags"])
                for tag in update["tags"]:
                    if tag.casefold() not in {existing.casefold() for existing in tags}:
                        tags.append(tag)
                state.record["free_tags"] = tags
                results.append({"image_id": 42, "path": state.record["path"], "ok": True, "free_tags": tags})
            return {"results": results}

        def metadata_result(image_id, path, **fields):
            check_identity(image_id, path)
            state.writes.append("metadata")
            state.record.update(fields)
            return {"image_id": image_id, "path": path, "ok": True, "changed": True, **fields}

        if modern:
            @server.tool()
            def set_image_description(image_id: int, path: str, description: str, mode: str) -> CallToolResult:
                if state.fail_description:
                    return CallToolResult(content=[TextContent(type="text", text="Simulated sidecar conflict")], is_error=True)
                assert mode == "replace"
                payload = metadata_result(image_id, path, description=description)
                return CallToolResult(content=[TextContent(type="text", text=json.dumps(payload))], structured_content=payload)

            @server.tool()
            def set_image_description_excluded(image_id: int, path: str, excluded: bool) -> dict:
                return metadata_result(image_id, path, exclude_embedded_description=excluded)

            @server.tool()
            def set_image_all_embedded_tags_excluded(image_id: int, path: str, excluded: bool) -> dict:
                return metadata_result(image_id, path, exclude_all_embedded_tags=excluded,
                                       excluded_embedded_tags=state.record["excluded_embedded_tags"])

            @server.tool()
            def set_image_embedded_tag_excluded(image_id: int, path: str, tag: str, excluded: bool) -> dict:
                tags = [value for value in state.record["excluded_embedded_tags"] if value.casefold() != tag.casefold()]
                if excluded:
                    tags.append(tag)
                return metadata_result(image_id, path, excluded_embedded_tags=tags,
                                       exclude_all_embedded_tags=state.record["exclude_all_embedded_tags"])

        with local_http_server(server.streamable_http_app(json_response=True)) as url:
            yield replace(Config(), mcp_url=f"{url}/mcp"), state

    return service


@pytest.mark.asyncio
@pytest.mark.parametrize("modern", [False, True])
async def test_mcp_real_discovery_preview_and_optional_writes(gui, mcp_service, modern):
    with mcp_service(modern) as (config, state):
        async with McpClient.open(config) as client:
            assert (await client.list_sets())[0]["name"] == "fixture-set"
            loaded = await client.load_image(1, 0)
            assert loaded["image"].width() == 32
            assert loaded["bytes"].startswith(b"\xff\xd8")
            assert loaded["record"]["id"] == 42
            assert await client.load_image(1, 1) is None
            assert all(value is modern for value in client.metadata_capabilities.values())
            assert state.writes == []
            assert await client.apply_tags(loaded["record"], [], "replace") == []
            if modern:
                await client.apply_metadata(loaded["record"], "set_image_description", {"description": "New caption", "mode": "replace"})
                await client.apply_metadata(loaded["record"], "set_image_embedded_tag_excluded", {"tag": "private", "excluded": True})
                await client.apply_metadata(loaded["record"], "set_image_all_embedded_tags_excluded", {"excluded": True})
                await client.apply_metadata(loaded["record"], "set_image_description_excluded", {"excluded": True})
                actual = (await client.fetch_selected_image(False))["record"]
                assert actual["description"] == "New caption"
                assert actual["excluded_embedded_tags"] == ["private"]
                assert actual["exclude_all_embedded_tags"] and actual["exclude_embedded_description"]


@pytest.mark.asyncio
async def test_mcp_transport_partial_apply_reconciliation_and_selected_identity(gui, tmp_path, mcp_service):
    with mcp_service() as (config, state):
        async with McpClient.open(config) as client:
            record = (await client.fetch_selected_image(False))["record"]
            payload = {"selected_image": True, "record": record, "tags": ["new"],
                       "baseline": metadata_values(record), "metadata_draft": metadata_values({**record, "description": "New caption"}),
                       "journal": {"endpoint": config.mcp_url, "set_id": 0, "image_id": 42, "path": record["path"]}}
            journal = StateManager(str(tmp_path))
            worker = Worker(config, str(tmp_path))
            try:
                state.fail_description = True
                with pytest.raises(RuntimeError, match="Simulated"):
                    await worker._apply_review(client, payload, journal)
                assert journal.restore(config.mcp_url)["status"] == "uncertain"
                writes = list(state.writes)
                actual = await worker._read_target(client, payload)
                assert state.writes == writes
                assert "new" in actual["free_tags"]
                payload["baseline"] = metadata_values(actual)
                state.fail_description = False
                result = await worker._apply_review(client, payload, journal)
                assert result["description"] == "New caption"
                assert state.writes.count("tags") == 1
                state.selected_changed = True
                writes = list(state.writes)
                with pytest.raises(ValueError, match="target changed"):
                    await worker._apply_review(client, payload, journal)
                assert state.writes == writes
            finally:
                journal.close()


@pytest.mark.asyncio
async def test_ollama_real_http_health_generation_and_refinement(local_http_server):
    calls = []

    async def tags(request):
        return JSONResponse({"models": [{"name": Config().model}]})

    async def show(request):
        return JSONResponse({"capabilities": ["vision"]})

    async def chat(request):
        body = await request.json()
        calls.append(body)
        if "tags" in body["format"]["properties"]:
            result = {"tags": ["field", "sky", "sun", "landscape", "illustration"], "description": "A field below the sky."}
        elif "images" in body["messages"][-1]:
            result = {"description": "A field below the sky.", "review_notes": []}
        else:
            context = json.loads(body["messages"][-1]["content"])
            result = {"description": context["source_descriptions"]["embedded"], "review_notes": ["Supplied context is not visually verified."]}
        return JSONResponse({"message": {"content": json.dumps(result)}})

    application = Starlette(routes=[Route("/api/tags", tags), Route("/api/show", show, methods=["POST"]), Route("/api/chat", chat, methods=["POST"])])
    with local_http_server(application) as url:
        client = OllamaClient(replace(Config(), ollama_url=url))
        try:
            assert (await client.health())["ready"]
            assert len((await client.analyze(b"full-image")).tags) == 5
            result = await client.refine_description(b"full-image", {"embedded": "Bern, 2024."})
            assert result.description == "Bern, 2024."
            assert len(calls) == 3
            assert base64.b64decode(calls[0]["messages"][0]["images"][0]) == b"full-image"
            assert "images" not in calls[-1]["messages"][-1]
        finally:
            await client.close()


@pytest.mark.asyncio
async def test_ollama_transport_http_error_is_propagated(local_http_server):
    application = Starlette(routes=[Route("/api/chat", lambda request: JSONResponse({}, status_code=503), methods=["POST"])])
    with local_http_server(application) as url:
        client = OllamaClient(replace(Config(), ollama_url=url))
        try:
            with pytest.raises(httpx.HTTPStatusError):
                await client.analyze(b"image")
        finally:
            await client.close()