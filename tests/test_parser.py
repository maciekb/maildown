"""Tests for parser module."""

from pathlib import Path

import pytest

from maildown.parser import parse_eml, safe_attachment_name

FIXTURES = Path(__file__).parent / "fixtures"


class TestParseSimpleText:
    def test_extracts_subject(self):
        email = parse_eml(FIXTURES / "simple-text.eml")
        assert email.subject == "Test email"

    def test_extracts_from_address(self):
        email = parse_eml(FIXTURES / "simple-text.eml")
        assert email.from_address == "Jan Kowalski <jan@example.com>"

    def test_extracts_to_address(self):
        email = parse_eml(FIXTURES / "simple-text.eml")
        assert email.to_address == "Anna Nowak <anna@example.com>"

    def test_extracts_date(self):
        email = parse_eml(FIXTURES / "simple-text.eml")
        assert email.date is not None
        assert email.date.year == 2024
        assert email.date.month == 3
        assert email.date.day == 15

    def test_extracts_message_id(self):
        email = parse_eml(FIXTURES / "simple-text.eml")
        assert email.message_id == "<test123@example.com>"

    def test_extracts_body_text(self):
        email = parse_eml(FIXTURES / "simple-text.eml")
        assert "Hello Anna" in email.body_text
        assert "simple test email" in email.body_text

    def test_no_body_html(self):
        email = parse_eml(FIXTURES / "simple-text.eml")
        assert email.body_html is None


class TestParseHtmlOnly:
    def test_extracts_body_html(self):
        email = parse_eml(FIXTURES / "simple-html.eml")
        assert email.body_html is not None
        assert "<h1>Hello Anna</h1>" in email.body_html

    def test_no_body_text(self):
        email = parse_eml(FIXTURES / "simple-html.eml")
        assert email.body_text is None


class TestParseMultipart:
    def test_extracts_both_bodies(self):
        email = parse_eml(FIXTURES / "multipart.eml")
        assert email.body_text is not None
        assert email.body_html is not None

    def test_text_body_is_plain_version(self):
        email = parse_eml(FIXTURES / "multipart.eml")
        assert "plain text version" in email.body_text

    def test_html_body_is_html_version(self):
        email = parse_eml(FIXTURES / "multipart.eml")
        assert "<em>HTML version</em>" in email.body_html


class TestParseAttachments:
    def test_extracts_attachment(self):
        email = parse_eml(FIXTURES / "with-attachment.eml")
        assert len(email.attachments) == 1

    def test_attachment_filename(self):
        email = parse_eml(FIXTURES / "with-attachment.eml")
        assert email.attachments[0].filename == "notes.txt"

    def test_attachment_content(self):
        email = parse_eml(FIXTURES / "with-attachment.eml")
        content = email.attachments[0].content.decode("utf-8")
        assert "notes in the attachment" in content


class TestParseUtf8:
    def test_handles_utf8_body(self):
        email = parse_eml(FIXTURES / "utf8-subject.eml")
        assert "zażółć gęślą jaźń" in email.body_text


class TestFromNameAndEmail:
    def test_from_name(self):
        email = parse_eml(FIXTURES / "simple-text.eml")
        assert email.from_name == "Jan Kowalski"

    def test_from_email(self):
        email = parse_eml(FIXTURES / "simple-text.eml")
        assert email.from_email == "jan@example.com"


class TestErrorHandling:
    def test_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            parse_eml(Path("/nonexistent/file.eml"))


class TestSafeAttachmentName:
    @pytest.mark.parametrize("name", ["report.txt", "image 1.png", "zażółć.txt", "name[1].txt"])
    def test_safe_names_pass_through(self, name):
        assert safe_attachment_name(name, 0) == name

    @pytest.mark.parametrize(
        "name",
        [
            None,
            "",
            ".",
            "..",
            "../../outside.txt",
            "../escape",
            "..\\escape",
            "/absolute",
            "C:\\escape",
            "C:escape",
            "a/b",
            "a\\b",
            "a:b",
            "a\x00b",
        ],
    )
    def test_unsafe_names_use_positional_fallback(self, name):
        assert safe_attachment_name(name, 0) == "attachment_1.bin"

    def test_fallback_uses_index(self):
        assert safe_attachment_name("", 4) == "attachment_5.bin"
