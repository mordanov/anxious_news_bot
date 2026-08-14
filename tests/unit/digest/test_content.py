"""Content service tests."""

import pytest

from anxious_news_bot.digest.services.content import (
    merge_composed_content,
    prepare_composer_inputs,
)
from tests.fixtures.digest import make_ranked_items


class TestPrepareComposerInputs:
    def test_produces_grounding(self):
        items = make_ranked_items(3)
        inputs = prepare_composer_inputs(items)
        assert len(inputs) == 3
        assert inputs[0]["index"] == 1
        assert "grounding" in inputs[0]

    def test_truncates_long_text(self):
        items = make_ranked_items(1)
        items[0]["summary"] = ""
        items[0]["normalized_text"] = "x" * 5000
        inputs = prepare_composer_inputs(items, max_input_chars=100)
        assert len(inputs[0]["grounding"]) == 100

    def test_rejects_more_than_twenty_or_noncontiguous_inputs(self):
        with pytest.raises(ValueError):
            prepare_composer_inputs(make_ranked_items(21))
        items = make_ranked_items(2)
        items[1]["position"] = 3
        with pytest.raises(ValueError, match="contiguous"):
            prepare_composer_inputs(items)


class TestMergeComposedContent:
    def test_merges_correctly(self):
        ranked = make_ranked_items(2)
        composed = (
            {"index": 1, "title": "Localized 1", "summary": "Sum 1"},
            {"index": 2, "title": "Localized 2", "summary": "Sum 2"},
        )
        result = merge_composed_content(composed, ranked)
        assert len(result) == 2
        assert result[0].title == "Localized 1"
        assert result[0].source_name == ranked[0]["source_name"]
        assert result[0].canonical_url == ranked[0]["canonical_url"]
        assert result[0].content_hash  # Non-empty hash

    @pytest.mark.parametrize(
        "composed",
        [
            ({"index": 1, "title": "One", "summary": "One"},),
            (
                {"index": 1, "title": "One", "summary": "One"},
                {"index": 1, "title": "Duplicate", "summary": "Duplicate"},
            ),
            (
                {"index": 1, "title": "One", "summary": "One"},
                {"index": 2, "title": "Two", "summary": "Two"},
                {"index": 3, "title": "Extra", "summary": "Extra"},
            ),
        ],
    )
    def test_rejects_partial_duplicate_or_extra_output(self, composed):
        with pytest.raises(ValueError, match="exactly"):
            merge_composed_content(composed, make_ranked_items(2))
