"""Tests for writer module."""

from datetime import datetime
from pathlib import Path

import pytest

from maildown.converter import AttachmentMode, ConversionOptions
from maildown.parser import Attachment, ParsedEmail
from maildown.writer import determine_output_path, write_markdown


class TestWriteMarkdown:
    @pytest.fixture
    def sample_email(self):
        return ParsedEmail(
            subject="Test Email",
            from_address="Jan <jan@example.com>",
            to_address="Anna <anna@example.com>",
            date=datetime(2024, 3, 15, 10, 30, 0),
            body_text="Hello, this is the body.",
        )

    def test_creates_file(self, tmp_path, sample_email):
        output_path = tmp_path / "test.md"
        write_markdown(sample_email, output_path)
        assert output_path.exists()

    def test_creates_parent_dirs(self, tmp_path, sample_email):
        output_path = tmp_path / "nested" / "dir" / "test.md"
        write_markdown(sample_email, output_path)
        assert output_path.exists()

    def test_writes_markdown_content(self, tmp_path, sample_email):
        output_path = tmp_path / "test.md"
        write_markdown(sample_email, output_path)
        content = output_path.read_text()
        assert "# Test Email" in content
        assert "Hello, this is the body." in content


class TestWriteWithAttachments:
    @pytest.fixture
    def email_with_attachment(self):
        return ParsedEmail(
            subject="Test",
            body_text="Body",
            date=datetime(2024, 3, 15),
            attachments=[
                Attachment(
                    filename="test.txt",
                    content_type="text/plain",
                    size=11,
                    content=b"hello world",
                )
            ],
        )

    def test_extract_mode_creates_attachment_file(self, tmp_path, email_with_attachment):
        output_path = tmp_path / "email.md"
        options = ConversionOptions(attachment_mode=AttachmentMode.EXTRACT)
        write_markdown(email_with_attachment, output_path, options)

        attachment_path = tmp_path / "attachments" / "email" / "test.txt"
        assert attachment_path.exists()
        assert attachment_path.read_bytes() == b"hello world"


class TestDetermineOutputPath:
    @pytest.fixture
    def email(self):
        return ParsedEmail(
            subject="Test Email",
            date=datetime(2024, 3, 15),
        )

    def test_output_beside_source(self, email):
        source = Path("/input/email.eml")
        result = determine_output_path(source, None, "{date}-{subject}", email)
        assert result == Path("/input/2024-03-15-test-email.md")

    def test_output_to_directory(self, email):
        source = Path("/input/email.eml")
        output_dir = Path("/output")
        result = determine_output_path(source, output_dir, "{date}-{subject}", email)
        assert result == Path("/output/2024-03-15-test-email.md")

    def test_preserve_structure(self, email):
        source = Path("/input/inbox/2024/email.eml")
        output_dir = Path("/output")
        base_dir = Path("/input")
        result = determine_output_path(
            source, output_dir, "{subject}", email, preserve_structure=True, base_input_dir=base_dir
        )
        assert result == Path("/output/inbox/2024/test-email.md")
