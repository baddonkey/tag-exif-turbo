import base64

import httpx
import pytest
from pydantic import ValidationError

from backend.config import Config
from backend.ollama_client import Analysis, OllamaClient


@pytest.mark.parametrize("tags", [["one"], ["tree", "Tree", "grass", "sky", "cloud"], ["a", "b", "c", "d", ""]])
def test_invalid_tags(tags):
    with pytest.raises(ValidationError):
        Analysis(tags=tags)


@pytest.mark.asyncio
async def test_full_image_bytes_are_sent():
    import json

    data = b"whole-image-bytes" * 1000

    async def handler(request):
        body = json.loads(request.content)
        assert base64.b64decode(body["messages"][0]["images"][0]) == data
        assert "tools" not in body
        return httpx.Response(200, json={"message": {"content": '{"tags":["tree","grass","cloud","sky","landscape"]}'}})

    client = OllamaClient(Config())
    await client.close()
    client.client = httpx.AsyncClient(base_url="http://test", transport=httpx.MockTransport(handler))
    try:
        assert len(await client.analyze(data)) == 5
    finally:
        await client.close()