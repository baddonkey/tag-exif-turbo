import re
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import unquote, urlsplit

from markdown_it import MarkdownIt


def inspect_markdown(path: Path) -> tuple[list[str], set[str]]:
    tokens = MarkdownIt().parse(path.read_text(encoding="utf-8"))
    links = []
    anchors = set()
    duplicates = Counter()
    for index, token in enumerate(tokens):
        if token.type == "heading_open":
            text = tokens[index + 1].content.lower()
            slug = re.sub(r"[^\w -]", "", text).replace(" ", "-")
            count = duplicates[slug]
            anchors.add(f"{slug}-{count}" if count else slug)
            duplicates[slug] += 1
        for child in token.children or []:
            if child.type == "link_open":
                links.append(child.attrGet("href") or "")
            elif child.type == "image":
                links.append(child.attrGet("src") or "")
    return links, anchors


def check_docs(root: Path) -> tuple[int, int]:
    documents = [root / "README.md", *sorted((root / "docs").rglob("*.md"))]
    parsed = {path.resolve(): inspect_markdown(path) for path in documents}
    checked = 0
    for document in documents:
        for link in parsed[document.resolve()][0]:
            parts = urlsplit(link)
            if parts.scheme or parts.netloc:
                continue
            target = (document.parent / unquote(parts.path)).resolve() if parts.path else document.resolve()
            if not target.exists():
                raise ValueError(f"{document.relative_to(root)}: missing link target {link}")
            if parts.fragment and target.suffix == ".md":
                anchors = parsed.get(target, ([], set()))[1]
                if unquote(parts.fragment) not in anchors:
                    raise ValueError(f"{document.relative_to(root)}: missing heading {link}")
            checked += 1
    credits = root / "docs" / "screenshots" / "README.md"
    credited = {(credits.parent / unquote(urlsplit(link).path)).resolve()
                for link in parsed[credits.resolve()][0] if not urlsplit(link).scheme}
    images = [root / "docs" / "readme_hs.png", *sorted((root / "docs" / "screenshots").glob("*.png"))]
    for image in images:
        if image.resolve() not in credited:
            raise ValueError(f"Missing screenshot credit entry: {image.relative_to(root)}")
        if image.read_bytes()[:8] != b"\x89PNG\r\n\x1a\n":
            raise ValueError(f"Invalid PNG: {image.relative_to(root)}")
    return checked, len(images)


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    try:
        links, images = check_docs(root)
    except (OSError, ValueError) as error:
        print(error, file=sys.stderr)
        return 1
    print(f"Validated {links} local links/anchors and {images} credited screenshots.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())