# Exif Turbo AI Tagger

A native desktop app for reviewing AI-generated image tags with Exif Turbo and
Ollama. Edit suggestions, approve tags, or skip an image. No OpenWebUI required.

![Exif Turbo AI Tagger reviewing an image and suggested tags](docs/readme_hs.png)

## Run

Requires Python 3.11+; tested on macOS with Python 3.14.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python main.py
```

Keep these services running:

- Exif Turbo: unlocked database, MCP at `http://127.0.0.1:8765/mcp`, and custom tagging enabled for writes.
- Ollama: API at `http://127.0.0.1:11434` with `qwen3-vl:4b-instruct-q8_0` installed.

Configure endpoints and the model in Settings or through [.env.example](.env.example).
Startup restores your saved review or selects the first available image set.
Optionally set `DEFAULT_IMAGE_SET` to prefer a set when starting without saved progress.
**Apply Tags requires explicit approval and preserves existing tags.**
Previous and Next stay available during AI analysis; results for images you leave
are discarded without writing tags.

## Develop

```sh
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m pytest -q
.venv/bin/python main.py --version
```

See [the project specification](docs/project-spec.md) for architecture, workflow,
shortcuts, persistence, live checks, troubleshooting, and versioning.