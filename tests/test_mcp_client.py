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


@pytest.mark.asyncio
async def test_selected_metadata_preserved():
    client = McpClient(None, Config())
    client.can_read_selected_image = True
    fields = {"description": "A tree.", "exclude_embedded_description": True,
              "excluded_embedded_tags": ["private"], "exclude_all_embedded_tags": False}

    async def fake_call(name, arguments):
        return {"image_id": 1, "path": "/a.jpg", "filename": "a.jpg", **fields}, None

    client.call = fake_call
    record = (await client.fetch_selected_image(False))["record"]
    assert {key: record[key] for key in fields} == fields


@pytest.mark.asyncio
@pytest.mark.parametrize("wrong_identity", [False, True])
async def test_metadata_write_confirmation(wrong_identity):
    client = McpClient(None, Config())
    client.metadata_capabilities["set_image_description"] = True

    async def fake_call(name, arguments):
        assert arguments["mode"] == "replace"
        return {"image_id": 2 if wrong_identity else 1, "path": "/a.jpg", "ok": True,
                "description": "", "changed": False}, None

    client.call = fake_call
    if wrong_identity:
        with pytest.raises(RuntimeError, match="identity mismatch"):
            await client.apply_metadata({"id": 1, "path": "/a.jpg"}, "set_image_description", {"description": "", "mode": "replace"})
    else:
        assert await client.apply_metadata({"id": 1, "path": "/a.jpg"}, "set_image_description", {"description": "", "mode": "replace"}) == {"description": ""}


@pytest.mark.asyncio
@pytest.mark.parametrize("modern", [False, True])
async def test_metadata_discovery_is_optional_and_never_writes(modern):
    class Session:
        async def list_tools(self, params=None):
            definitions = {
                "list_image_sets": {},
                "get_image_set_images": {"set_id": {"type": "integer"}, "offset": {"type": "integer"}, "limit": {"type": "integer"}, "include_previews": {"type": "boolean"}},
                "set_custom_tags_batch": {"updates": {"type": "array"}},
            }
            if modern:
                for name, extra in {
                    "set_image_description": {"description": {"type": "string"}, "mode": {"enum": ["append", "replace"]}},
                    "set_image_description_excluded": {"excluded": {"type": "boolean"}},
                    "set_image_embedded_tag_excluded": {"tag": {"type": "string"}, "excluded": {"type": "boolean"}},
                    "set_image_all_embedded_tags_excluded": {"excluded": {"type": "boolean"}},
                }.items():
                    definitions[name] = {"image_id": {"type": "integer"}, "path": {"type": "string"}, **extra}
            return SimpleNamespace(tools=[SimpleNamespace(name=name, input_schema={"type": "object", "properties": fields, "required": list(fields)}) for name, fields in definitions.items()], next_cursor=None)

        async def list_resource_templates(self):
            return SimpleNamespace(resource_templates=[])

        async def call_tool(self, *args):
            pytest.fail("Discovery must not call tools")

    client = McpClient(Session(), Config())
    await client.discover()
    assert client.can_write
    assert len(client.metadata_capabilities) == 4
    assert all(value is modern for value in client.metadata_capabilities.values())


@pytest.mark.parametrize("record", [
    {"description": None}, {"exclude_embedded_description": 1},
    {"exclude_all_embedded_tags": "false"}, {"excluded_embedded_tags": [1]},
])
def test_malformed_metadata_rejected(record):
    with pytest.raises(ValueError):
        McpClient.validate_metadata(record)


@pytest.mark.asyncio
@pytest.mark.parametrize("tags", [[], ["tree"]])
async def test_tag_replacement_including_clear(tags):
    client = McpClient(None, Config())
    client.can_replace_tags = True

    async def fake_call(name, arguments):
        assert name == "set_custom_tags_batch"
        assert arguments == {"updates": [{"image_id": 1, "path": "/a.jpg", "tags": tags, "mode": "replace"}]}
        return {"results": [{"ok": True, "image_id": 1, "path": "/a.jpg", "free_tags": tags}]}, None

    client.call = fake_call
    assert await client.apply_tags({"id": 1, "path": "/a.jpg"}, tags, "replace") == tags