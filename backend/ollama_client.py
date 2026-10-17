import base64

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .config import Config
from .tag_model import clean_tags


class Analysis(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tags: list[str] = Field(min_length=5, max_length=10)

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, tags: list[str]) -> list[str]:
        cleaned = clean_tags(tags)
        if len(cleaned) != len(tags):
            raise ValueError("Tags must be nonempty and unique, ignoring case.")
        return cleaned


class OllamaClient:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.client = httpx.AsyncClient(base_url=config.ollama_url, timeout=httpx.Timeout(config.inference_timeout, connect=10))

    async def close(self) -> None:
        await self.client.aclose()

    async def health(self) -> dict:
        response = await self.client.get("/api/tags", timeout=10)
        response.raise_for_status()
        names = {item["name"] for item in response.json().get("models", [])}
        if self.config.model not in names:
            return {"connected": True, "ready": False, "message": f"Model missing. Run: ollama pull {self.config.model}"}
        response = await self.client.post("/api/show", json={"model": self.config.model}, timeout=15)
        response.raise_for_status()
        if "vision" not in response.json().get("capabilities", []):
            return {"connected": True, "ready": False, "message": "The selected model does not advertise vision support."}
        return {"connected": True, "ready": True, "message": "Vision model ready"}

    async def analyze(self, image_bytes: bytes) -> list[str]:
        response = await self.client.post("/api/chat", json={
            "model": self.config.model,
            "stream": False,
            "format": Analysis.model_json_schema(),
            "options": {"temperature": 0.1, "num_predict": 256, "num_ctx": 4096},
            "messages": [{
                "role": "user",
                "content": "Return JSON with 5 to 10 distinct, concise, searchable tags for this image. Describe only visibly supported subjects, objects, actions, surroundings and photographic characteristics. Do not infer people's identities, named locations, events, dates or private traits. Do not use filename or metadata to invent context. No descriptions or commentary.",
                "images": [base64.b64encode(image_bytes).decode("ascii")],
            }],
        })
        response.raise_for_status()
        return Analysis.model_validate_json(response.json()["message"]["content"]).tags