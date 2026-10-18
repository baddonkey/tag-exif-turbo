import ast
import unicodedata


DEFAULTS = {
    "description": "",
    "exclude_embedded_description": False,
    "excluded_embedded_tags": [],
    "exclude_all_embedded_tags": False,
}


def metadata_values(record: dict) -> dict:
    return {key: record.get(key, default) for key, default in DEFAULTS.items()}


def normalize_description(value: str) -> str:
    text = unicodedata.normalize("NFC", value.replace("\r\n", "\n").replace("\r", "\n")).strip()
    if any(unicodedata.category(character) == "Cc" and character not in "\n\t" for character in text):
        raise ValueError("Descriptions must not contain control characters.")
    return text


def merge_tags(*groups) -> list[str]:
    labels = {}
    for group in groups:
        for value in group:
            label = str(value).strip()
            if label:
                labels.setdefault(label.casefold(), label)
    return sorted(labels.values(), key=lambda label: (label.casefold(), label))


def embedded_tags(metadata: dict) -> list[str]:
    labels = []
    for key in ("XMP-dc:Subject", "XMP:Subject", "IPTC:Keywords", "XMP-lr:HierarchicalSubject", "XMP:HierarchicalSubject"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip().startswith(("[", "(")):
            try:
                value = ast.literal_eval(value)
            except (SyntaxError, ValueError):
                pass
        candidates = value if isinstance(value, (list, tuple)) else (value,)
        labels.extend(candidate for candidate in candidates if candidate is not None)
    return merge_tags(labels)


def embedded_description(metadata: dict) -> str:
    descriptions = []
    for key, value in metadata.items():
        group, _, name = key.rpartition(":")
        supported = (
            (group in {"IFD0", "IFD1", "EXIF"} and name == "ImageDescription")
            or (group in {"ExifIFD", "EXIF", "XMP-exif", "XMP"} and name == "UserComment")
            or (group == "IPTC" and name == "Caption-Abstract")
            or (group in {"XMP-dc", "XMP", "PNG", "QuickTime", "ItemList", "Keys", "UserData"}
                and (name == "Description" or name.startswith("Description-")))
        )
        if supported:
            for candidate in value.values() if isinstance(value, dict) else (value,):
                if isinstance(candidate, str):
                    text = candidate.replace("\r\n", "\n").replace("\r", "\n").strip()
                    if text and text not in descriptions:
                        descriptions.append(text)
    return "\n\n".join(descriptions)


def proposed_description(metadata: dict, draft: dict) -> str:
    source = "" if draft["exclude_embedded_description"] else embedded_description(metadata)
    return "\n\n".join(text for text in (source, normalize_description(draft["description"])) if text)


def included_tags(metadata: dict, draft: dict) -> list[str]:
    excluded = {tag.casefold() for tag in draft["excluded_embedded_tags"]}
    return [] if draft["exclude_all_embedded_tags"] else [tag for tag in embedded_tags(metadata) if tag.casefold() not in excluded]


def metadata_operations(baseline: dict, draft: dict) -> list[tuple[str, dict]]:
    operations = []
    description = normalize_description(draft["description"])
    if description != normalize_description(baseline["description"]):
        operations.append(("set_image_description", {"description": description, "mode": "replace"}))
    before = {tag.casefold(): tag for tag in baseline["excluded_embedded_tags"]}
    after = {tag.casefold(): tag for tag in draft["excluded_embedded_tags"]}
    for key in sorted(before.keys() ^ after.keys()):
        operations.append(("set_image_embedded_tag_excluded", {"tag": after.get(key, before.get(key)), "excluded": key in after}))
    for field, name in (
        ("exclude_all_embedded_tags", "set_image_all_embedded_tags_excluded"),
        ("exclude_embedded_description", "set_image_description_excluded"),
    ):
        if draft[field] != baseline[field]:
            operations.append((name, {"excluded": draft[field]}))
    return operations


def metadata_matches(actual: dict, expected: dict) -> bool:
    return all(
        {tag.casefold() for tag in actual[key]} == {tag.casefold() for tag in expected[key]}
        if key == "excluded_embedded_tags" else actual[key] == expected[key]
        for key in DEFAULTS
    )