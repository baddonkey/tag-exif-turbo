# Exif Turbo AI Tagger: Project Specification

## Scope

A native desktop application for reviewing and approving AI-generated image tags.
All visual interface elements use Qt Quick/QML, Qt Quick Controls 2, Layouts and
Dialogs. Python uses PySide6 and QQmlApplicationEngine. There is no Qt Widgets UI,
browser frontend, web server or OpenWebUI dependency.

Descriptions are deferred. Existing metadata is never replaced or deleted by
this application. Bulk autonomous approval, installers, signing and notarization
are outside the current scope.

## Runtime and Configuration

- Python minimum: 3.11; verified environment: Python 3.14.6 on macOS.
- Runtime dependencies and exact versions: ../pyproject.toml.
- Development dependencies: the optional `dev` extra, installed with
  `.venv/bin/python -m pip install -e '.[dev]'`.
- Exif Turbo MCP: http://127.0.0.1:8765/mcp.
- Ollama API: http://127.0.0.1:11434.
- Default vision model: qwen3-vl:4b-instruct-q8_0.
- Startup image set: restore saved progress, otherwise use the optional
  DEFAULT_IMAGE_SET preference or the first available set. No specific name is required.
- Exif Turbo must have an unlocked database and MCP enabled. Custom tagging must
  be enabled to permit writes.

Settings persists endpoint and model preferences. Environment variables override
saved service settings; a local .env is loaded automatically. Supported variables
are documented in ../.env.example. Models are not downloaded, substituted, or
unloaded automatically. Other platforms require compatible Qt wheels and remain
uncertified.

The source checkout starts with `.venv/bin/python main.py`. Installation also
provides `.venv/bin/tag-exif-turbo`; with the virtual environment activated, the
command is `tag-exif-turbo`.

## Versioning and Packaging

The initial application version is 0.0.1. Use simple MAJOR.MINOR.PATCH versioning:
PATCH for compatible fixes, MINOR for compatible features, and MAJOR for breaking
changes. The single version source is `project.version` in ../pyproject.toml.
Increment it for a release and reinstall editable metadata after changing it.

The backend exposes __version__; the entry point supports --version and supplies
the same value to QGuiApplication.setApplicationVersion. The SQLite journal schema
version is independent of the application release version.

PEP 517 builds use Hatchling. Wheels include the Python entry point, backend,
QML components and icon assets. Installed copies resolve bundled resources from
backend/resources; source checkouts use the adjacent qml and assets directories.
Source distributions also include tests, documentation and the environment example.
This Python package is not a signed macOS application bundle or Windows installer.

## Interface

The ApplicationWindow contains a toolbar with service status, set selector,
image index, progress and settings; a horizontal resizable SplitView; and an
action bar with Previous, Next, Regenerate, Skip, Apply Tags and Quit.

The viewer preserves aspect ratio, fits the available space, supports wheel and
pinch zoom up to 12x, and permits dragging when enlarged. Original image dimensions
from metadata are distinguished from the decoded preview dimensions.

The review panel shows model readiness, editable suggested tag chips, custom tag
input, read-only existing tags, and image metadata. The QML Theme singleton owns
dark/light colors, typography and spacing. Dropdown text has explicit theme-aware
contrast. Window geometry and initial splitter preferences are restored once at
startup; image and set changes must preserve the user's current dimensions.

Application icons use lens-and-tag artwork on opaque white backgrounds. PNG sizes
range from 16 to 1024 pixels. Native assets are ../assets/tag-exif-turbo.icns for
macOS and ../assets/tag-exif-turbo.ico for Windows. Restart to load changed artwork.
The README hero image is readme_hs.png in this directory.

## Approval Workflow

1. Initialize a persistent MCP connection and discover actual tools and schemas.
2. Resolve the saved set, optional configured preference, or first available set.
3. Load one image with previews enabled at the saved offset or offset 0 for a new
  review. Verify a restored image's ID and path before restoring its draft.
4. Display the actual preview and send its complete encoded bytes to Ollama.
5. Validate and display 5-10 distinct, meaningful, searchable suggested tags.
6. Wait for explicit user review: edit, regenerate, apply or skip.
7. Advance only after the approval decision has been resolved.

Previous, Next, changing sets or service configuration, and Quit must resolve a
pending review through Apply, Skip without writing, or Cancel. Regenerate does not
write or advance. Existing tags are read-only; removing a suggestion does not
remove stored metadata. Revisiting a resolved review does not automatically
reanalyze or write it.

Exception: Previous and Next remain available during ANALYZING. Navigating then
defers the review without an approval dialog, preserves any existing draft, and
invalidates the old operation token. Late tags, errors and model-health messages
for that image are ignored. Returning to a deferred analysis restarts it while
preserving draft tags. Image-preview loads and metadata writes remain serialized;
navigation stays disabled during those operations and during uncertain writes.

State names: DISCONNECTED, READY, LOADING_IMAGE, ANALYZING, AWAITING_APPROVAL,
APPLYING_TAGS, ERROR and COMPLETED. The Python controller owns offsets, approval
and processing order; the language model never receives or invokes MCP tools.

