import asyncio
import base64
import json
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import unquote, urlparse

import httpx
from jsonschema import Draft202012Validator
from mcp import ClientSession, types
from mcp.client.streamable_http import streamable_http_client
from PySide6.QtCore import QBuffer, QByteArray, QIODevice
from PySide6.QtGui import QImageReader

from .config import Config

MAX_IMAGE_BYTES = 32 * 1024 * 1024


def result_payload(result):
    if getattr(result, "is_error", False):
        message = "\n".join(item.text for item in result.content if item.type == "text")
        raise RuntimeError(message or "MCP tool failed.")
    structured = getattr(result, "structured_content", None)
    if structured is not None:
        return structured
    for item in getattr(result, "content", []):
        if item.type == "text":
            try:
                return json.loads(item.text)
            except json.JSONDecodeError:
                continue
    raise ValueError("MCP returned no supported structured result.")


def decode_preview(data: bytes):
    if not data or len(data) > MAX_IMAGE_BYTES:
        raise ValueError("Preview is empty or exceeds the 32 MiB safety limit.")
    buffer = QBuffer()
    buffer.setData(QByteArray(data))
    buffer.open(QIODevice.OpenModeFlag.ReadOnly)
    reader = QImageReader(buffer)
    reader.setAutoTransform(True)
    dimensions = reader.size()
    if dimensions.width() * dimensions.height() > 100_000_000:
        raise ValueError("Preview dimensions exceed the decode safety limit.")
    image = reader.read()
    if image.isNull():
        raise ValueError(f"Cannot decode preview: {reader.errorString()}")
    return image


