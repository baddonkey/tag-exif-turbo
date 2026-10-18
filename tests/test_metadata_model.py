import pytest

from backend.metadata_model import (
    embedded_description, embedded_tags, included_tags, metadata_matches,
    metadata_operations, metadata_values, normalize_description, proposed_description,
)


def test_embedded_extraction_and_description_composition():
    source = {"XMP-dc:Subject": ["Tree", "sky"], "IPTC:Keywords": "['tree', 'private']",
              "IFD0:ImageDescription": "Caption\r\nline", "XMP-dc:Description": {"en": "Caption\nline", "de": "Bild"}}
    assert embedded_tags(source) == ["private", "sky", "Tree"]
    assert embedded_description(source) == "Caption\nline\n\nBild"
    draft = metadata_values({"description": "Custom", "excluded_embedded_tags": ["PRIVATE"]})
    assert included_tags(source, draft) == ["sky", "Tree"]
    assert proposed_description(source, draft) == "Caption\nline\n\nBild\n\nCustom"
    draft["exclude_embedded_description"] = True
    draft["exclude_all_embedded_tags"] = True
    assert proposed_description(source, draft) == "Custom"
    assert included_tags(source, draft) == []
    assert draft["excluded_embedded_tags"] == ["PRIVATE"]


def test_changed_fields_only_and_explicit_clear():
    baseline = metadata_values({"description": "Saved", "excluded_embedded_tags": ["Private"]})
    assert metadata_operations(baseline, baseline) == []
    draft = {**baseline, "description": "", "exclude_all_embedded_tags": True}
    assert metadata_operations(baseline, draft) == [
        ("set_image_description", {"description": "", "mode": "replace"}),
        ("set_image_all_embedded_tags_excluded", {"excluded": True}),
    ]
    assert metadata_matches(baseline, {**baseline, "excluded_embedded_tags": ["private"]})


def test_description_normalization():
    assert normalize_description(" e\u0301\r\n\tline ") == "\u00e9\n\tline"
    with pytest.raises(ValueError):
        normalize_description("bad\x00text")