# Exif Turbo AI Tagger

A native desktop app for reviewing AI-generated image tags and descriptions with
Exif Turbo and Ollama. Edit suggestions, choose embedded metadata exclusions,
approve changes, or skip an image. No OpenWebUI required.

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
The window centers on its screen and opens maximized.
Only one instance runs per signed-in user. Launching again brings the existing
window forward, restoring it if minimized, without starting another review worker.
On Windows the application uses its own taskbar identity and icon rather than Python's.
Optionally set `DEFAULT_IMAGE_SET` to prefer a set when starting without saved progress.
Use the toolbar selector to review an image set or only the image currently
selected in Exif Turbo. The single-image target is checked again before writing.
In current-image mode, click **Reload image** after changing the selection in
Exif Turbo. Pending reviews still require Apply, Skip, or Cancel before reloading.
**Apply Changes saves the entire review only after explicit approval.**
Tags, custom description edits, and embedded metadata exclusion choices remain
local drafts until Apply. Description-only and exclusion-only reviews are supported.
The Tags and Description tabs distinguish saved custom values from embedded
metadata and show the proposed derivative result. Ignore embedded tags individually
or all at once, and ignore the embedded description independently of custom text.
Exclusions affect derivative copies, not original files or source search metadata.
Turning ignore-all off restores individual tag exclusion choices.

Custom tags default to **Merge**, which retains saved tags and adds reviewed ones.
Choose **Replace** to save only the reviewed tags, restoring any saved chips you
want to retain. Removing a saved chip automatically selects Replace while keeping
the other saved tags. Struck-through chips can be restored before Apply.
Removals are staged locally and listed for confirmation when applying; replacing
with an empty custom list clears custom tags. Embedded tags are unaffected by
custom-tag replacement and remain controlled by their separate ignore options.
**Replace All**, beside Replace, saves the reviewed custom-tag list just like Replace.
Embedded-tag exclusions are independent: selecting a tag mode never changes them,
and toggling exclusions never changes the tag mode. All changes still wait for Apply.

AI descriptions are editable proposals. Regenerate never overwrites manual
description edits; Use suggestion and Append change only the draft. Clearing a
saved custom description requires confirmation when applying. In the Description
tab, Generate suggestion requests a description without changing edited tags;
this also works for restored older reviews that have no description proposal.
Skip writes nothing and discards proposed saved-tag removals, description edits,
and exclusion choices.

For context-aware rewriting, click **Regenerate Suggestion with Embedded Context**
in Description. It uses the current embedded caption automatically, with no extra
settings, source selection or context editor. The regular Generate button remains
image-only. Missing embedded text disables the context button; captions over 2,000
characters are rejected rather than silently truncated.
Refinement uses the same model in two stages: visual observations, then a contextual
rewrite. Both stages share the configured inference deadline.

Context and **Ignore embedded description** are independent: an excluded caption
can still supply useful facts for refinement. Supplied names, dates, places and
events may be retained without claiming visual verification. Review notes flag
possible conflicts, but model output still needs your review. Refine changes only
the proposal; Use suggestion or Append updates the draft, and Apply saves it.
Request snapshots are kept in local review history for exact retries. Only the
explicit context button sends embedded text to the configured Ollama endpoint,
which may be remote. The custom draft is not sent as context.

MCP applies the approved fields through separate calls, not an atomic transaction.
If a write is interrupted, some changes may already be saved. Retry rereads metadata
without replaying writes; review the actual state and explicitly Apply again to
finish remaining changes. Description/exclusion controls require the corresponding
MCP tools; older servers can still support tag-only reviews.

Previous and Next stay available during AI analysis; results for images you leave
are discarded without writing metadata, and local drafts are retained.

## Develop

```sh
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m pytest -q
.venv/bin/python main.py --version
```

See [the project specification](docs/project-spec.md) for architecture, workflow,
shortcuts, persistence, live checks, troubleshooting, and versioning.