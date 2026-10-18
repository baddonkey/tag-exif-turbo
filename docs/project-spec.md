# Exif Turbo AI Tagger: Project Specification

## Scope

A native desktop application for reviewing and approving AI-generated image tags
and descriptions, with embedded metadata exclusion controls.
All visual interface elements use Qt Quick/QML, Qt Quick Controls 2, Layouts and
Dialogs. Python uses PySide6 and QQmlApplicationEngine. There is no Qt Widgets UI,
browser frontend, web server or OpenWebUI dependency.

Custom descriptions can be replaced or cleared after explicit approval. Embedded
tags and descriptions can be excluded from derivative copies, never modified in
originals or removed from source search metadata. Existing custom tags are
preserved in Merge and can be explicitly removed in Replace. Bulk autonomous approval, installers, signing and notarization are
outside the current scope.

## Runtime and Configuration

- Python minimum: 3.11; verified environment: Python 3.14.6 on macOS.
- Runtime dependencies and exact versions: ../pyproject.toml.
- Development dependencies: the optional `dev` extra, installed with
  `.venv/bin/python -m pip install -e '.[dev]'`.
- Exif Turbo MCP: http://127.0.0.1:8765/mcp.
- Ollama API: http://127.0.0.1:11434.
- Default vision model: qwen3-vl:4b-instruct-q8_0.
- Startup target: restore saved progress, otherwise use the optional
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

The ApplicationWindow contains a toolbar with service status, image-source selector
(an image set or the current Exif Turbo selection as a single-image target),
image index, progress and settings; a horizontal resizable SplitView; and an
action bar with Previous, Next, Regenerate, Skip, Apply Changes and Quit.

The viewer preserves aspect ratio, fits the available space, supports wheel and
pinch zoom up to 12x, and permits dragging when enlarged. Original image dimensions
from metadata are distinguished from the decoded preview dimensions.

The review panel shows model readiness and Tags, Description and Metadata tabs.
Tags contains editable suggestions, custom tag input, removable saved custom tags,
embedded keyword pills, and an Ignore all embedded tags switch. Clicking an
embedded pill anywhere, including its x, toggles its ignored state and strike-through without removing
the pill; clicking again restores inclusion. These toggles remain local until Apply.
The Merge/Replace/Replace All radio group defaults to Merge for new reviews. Merge preserves saved
custom tags and adds reviewed suggestions. Selecting Replace uses the reviewed
suggestions plus saved chips explicitly restored for retention. Removing a saved
chip automatically switches to Replace but retains the other saved chips. A removed
chip is struck through and can be restored. Removing a saved tag also removes a
case-insensitive duplicate suggestion so it cannot be silently re-added.
Apply lists removed custom tags for confirmation, including when approving navigation.
Replacing with an empty list intentionally clears custom tags. These choices remain
local drafts until the unified Apply; Skip discards saved-tag removal choices.
Replace All has the same custom-tag replacement semantics as Replace, on the current
image only. Every tag mode is independent of embedded-tag exclusions: changing modes
does not alter exclusion choices, and toggling exclusions does not change modes.
Replace All requires only custom-tag replacement capability. Restored drafts preserve
their explicit exclusion values; legacy ignore-restoration fields are no longer used.
Replace All is not a bulk operation and does not affect descriptions.
Ignore-all takes precedence without erasing individual exclusions. Excluding an
embedded tag does not remove a same-named custom tag.
Description contains a multiline custom draft, AI proposal with Use/Append actions,
and Generate suggestion, which requests a fresh description without replacing tag
suggestions. This is available even when restoring an older tags-only review.
Description-only analysis retains its scope on Retry and deferred-analysis restore.
It also shows read-only embedded text and an Ignore embedded description switch. Enter inserts
a newline; there is no focus-loss autosave or separate metadata Save. Replacing
nonempty draft text with a proposal and applying a cleared saved description require
confirmation. Ignored source values remain inspectable with strike-through.
Current custom tags appear first in the Tags view, above Merge/Replace and suggestions.
The read-only Custom tags to save preview shows the exact pending custom-tag list as
pills, without embedded keywords, and reflects removals, restoration and empty results.
The Tags preview ends with Proposed derivative tags, combining reviewed custom tags
and included embedded keywords. Description retains its derivative description preview;
Metadata displays only raw image metadata.
These previews reflect draft changes, not persisted results, and remain outside the
tab's scrolling content. Embedded text extraction and composition match Exif Turbo's
export behavior, including XMP language variants and IFD0 descriptions.
The QML Theme singleton owns
dark/light colors, typography and spacing. Dropdown text has explicit theme-aware
contrast. The saved normal window size and initial splitter preferences are restored
once at startup. The launcher then centers the normal window in its screen's
available area and opens it maximized. Image and set changes must preserve the
user's current dimensions and window state.

The launcher acquires a per-user QLockFile in AppDataLocation and starts a
user-restricted QLocalServer before creating any controller, worker or journal.
Later launches notify that server to activate the existing window and exit
without starting another review. A minimized window is restored maximized; a
normal or maximized window retains its state. Live owners are never evicted due
to elapsed lock age. Qt recovers locks left by crashed processes, and normal
shutdown closes the server and releases the lock. A failed lock or listener is
reported rather than launching without protection. Smoke/live-check modes refuse
to run beside an existing instance instead of claiming a successful diagnostic.

On Windows, ExifTurbo.AITagger is set as the explicit process AppUserModelID before
QGuiApplication is created. The application icon is also assigned directly to the
QML window, keeping taskbar identity and branding separate from the Python host.

