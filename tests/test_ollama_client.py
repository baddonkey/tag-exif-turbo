import base64

import httpx
import pytest
from pydantic import ValidationError

from backend.config import Config
from backend.ollama_client import Analysis, OllamaClient


@pytest.mark.parametrize("tags", [["one"], ["tree", "Tree", "grass", "sky", "cloud"], ["a", "b", "c", "d", ""]])
def test_invalid_tags(tags):
    with pytest.raises(ValidationError):
        Analysis(tags=tags, description="A tree.")


@pytest.mark.parametrize("description", ["", "   ", "bad\x00text", "a" * 2001, None])
def test_invalid_description(description):
    with pytest.raises(ValidationError):
        Analysis(tags=["tree", "grass", "cloud", "sky", "landscape"], description=description)


def test_description_required_and_normalized():
    tags = ["tree", "grass", "cloud", "sky", "landscape"]
    with pytest.raises(ValidationError):
        Analysis(tags=tags)
    assert Analysis(tags=tags, description="  A tree.\r\nClouds.  ").description == "A tree.\nClouds."


@pytest.mark.asyncio
async def test_full_image_bytes_are_sent():
    import json

    data = b"whole-image-bytes" * 1000

    async def handler(request):
        body = json.loads(request.content)
        assert base64.b64decode(body["messages"][0]["images"][0]) == data
        assert "tools" not in body
        assert "description" in body["format"]["required"]
        assert body["options"]["num_predict"] == 512
        return httpx.Response(200, json={"message": {"content": '{"tags":["tree","grass","cloud","sky","landscape"],"description":"A tree beneath clouds."}'}})

    client = OllamaClient(Config())
    await client.close()
    client.client = httpx.AsyncClient(base_url="http://test", transport=httpx.MockTransport(handler))
    try:
        result = await client.analyze(data)
        assert len(result.tags) == 5
        assert result.description == "A tree beneath clouds."
    finally:
        await client.close()