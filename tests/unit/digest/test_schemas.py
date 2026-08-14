"""Schema validation tests."""

import pytest

from anxious_news_bot.digest.schemas import (
    ContentValidationError,
    validate_composer_response,
)


class TestValidateComposerResponse:
    def test_valid_response(self):
        response = {
            "schema_version": "1.0",
            "items": [
                {"index": 1, "title": "T1", "summary": "S1"},
                {"index": 2, "title": "T2", "summary": "S2"},
            ],
        }
        result = validate_composer_response(response, 2)
        assert len(result) == 2
        assert result[0]["index"] == 1
        assert result[1]["index"] == 2

    def test_wrong_schema_version(self):
        with pytest.raises(ContentValidationError):
            validate_composer_response({"schema_version": "2.0", "items": []}, 0)

    def test_wrong_count(self):
        response = {
            "schema_version": "1.0",
            "items": [{"index": 1, "title": "T", "summary": "S"}],
        }
        with pytest.raises(ContentValidationError, match="expected 2"):
            validate_composer_response(response, 2)

    def test_duplicate_index(self):
        response = {
            "schema_version": "1.0",
            "items": [
                {"index": 1, "title": "T", "summary": "S"},
                {"index": 1, "title": "T2", "summary": "S2"},
            ],
        }
        with pytest.raises(ContentValidationError, match="duplicate"):
            validate_composer_response(response, 2)

    def test_missing_index(self):
        response = {
            "schema_version": "1.0",
            "items": [
                {"index": 1, "title": "T", "summary": "S"},
                {"index": 3, "title": "T2", "summary": "S2"},
            ],
        }
        with pytest.raises(ContentValidationError):
            validate_composer_response(response, 2)

    def test_empty_title(self):
        response = {
            "schema_version": "1.0",
            "items": [{"index": 1, "title": "", "summary": "S"}],
        }
        with pytest.raises(ContentValidationError, match="title"):
            validate_composer_response(response, 1)

    def test_title_too_long(self):
        response = {
            "schema_version": "1.0",
            "items": [{"index": 1, "title": "x" * 501, "summary": "S"}],
        }
        with pytest.raises(ContentValidationError, match="title"):
            validate_composer_response(response, 1)

    def test_rejects_top_level_additional_properties(self):
        response = {
            "schema_version": "1.0",
            "items": [{"index": 1, "title": "T", "summary": "S"}],
            "prompt": "must not be accepted",
        }

        with pytest.raises(ContentValidationError, match="extra"):
            validate_composer_response(response, 1)

    def test_rejects_item_additional_properties(self):
        response = {
            "schema_version": "1.0",
            "items": [
                {
                    "index": 1,
                    "title": "T",
                    "summary": "S",
                    "canonical_url": "https://untrusted.invalid",
                }
            ],
        }

        with pytest.raises(ContentValidationError, match="extra"):
            validate_composer_response(response, 1)

    def test_boolean_is_not_a_valid_index(self):
        response = {
            "schema_version": "1.0",
            "items": [{"index": True, "title": "T", "summary": "S"}],
        }

        with pytest.raises(ContentValidationError, match="index"):
            validate_composer_response(response, 1)

    @pytest.mark.parametrize("field", ["title", "summary"])
    def test_rejects_whitespace_only_content(self, field):
        item = {"index": 1, "title": "T", "summary": "S"}
        item[field] = "   "

        with pytest.raises(ContentValidationError, match=field):
            validate_composer_response(
                {"schema_version": "1.0", "items": [item]},
                1,
            )
