"""Tests for converter module."""

from datetime import datetime, timezone

import pytest

from maildown.converter import (
    AttachmentMode,
    ConversionOptions,
    convert_to_markdown,
    generate_filename,
    slugify,
)
from maildown.parser import Attachment, ParsedEmail


class TestSlugify:
    def test_lowercase(self):
        assert slugify("Hello World") == "hello-world"

    def test_removes_special_chars(self):
        assert slugify("Test: Email!") == "test-email"

    def test_handles_polish_chars(self):
        assert slugify("zażółć gęślą jaźń") == "zazolc-gesla-jazn"

    def test_empty_string(self):
        assert slugify("") == ""

    def test_limits_length(self):
        long_text = "a" * 200
        assert len(slugify(long_text)) <= 100


class TestConvertToMarkdown:
    @pytest.fixture
    def sample_email(self):
        return ParsedEmail(
            subject="Test Subject",
            from_address="Jan <jan@example.com>",
            to_address="Anna <anna@example.com>",
            date=datetime(2024, 3, 15, 10, 30, 0, tzinfo=timezone.utc),
            message_id="<test@example.com>",
            body_text="Hello, this is the body.",
        )

    def test_includes_frontmatter(self, sample_email):
        result = convert_to_markdown(sample_email)
        assert "---" in result
        assert "subject: Test Subject" in result

    def test_includes_title(self, sample_email):
        result = convert_to_markdown(sample_email)
        assert "# Test Subject" in result

    def test_includes_body(self, sample_email):
        result = convert_to_markdown(sample_email)
        assert "Hello, this is the body." in result

    def test_without_frontmatter(self, sample_email):
        options = ConversionOptions(include_frontmatter=False)
        result = convert_to_markdown(sample_email, options)
        # Should not have YAML markers at start
        assert not result.startswith("---")

    def test_prefers_text_by_default(self):
        email = ParsedEmail(
            subject="Test",
            body_text="Plain text",
            body_html="<p>HTML text</p>",
        )
        result = convert_to_markdown(email)
        assert "Plain text" in result
        assert "<p>" not in result

    def test_prefer_html_converts_to_markdown(self):
        email = ParsedEmail(
            subject="Test",
            body_text="Plain text",
            body_html="<p><strong>Bold</strong> text</p>",
        )
        options = ConversionOptions(prefer_html=True)
        result = convert_to_markdown(email, options)
        assert "**Bold**" in result


class TestAttachmentsInMarkdown:
    @pytest.fixture
    def email_with_attachment(self):
        return ParsedEmail(
            subject="Test",
            body_text="Body",
            attachments=[
                Attachment(
                    filename="doc.pdf",
                    content_type="application/pdf",
                    size=1024,
                    content=b"pdf content",
                )
            ],
        )

    def test_list_mode(self, email_with_attachment):
        options = ConversionOptions(attachment_mode=AttachmentMode.LIST)
        result = convert_to_markdown(email_with_attachment, options)
        assert "## Attachments" in result
        assert "doc.pdf (1.0 KB)" in result

    def test_ignore_mode(self, email_with_attachment):
        options = ConversionOptions(attachment_mode=AttachmentMode.IGNORE)
        result = convert_to_markdown(email_with_attachment, options)
        assert "## Attachments" not in result

    def test_extract_mode_with_path(self, email_with_attachment):
        options = ConversionOptions(attachment_mode=AttachmentMode.EXTRACT)
        result = convert_to_markdown(
            email_with_attachment, options, attachment_base_path="./attachments/test"
        )
        assert "[doc.pdf](./attachments/test/doc.pdf)" in result


class TestGenerateFilename:
    @pytest.fixture
    def email(self):
        return ParsedEmail(
            subject="Test Subject",
            from_address="Jan Kowalski <jan@example.com>",
            date=datetime(2024, 3, 15, 10, 30, 0),
        )

    def test_default_pattern(self, email):
        result = generate_filename(email)
        assert result == "2024-03-15-test-subject"

    def test_datetime_pattern(self, email):
        result = generate_filename(email, "{datetime}-{subject}")
        assert result == "2024-03-15T10-30-00-test-subject"

    def test_from_pattern(self, email):
        result = generate_filename(email, "{from}-{subject}")
        assert result == "jan-kowalski-test-subject"

    def test_from_email_pattern(self, email):
        result = generate_filename(email, "{from_email}")
        assert result == "jan@example.com"

    def test_missing_date(self):
        email = ParsedEmail(subject="Test")
        result = generate_filename(email, "{date}-{subject}")
        assert result == "unknown-date-test"

    def test_missing_subject(self):
        email = ParsedEmail(date=datetime(2024, 3, 15))
        result = generate_filename(email, "{date}-{subject}")
        assert result == "2024-03-15-no-subject"