## MCP and Image Handling

Discovered schemas are validated before tool calls; parameters and response
formats are not invented. The known Exif Turbo capabilities are list_image_sets,
get_image_set_images, preview resources, and set_custom_tags_batch. The selection-
relative add_custom_tags tool is not a safe substitute for indexed-image writes.

Apply requires explicit approval and a safe identity-addressed writer. It submits
one append update containing image ID and path. Existing tags are preserved.
Exif Turbo updates its sidecar and index, not the original image file.

Transport success is insufficient: per-image success and returned identity must
match. Failed or interrupted writes remain pending/uncertain. Retry first rereads
the target's existing tags without replaying a write. Another explicit Apply is
required. Changed or unverifiable identities fail closed.

Supported image inputs include MCP ImageContent, inline base64, preview resources,
accessible HTTP(S) URLs and local files. MCP JPEG previews are preferred. Preview
data is limited to 32 MiB and 100 megapixels; unsupported Qt codecs produce a
recoverable error. Original RAW decoding is not implemented. When MCP supplies
a JPEG preview, inference uses its complete bytes, not the original RAW file.

Decoded previews are held in a bounded QQuickImageProvider cache with revision-
specific URLs. Preview files are not permanently saved.

## Ollama Analysis

Use Ollama's native /api/chat vision API with the exact configured model. Check
model availability and advertised vision capability before inference. Supply
complete base64 image data and a Pydantic-derived tags-only JSON schema. Validate
5-10 nonempty, normalized, case-insensitively distinct tags.

The prompt requires factual visual evidence and forbids inferred identities,
named locations, events, dates or private traits. Requests bound the context to
4,096 tokens and generation to 256 tokens. Hallucination avoidance is a prompt
constraint, not a factuality guarantee; human review remains mandatory.

## Concurrency and Persistence

AppController is a GUI-thread QObject exposing reactive properties and slots.
QAbstractListModel instances represent images and tags. Only the GUI thread
mutates these objects.

A dedicated QThread runs one asyncio loop with a sequential MCP/journal command
queue. The owning coroutine retains the persistent MCP session context. Ollama
inference runs in a separate asyncio task so preview loads do not wait for it.
There is at most one active inference and one replaceable pending request for
the latest selected image; intermediate requests are not accumulated. Queued Qt
signals return results, and stale operation tokens are ignored. Network access,
decoding and journal operations run off the GUI thread. Requests have deadlines;
connection attempts are bounded. Shutdown cancels foreground and background work
before closing clients and the journal.

QSettings stores theme, geometry, splitter ratio and service preferences. A
versioned SQLite journal under QStandardPaths.AppDataLocation stores progress,
draft tags and uncertain writes. Identity includes endpoint, set, image ID and
path; offsets are not sufficient identity. Settings can reset local progress
without changing stored image tags. The journal contains local paths and tags,
but never preview bytes.

## Keyboard Shortcuts

| Action | Shortcut |
| --- | --- |
| Previous / Next | Alt+Left / Alt+Right |
| Apply | Ctrl+Return |
| Regenerate | Ctrl+R |
| Settings | Ctrl+, |
| Quit | Platform-standard Quit bindings |

Image-navigation shortcuts are suppressed while editing text.

## Verification

Run `.venv/bin/python -m pytest -q` after installing the dev extra. Focused tests
cover workflow safety, schema handling, image bytes, tag notifications, controller
guards, persistence, stale results, QML resizing and icon assets.

Offline QML smoke check:
`QT_QPA_PLATFORM=offscreen .venv/bin/python main.py --smoke`

Read-only real-service integration check:
`QT_QPA_PLATFORM=offscreen .venv/bin/python main.py --live-check --screenshot artifacts/live.png`

For a repeatable sample test, create a set named smoke-test and explicitly set
DEFAULT_IMAGE_SET=smoke-test. That name is only an example, not a startup
requirement. An empty DEFAULT_IMAGE_SET selects the first available set when
there is no saved review. Saved progress takes priority over this preference;
use a fresh journal or explicitly reset progress in Settings to test the sample
instead of resuming another set. The offline smoke check needs no set or services.

Smoke mode makes no network requests. Live-check requires fresh real inference,
stores the resulting local draft, and exits without writing image metadata. It
may take up to four minutes. Captures include user images and metadata; inspect
them before publishing. The ignored artifacts directory is not documentation.

## Troubleshooting

- MCP unavailable: unlock Exif Turbo, enable MCP, check the port and reconnect.
  Diagnostics exposes discovered tool schemas.
- Model missing: manually run the exact ollama pull command shown by the app.
- Inference timeout: inspect ollama ps and memory pressure. An oversized context
  in another loaded model can block inference; unload it yourself if appropriate.
- Changed database or set: verify the intended database, then reset local progress
  in Settings if identity reconciliation cannot safely restore it.
- Unsupported preview: use an MCP JPEG/resource preview or another Qt-readable
  file within the size limits.