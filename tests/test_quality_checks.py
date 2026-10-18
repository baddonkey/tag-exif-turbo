from pathlib import Path
from types import SimpleNamespace

import pytest
import httpx
import httpx2
from PySide6.QtGui import QColor, QImage
from PySide6.QtQuick import QQuickWindow
from PySide6.QtTest import QTest

import conftest
from scripts.check_docs import check_docs, inspect_markdown


def test_repository_documentation_links_and_image_credits():
    links, images = check_docs(Path(__file__).resolve().parents[1])
    assert links > 0
    assert images > 0


def test_markdown_parser_handles_images_code_and_duplicate_headings(tmp_path):
    document = tmp_path / "example.md"
    document.write_text("# One\n# One\n![Photo](photo.png)\n[Chapter](#one-1)\n```md\n[not a link](absent)\n```\n", encoding="utf-8")
    links, anchors = inspect_markdown(document)
    assert links == ["photo.png", "#one-1"]
    assert anchors == {"one", "one-1"}


def test_documentation_check_rejects_broken_target(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "README.md").write_text("[Missing](missing.md)", encoding="utf-8")
    with pytest.raises(ValueError, match="missing link target"):
        check_docs(tmp_path)


@pytest.mark.asyncio
@pytest.mark.parametrize("module", [httpx, httpx2])
async def test_offline_guard_blocks_unregistered_services(module):
    async with module.AsyncClient() as client:
        with pytest.raises(AssertionError, match="Unexpected network"):
            await client.get("http://127.0.0.1:8765/not-a-test-fixture")


def test_failure_hook_writes_visible_qml_window(gui, monkeypatch, tmp_path, record_ui_failure):
    monkeypatch.setenv("TAGGER_TEST_ARTIFACTS", str(tmp_path))
    window = QQuickWindow()
    window.resize(64, 64)
    window.setColor(QColor("red"))
    window.show()
    QTest.qWait(50)
    try:
        hook = conftest.pytest_runtest_makereport(SimpleNamespace(nodeid="test_ui::failure"), None)
        next(hook)
        with pytest.raises(StopIteration):
            hook.send(SimpleNamespace(get_result=lambda: SimpleNamespace(when="call", failed=True)))
        captures = list(tmp_path.glob("test_ui__failure-*.png"))
        assert captures
        assert not QImage(str(captures[0])).isNull()
        with pytest.raises(RuntimeError, match="simulated"):
            try:
                raise RuntimeError("simulated UI failure")
            finally:
                record_ui_failure()
        assert len(list(tmp_path.glob("*.png"))) >= 2
    finally:
        window.close()