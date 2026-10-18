import base64
from types import SimpleNamespace

import pytest

from backend.config import Config
from backend.mcp_client import McpClient, decode_preview, result_payload
from backend.worker import select_startup_set


def test_startup_set_preference_is_optional(monkeypatch):
    monkeypatch.setattr("backend.config.load_dotenv", lambda: None)
    monkeypatch.delenv("DEFAULT_IMAGE_SET", raising=False)
    assert Config().default_set == ""
    assert Config.from_env().default_set == ""
    monkeypatch.setenv("DEFAULT_IMAGE_SET", " ")
    assert Config.from_env().default_set == ""
    monkeypatch.setenv("DEFAULT_IMAGE_SET", "custom-test")
    assert Config.from_env().default_set == "custom-test"


def test_startup_accepts_any_available_set():
    sets = [{"id": 1, "name": "Holiday photos"}, {"id": 2, "name": "Landscapes"}]
    assert select_startup_set(sets) == sets[0]
    assert select_startup_set(sets, "Landscapes") == sets[1]
    with pytest.raises(ValueError, match="missing or ambiguous"):
        select_startup_set(sets, "Missing set")
    with pytest.raises(ValueError, match="No image sets"):
        select_startup_set([])


def test_startup_restores_saved_set_before_preference():
    sets = [{"id": 1, "name": "Holiday photos"}, {"id": 2, "name": "Landscapes"}]
    saved = {"set_id": 2, "set_name": "Landscapes"}
    assert select_startup_set(sets, "Missing preference", saved) == sets[1]
    with pytest.raises(ValueError, match="Saved image set changed"):
        select_startup_set(sets[:1], saved=saved)


def test_payload_prefers_structured_content():
    result = SimpleNamespace(is_error=False, structured_content={"sets": []}, content=[])
    assert result_payload(result) == {"sets": []}


def test_error_result_is_not_success():
    with pytest.raises(RuntimeError, match="locked"):
        result_payload(SimpleNamespace(is_error=True, content=[SimpleNamespace(type="text", text="locked")]))


def test_schema_rejects_unknown_arguments():
    client = McpClient(None, Config())
    client.tools["read"] = SimpleNamespace(input_schema={"type": "object", "properties": {"offset": {"type": "integer"}}, "required": ["offset"]})
    client.validate_call("read", {"offset": 0})
    with pytest.raises(ValueError):
        client.validate_call("read", {"offset": 0, "invented": True})
    with pytest.raises(ValueError):
        client.validate_call("read", {"offset": "zero"})


def test_invalid_preview_rejected():
    with pytest.raises(ValueError):
        decode_preview(b"not an image")


@pytest.mark.asyncio
async def test_batch_per_image_failure():
    client = McpClient(None, Config())
    client.can_write = True

    async def fake_call(name, arguments):
        assert arguments["updates"][0]["mode"] == "append"
        return {"results": [{"ok": False, "error": "identity mismatch"}]}, None

    client.call = fake_call
    with pytest.raises(RuntimeError, match="identity mismatch"):
        await client.apply_tags({"id": 1, "path": "/a.jpg"}, ["tree"])


@pytest.mark.asyncio
async def test_selected_image_loads_identity_and_preview(monkeypatch):
    client = McpClient(None, Config())
    client.can_read_selected_image = True
    image = object()

    async def fake_call(name, arguments):
        assert name == "get_selected_image"
        assert arguments == {"include_preview": True}
        return {
            "image_id": 42,
            "path": "/selected.jpg",
            "filename": "selected.jpg",
            "free_tags": ["existing"],
            "metadata": {"Make": "Canon"},
            "preview_jpeg_base64": base64.b64encode(b"preview").decode("ascii"),
        }, None

    monkeypatch.setattr("backend.mcp_client.decode_preview", lambda data: image)
    client.call = fake_call
    loaded = await client.load_selected_image()
    assert loaded["record"] == {
        "id": 42,
        "path": "/selected.jpg",
        "filename": "selected.jpg",
        "free_tags": ["existing"],
        "metadata": {"Make": "Canon"},
    }
    assert loaded["bytes"] == b"preview"
    assert loaded["image"] is image


@pytest.mark.asyncio
async def test_selected_image_requires_stable_identity():
    client = McpClient(None, Config())
    client.can_read_selected_image = True

    async def fake_call(name, arguments):
        return {"image_id": None, "path": "/selected.jpg", "filename": "selected.jpg"}, None

    client.call = fake_call
    with pytest.raises(ValueError, match="stable ID"):
        await client.fetch_selected_image(False)