Application icons use lens-and-tag artwork on opaque white backgrounds. PNG sizes
range from 16 to 1024 pixels. Native assets are ../assets/tag-exif-turbo.icns for
macOS and ../assets/tag-exif-turbo.ico for Windows. Restart to load changed artwork.
The README hero image is readme_hs.png in this directory.

## Approval Workflow

1. Initialize a persistent MCP connection and discover actual tools and schemas.
2. Resolve the saved target, optional configured set preference, or first
  available set.
3. Load one image with previews enabled at the saved offset or offset 0 for a new
  set review. In current-image mode, load the image selected in Exif Turbo. Verify
  a restored image's ID and path before restoring its draft.
4. Display the actual preview and send its complete encoded bytes to Ollama.
5. Validate and display 5-10 distinct, meaningful tags and a factual description.
6. Wait for explicit user review: edit, regenerate, apply or skip.
7. Advance only after the approval decision has been resolved.

Previous, Next, changing sets or service configuration, and Quit must resolve a
pending review through Apply, Skip without writing, or Cancel. Regenerate does not
write or advance. All description and exclusion edits remain local until the same
Apply Changes approval used for tags. Apply may contain only description or exclusion
changes and does not require Ollama to be available. Skip makes no MCP writes and
discards proposed saved-tag removals and description/exclusion edits. In Merge,
removing a suggestion does not remove a saved tag. In Replace, only retained saved
tags and reviewed suggestions are written after confirmation. Revisiting a resolved review does not automatically
reanalyze or write it. Initial analysis can populate an empty untouched custom draft;
saved, manually edited or intentionally cleared descriptions are never overwritten
by inference. Regenerate offers a new description proposal instead.
An unfinished analysis restarts when restored; metadata-only drafts do not trigger
inference solely because tags are empty. Legacy tag-only journal documents remain
readable. If Ollama or the configured vision model is unavailable, the app reports
the reason; Retry reconnects services.

Exception: Previous and Next remain available during ANALYZING. Navigating then
defers the review without an approval dialog, preserves any existing draft, and
invalidates the old operation token. Late tags, errors and model-health messages
for that image are ignored. Returning to a deferred analysis restarts it while
preserving draft tags, description and exclusions. Image-preview loads and metadata writes remain serialized;
navigation stays disabled during those operations and during uncertain writes.

State names: DISCONNECTED, READY, LOADING_IMAGE, ANALYZING, AWAITING_APPROVAL,
APPLYING_TAGS, ERROR and COMPLETED. The Python controller owns offsets, approval
and processing order; the language model never receives or invokes MCP tools.
APPLYING_TAGS is retained internally for compatibility and covers the full metadata
write sequence, while the UI uses metadata-oriented status messages.

## MCP and Image Handling

Discovered schemas are validated before tool calls; parameters and response
formats are not invented. The known Exif Turbo capabilities are list_image_sets,
get_image_set_images, preview resources, and set_custom_tags_batch.
Current-image mode is available when the optional get_selected_image tool is
present; it loads the selection through that tool and rechecks its ID and path
before writing. The selection-relative add_custom_tags tool is not a safe
substitute for indexed-image writes.

New optional capabilities are set_image_description, set_image_description_excluded,
set_image_embedded_tag_excluded and set_image_all_embedded_tags_excluded. Discovery
validates each separately without calling any mutating tool. Unsupported controls
are disabled; Apply is gated only by writers required for actual pending changes.
Both selected-image and set-image reads retain description, exclude_embedded_description,
excluded_embedded_tags and exclude_all_embedded_tags. free_tags and description are
custom sidecar values; embedded values come from metadata.

Apply requires explicit approval and safe identity-addressed writers. It appends
new custom tags in Merge or replaces the custom list in Replace, replaces changed custom description text (empty clears it), then
applies changed individual/all-tag and description exclusion flags. All calls
include image ID and path. Unchanged fields are not written. Tag replacement
capability is discovered separately, including support for an empty list.
Replace checks the saved custom-tag baseline before writing and requires exact
case-insensitive tag-set readback, not just the presence of requested labels.
A replacement already confirmed by readback is not replayed after interruption.
Mode, retained saved tags, target and baseline are journaled with the review;
legacy drafts default to Merge. Exif Turbo updates its sidecar and index, not the original image.
Metadata is reread before applying to detect conflicting external field edits;
current-image selection is rechecked before each write. No client-supplied revision
or combined transaction is exposed, so this is not an atomic multi-field save.

Transport success is insufficient: per-image success and returned identity must
match, and final readback must confirm every requested field. Write intent is saved
before the first mutation and progress is journaled after acknowledgements. Failed
or interrupted sequences remain uncertain and never advance. Some operations may
already have succeeded; Retry first rereads tags, description and exclusions without
replaying writes. Review the actual saved values and explicitly Apply again to finish
remaining differences. Confirmed writes are not repeated. Skip/navigation remain
blocked until reconciliation. Changed or unverifiable identities fail closed.

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
complete base64 image data and a Pydantic-derived JSON schema containing tags and
description. Validate 5-10 nonempty, normalized, case-insensitively distinct tags and
a nonempty description of at most 2,000 characters. Request 1-3 concise factual
sentences. Normalize descriptions to NFC, LF line endings and trimmed boundaries;
preserve internal tabs/newlines and reject other control characters.

The prompt requires factual visual evidence and forbids inferred identities,
named locations, events, dates or private traits. Requests bound the context to
4,096 tokens and generation to 512 tokens. Hallucination avoidance is a prompt
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
draft tags, custom description, AI proposal, exclusion choices, saved baseline and
uncertain multi-operation write intent. The existing JSON document storage remains
compatible with older tag-only reviews. Identity includes endpoint, set, image ID and
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