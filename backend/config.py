import os
from dataclasses import dataclass
from urllib.parse import urlparse

from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    mcp_url: str = "http://127.0.0.1:8765/mcp"
    ollama_url: str = "http://127.0.0.1:11434"
    model: str = "qwen3-vl:4b-instruct-q8_0"
    default_set: str = ""
    request_timeout: float = 30
    inference_timeout: float = 180

    def __post_init__(self) -> None:
        for address in (self.mcp_url, self.ollama_url):
            parsed = urlparse(address)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username:
                raise ValueError("Service URLs must be HTTP(S) URLs without embedded credentials.")
        if not self.model.strip():
            raise ValueError("A model name is required.")

    @classmethod
    def from_env(cls) -> "Config":
        load_dotenv()
        return cls(
            mcp_url=os.getenv("MCP_URL", cls.mcp_url),
            ollama_url=os.getenv("OLLAMA_URL", cls.ollama_url).rstrip("/"),
            model=os.getenv("OLLAMA_MODEL", cls.model),
            default_set=os.getenv("DEFAULT_IMAGE_SET", "").strip() or cls.default_set,
        )