class McpClient:
    def __init__(self, session: ClientSession, config: Config) -> None:
        self.session = session
        self.config = config
        self.tools: dict = {}
        self.resources: list[str] = []
        self.can_write = False
        self.can_replace_tags = False
        self.can_read_selected_image = False
        self.metadata_capabilities: dict[str, bool] = {}

    @classmethod
    @asynccontextmanager
    async def open(cls, config: Config):
        async with streamable_http_client(config.mcp_url, max_sse_event_size=64 * 1024 * 1024) as streams:
            async with ClientSession(streams[0], streams[1], read_timeout_seconds=config.request_timeout) as session:
                async with asyncio.timeout(config.request_timeout):
                    info = await session.initialize()
                    if info.server_info.name != "exif-turbo":
                        raise ValueError("Unsupported MCP server. Expected exif-turbo.")
                    client = cls(session, config)
                    await client.discover()
                yield client

    async def discover(self) -> None:
        cursor = None
        while True:
            page = await self.session.list_tools(params=types.PaginatedRequestParams(cursor=cursor) if cursor else None)
            self.tools.update({tool.name: tool for tool in page.tools})
            cursor = page.next_cursor
            if not cursor:
                break
        self.validate_call("list_image_sets", {})
        self.validate_call("get_image_set_images", {"set_id": 1, "offset": 0, "limit": 1, "include_previews": True})
        try:
            self.validate_call("get_selected_image", {"include_preview": True})
            self.can_read_selected_image = True
        except ValueError:
            self.can_read_selected_image = False
        try:
            self.validate_call("set_custom_tags_batch", {"updates": [{"image_id": 1, "path": "/schema-check", "tags": ["schema-check"], "mode": "append"}]})
            self.can_write = True
        except ValueError:
            self.can_write = False
        try:
            self.validate_call("set_custom_tags_batch", {"updates": [{"image_id": 1, "path": "/schema-check", "tags": [], "mode": "replace"}]})
            self.can_replace_tags = True
        except ValueError:
            self.can_replace_tags = False
        for name, extra in {
            "set_image_description": {"description": "schema-check", "mode": "replace"},
            "set_image_description_excluded": {"excluded": False},
            "set_image_embedded_tag_excluded": {"tag": "schema-check", "excluded": False},
            "set_image_all_embedded_tags_excluded": {"excluded": False},
        }.items():
            try:
                self.validate_call(name, {"image_id": 1, "path": "/schema-check", **extra})
                self.metadata_capabilities[name] = True
            except ValueError:
                self.metadata_capabilities[name] = False
        try:
            page = await self.session.list_resource_templates()
            self.resources = [str(item.uri_template) for item in page.resource_templates]
        except Exception:
            self.resources = []

    def validate_call(self, name: str, arguments: dict) -> None:
        tool = self.tools.get(name)
        if tool is None:
            raise ValueError(f"Required MCP capability is unavailable: {name}")
        schema = tool.input_schema
        unknown = arguments.keys() - schema.get("properties", {}).keys()
        if unknown:
            raise ValueError(f"Unsupported MCP parameters for {name}: {sorted(unknown)}")
        errors = list(Draft202012Validator(schema).iter_errors(arguments))
        if errors:
            raise ValueError(f"Incompatible MCP schema for {name}: {errors[0].message}")

    async def call(self, name: str, arguments: dict):
        self.validate_call(name, arguments)
        async with asyncio.timeout(self.config.request_timeout):
            result = await self.session.call_tool(name, arguments)
        return result_payload(result), result

    async def list_sets(self) -> list[dict]:
        payload, _ = await self.call("list_image_sets", {})
        sets = payload.get("sets") if isinstance(payload, dict) else payload
        if not isinstance(sets, list) or any(not isinstance(item, dict) or not isinstance(item.get("id"), int) or not isinstance(item.get("name"), str) for item in sets):
            raise ValueError("Unsupported image-set response.")
        return sets

    async def fetch_record(self, set_id: int, offset: int, previews: bool = True) -> tuple[dict | None, object]:
        payload, result = await self.call("get_image_set_images", {"set_id": set_id, "offset": offset, "limit": 1, "include_previews": previews})
        if not isinstance(payload, dict) or not isinstance(payload.get("images"), list):
            raise ValueError("Unsupported image-page response.")
        records = payload["images"]
        if not records:
            return None, result
        if len(records) != 1:
            raise ValueError("MCP did not honor the one-image limit.")
        record = records[0]
        if not isinstance(record.get("id"), int) or not record.get("path") or not record.get("filename"):
            raise ValueError("MCP image has no stable ID, path, or filename.")
        self.validate_metadata(record)
        return record, result

    async def load_image(self, set_id: int, offset: int) -> dict | None:
        record, result = await self.fetch_record(set_id, offset)
        if record is None:
            return None
        data = await self.preview_bytes(record, result)
        image = decode_preview(data)
        record = {key: value for key, value in record.items() if key != "preview_jpeg_base64"}
        return {"record": record, "bytes": data, "image": image}

    async def fetch_selected_image(self, include_preview: bool = True) -> dict:
        if not self.can_read_selected_image:
            raise ValueError("The connected Exif Turbo server does not expose get_selected_image.")
        payload, _ = await self.call("get_selected_image", {"include_preview": include_preview})
        if not isinstance(payload, dict):
            raise ValueError("Unsupported selected-image response.")
        image_id = payload.get("image_id")
        path = payload.get("path")
        filename = payload.get("filename")
        if type(image_id) is not int or image_id <= 0 or not isinstance(path, str) or not path or not isinstance(filename, str) or not filename:
            raise ValueError("The selected image has no stable ID, path, or filename for identity-verified tagging.")
        free_tags = payload.get("free_tags", [])
        metadata = payload.get("metadata")
        if not isinstance(free_tags, list) or not all(isinstance(tag, str) for tag in free_tags):
            raise ValueError("Unsupported selected-image tags.")
        if metadata is not None and not isinstance(metadata, dict):
            raise ValueError("Unsupported selected-image metadata.")
        record = {"id": image_id, "path": path, "filename": filename, "free_tags": free_tags, "metadata": metadata or {}}
        for key in ("description", "exclude_embedded_description", "excluded_embedded_tags", "exclude_all_embedded_tags"):
            if key in payload:
                record[key] = payload[key]
        self.validate_metadata(record)
        if not include_preview:
            return {"record": record}
        encoded = payload.get("preview_jpeg_base64")
        if not isinstance(encoded, str) or not encoded or len(encoded) > MAX_IMAGE_BYTES * 4 // 3 + 8:
            raise ValueError("No usable preview is available for the selected image.")
        data = base64.b64decode(encoded, validate=True)
        image = decode_preview(data)
        return {"record": record, "bytes": data, "image": image}

    async def load_selected_image(self) -> dict:
        return await self.fetch_selected_image()

    @staticmethod
    def validate_metadata(record: dict) -> None:
        if "description" in record and not isinstance(record["description"], str):
            raise ValueError("Unsupported custom description.")
        for key in ("exclude_embedded_description", "exclude_all_embedded_tags"):
            if key in record and type(record[key]) is not bool:
                raise ValueError(f"Unsupported {key}.")
        if "excluded_embedded_tags" in record:
            tags = record["excluded_embedded_tags"]
            if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
                raise ValueError("Unsupported embedded tag exclusions.")

    async def apply_metadata(self, record: dict, name: str, arguments: dict) -> dict:
        if not self.metadata_capabilities.get(name, False):
            raise ValueError(f"Required MCP capability is unavailable: {name}")
        payload, _ = await self.call(name, {**arguments, "image_id": record["id"], "path": record["path"]})
        if not isinstance(payload, dict) or payload.get("ok") is not True:
            raise RuntimeError("MCP did not confirm the metadata write; reconcile before retrying.")
        if type(payload.get("image_id")) is not int or payload["image_id"] != record["id"] or payload.get("path") != record["path"]:
            raise RuntimeError("MCP write result identity mismatch; reconcile before retrying.")
        required = {
            "set_image_description": ("description",),
            "set_image_description_excluded": ("exclude_embedded_description",),
            "set_image_embedded_tag_excluded": ("excluded_embedded_tags", "exclude_all_embedded_tags"),
            "set_image_all_embedded_tags_excluded": ("excluded_embedded_tags", "exclude_all_embedded_tags"),
        }[name]
        if any(key not in payload for key in required) or type(payload.get("changed")) is not bool:
            raise RuntimeError("MCP write response has no confirmed metadata values.")
        self.validate_metadata(payload)
        return {key: payload[key] for key in required}

    async def preview_bytes(self, record: dict, result) -> bytes:
        encoded = record.get("preview_jpeg_base64")
        if encoded:
            if len(encoded) > MAX_IMAGE_BYTES * 4 // 3 + 8:
                raise ValueError("Encoded preview is too large.")
            return base64.b64decode(encoded, validate=True)
        for item in getattr(result, "content", []):
            if item.type == "image":
                if len(item.data) > MAX_IMAGE_BYTES * 4 // 3 + 8:
                    raise ValueError("Encoded image is too large.")
                return base64.b64decode(item.data, validate=True)
        resource = record.get("preview_uri")
        if resource and str(resource).startswith("exif-turbo://"):
            async with asyncio.timeout(self.config.request_timeout):
                result = await self.session.read_resource(resource)
            for content in result.contents:
                if hasattr(content, "blob"):
                    if len(content.blob) > MAX_IMAGE_BYTES * 4 // 3 + 8:
                        raise ValueError("Resource preview is too large.")
                    return base64.b64decode(content.blob, validate=True)
        location = record.get("preview_url") or record.get("preview_path") or record.get("path")
        if not location:
            raise ValueError("No usable image preview was returned.")
        parsed = urlparse(str(location))
        if parsed.scheme in {"http", "https"}:
            async with httpx.AsyncClient(timeout=self.config.request_timeout, follow_redirects=False) as client:
                async with client.stream("GET", str(location)) as response:
                    response.raise_for_status()
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        data.extend(chunk)
                        if len(data) > MAX_IMAGE_BYTES:
                            raise ValueError("Remote preview is too large.")
                    return bytes(data)
        if parsed.scheme not in {"", "file"}:
            raise ValueError("Unsupported preview URL scheme.")
        path = Path(unquote(parsed.path) if parsed.scheme == "file" else str(location))
        if not path.is_file() or path.stat().st_size > MAX_IMAGE_BYTES:
            raise ValueError("Preview path is inaccessible or exceeds 32 MiB.")
        with path.open("rb") as stream:
            return stream.read(MAX_IMAGE_BYTES + 1)

    async def apply_tags(self, record: dict, tags: list[str], mode: str = "append") -> list[str]:
        if mode not in {"append", "replace"}:
            raise ValueError("Tag mode must be append or replace.")
        if not (self.can_replace_tags if mode == "replace" else self.can_write):
            raise ValueError("No identity-addressed tag-writing capability is available.")
        payload, _ = await self.call("set_custom_tags_batch", {"updates": [{"image_id": record["id"], "path": record["path"], "tags": tags, "mode": mode}]})
        results = payload.get("results", [])
        if len(results) != 1:
            raise RuntimeError("MCP returned an ambiguous write result; reconcile before retrying.")
        result = results[0]
        if not result.get("ok"):
            raise RuntimeError(result.get("error", "MCP rejected the tag write."))
        if result.get("image_id") != record["id"] or result.get("path") != record["path"]:
            raise RuntimeError("MCP write result identity mismatch; reconcile before retrying.")
        tags = result.get("free_tags")
        if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
            raise RuntimeError("MCP write response has no confirmed tag list.")
        return tags