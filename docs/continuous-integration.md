# Quality Checks

Pull requests and pushes to `main` run the Quality and CodeQL workflows. Both can
also be started manually from GitHub Actions and run weekly on Mondays (04:15 and
04:35 UTC respectively). No real Exif Turbo instance, Ollama model, GPU, container
runtime or private database is needed.

## Required Checks

The Quality workflow ends with a stable **CI** status. Add that status to the
repository's branch protection or ruleset for `main`; workflow files alone do not
enable required checks. The CI status fails if any quality or matrix job fails or
is cancelled. Consider requiring the separate **Python security analysis** check
after its first successful GitHub run as well.

| Gate | What it checks |
| --- | --- |
| Python lint | Ruff syntax, undefined names and unused-code diagnostics, without a repository-wide formatting rewrite. |
| Documentation | Local Markdown links, heading anchors, screenshot references, PNG signatures and credit-map coverage. External websites are not requested. |
| Workflow lint | actionlint validates GitHub Actions syntax, expressions and shell snippets. |
| Dependency audit | pip-audit checks installed runtime and development dependencies against known advisories. pip itself is upgraded first. Findings fail the job; no advisories are suppressed. |
| Tests | Offline controller, metadata, persistence, GUI, desktop and transport regressions. |
| Coverage | Branch-aware terminal, XML and HTML reports. Reports establish a baseline; there is no arbitrary percentage threshold yet. |
| Packaging | Wheel and source archive build, Twine metadata checks, resource-content comparisons, fresh wheel installation and installed offline startup. |
| CodeQL | Python security analysis with the security-extended queries. It does not analyze QML as Python. |

## Test Matrix

The complete test suite and package checks run on:

| Runner | Python |
| --- | --- |
| Linux | 3.11, the declared minimum |
| Linux | 3.13 |
| Windows | 3.13 |
| macOS | 3.13 |

Qt uses `QT_QPA_PLATFORM=offscreen` and the Basic controls style. Linux jobs install
Qt runtime libraries and fonts. Native Windows API checks are skipped on other
platforms rather than pretending to validate Windows taskbar behavior there.
The preview-readiness test waits for actual image dimensions with a bounded
deadline instead of assuming asynchronous decoding finishes within 100 ms.
The Windows crash test terminates only its own test process tree, including the
venv redirector's child interpreter.

## Offline Services, Not Full Simulators

Most tests reuse the existing small fakes:

- Ollama client tests use `httpx.MockTransport` to validate complete image bytes,
  schemas, refinement stages, context handling and errors.
- Controller tests record worker commands, so editing and navigation cannot write
  real metadata.
- Worker tests use controlled async fakes for scheduling, cancellation, failures
  between writes and read-only reconciliation.
- Qt tests use generated image buffers and isolated review/settings directories.

The transport tests add real loopback servers on dynamically allocated ports:

- A small MCP SDK server implements just the tools consumed by this application.
  Its image preview is generated in memory, and tags/descriptions/exclusions are
  in-memory state. Tests cover real initialization/discovery, preview decoding,
  older servers without optional writers, replacement/clearing, partial writes,
  reconciliation and changed selected-image identities.
- A deterministic Ollama-shaped HTTP service implements `/api/tags`, `/api/show`
  and `/api/chat`. It validates real HTTP handling and the two-stage refinement
  request sequence without running a model.

An autouse test guard blocks requests from both `httpx` and the MCP SDK's `httpx2`
unless they use a mock transport or a fixture explicitly registers that loopback
endpoint. A forgotten real-service call fails immediately instead of contacting
an installed Exif Turbo instance or downloading a model.

These fixtures test the client contract, not Exif Turbo's encrypted database,
sidecar implementation, or model quality. They are deliberately not full service
replicas. Use the documented read-only live check manually against disposable
sample data when validating a real service/model release; it is not a required
pull-request check.

## Installed-Package Check

`scripts/check_package.py` compares every bundled QML/asset file with the checkout
and verifies the packaged entry point and desktop helper. It creates a fresh venv,
installs the wheel with its runtime dependencies, and runs the installed `--version`
launcher outside the checkout. Offline GUI startup uses the installed entry module
with isolated Qt settings/test data and no source-directory import path.

This catches omissions and stale copied QML that editable-install tests can miss.
The temporary environment and test data are removed after the check. The check
does not read or modify a user's normal review journal or service preferences.
Twine 7 is used because the current Hatch backend emits Metadata 2.5.

## Reports and Failure Diagnosis

Each matrix job uploads JUnit XML, branch-coverage XML/HTML and available synthetic
UI screenshots. Visible QML windows are captured on failed test calls when
`TAGGER_TEST_ARTIFACTS` is set. Built wheel/sdist files are uploaded only after that
matrix job succeeds. Artifacts are retained for seven days.

The dependency audit JSON is uploaded even when findings fail the audit. Start
with the failing step and its report rather than rerunning until a failure vanishes.
Screenshots contain only test-generated data; normal user images and service
credentials are not used by CI.

## Run Locally

With the project venv activated:

```sh
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
python -m ruff check .
python scripts/check_docs.py
python -m pytest -q --cov --cov-report=term-missing --cov-report=xml --cov-report=html:artifacts/coverage --junitxml=artifacts/junit.xml
python -m build
python -m twine check dist/*
python scripts/check_package.py dist
python -m pip_audit --local --progress-spinner off
```

Install actionlint separately or use the same pinned Go command as the workflow:

```sh
go install github.com/rhysd/actionlint/cmd/actionlint@v1.7.7
actionlint
```

Use a disposable venv for quality work if you do not want development-tool
installation to affect your normal environment. No production server should be
required for any command above.

## Workflow Security and Updates

Actions are pinned to verified full commit SHAs. Checkout does not persist Git
credentials. The default token is read-only; only the CodeQL analysis job receives
`security-events: write`. Workflows use `pull_request`, not a privileged
`pull_request_target` checkout. Jobs have timeouts and superseded runs are cancelled.

Dependabot opens weekly pull requests for Python dependencies and Actions pins;
it does not merge them automatically. Compatible Python updates are grouped, and
major updates remain separate for review. Enable Dependabot alerts and automatic
security-update PRs in repository settings if they are not already enabled.

The workflows need their first GitHub run before cross-platform behavior and
CodeQL uploads can be confirmed. Local Windows validation cannot certify macOS or
Linux runner behavior, and CodeQL itself runs on GitHub rather than inside pytest.