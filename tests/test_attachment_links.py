"""Converter link generation for attachment filenames."""

import pytest

from maildown.converter import AttachmentMode, ConversionOptions, convert_to_markdown
from maildown.parser import Attachment, ParsedEmail

UNSAFE_NAMES = [
    "../../outside.txt",
    "../escape",
    "..\\escape",
    "/absolute",
    "C:\\escape",
    "C:escape",
    "a:b",
    "",
    ".",
    "..",
    "a/b",
    "a\\b",
    "a\x00b",
]


def link_url(markdown: str) -> str:
    """Extract the first Markdown link URL."""
    return markdown.split("](", 1)[1].split(")", 1)[0]


@pytest.mark.parametrize(
    "base,expected",
    [
        (None, "./attachments/attachment_1.bin"),
        ("./attachments/mail", "./attachments/mail/attachment_1.bin"),
    ],
)
@pytest.mark.parametrize("name", UNSAFE_NAMES)
def test_extract_unsafe_names_use_positional_fallback_links(name, base, expected):
    email = ParsedEmail(attachments=[Attachment(name, "text/plain", 1, b"x")])
    options = ConversionOptions(attachment_mode=AttachmentMode.EXTRACT)
    markdown = convert_to_markdown(email, options, base)
    assert link_url(markdown) == expected
    assert ".." not in link_url(markdown)


@pytest.mark.parametrize(
    "base,expected",
    [
        (None, "./attachments/attachment_1.bin"),
        ("./attachments/mail", "./attachments/mail/attachment_1.bin"),
    ],
)
@pytest.mark.parametrize("name", UNSAFE_NAMES)
def test_embed_non_embedded_fallback_uses_positional_fallback_links(name, base, expected):
    attachment = Attachment(name, "application/pdf", 10, b"x" * 10)
    email = ParsedEmail(attachments=[attachment])
    options = ConversionOptions(attachment_mode=AttachmentMode.EMBED)
    markdown = convert_to_markdown(email, options, base)
    assert link_url(markdown) == expected
    assert ".." not in link_url(markdown)


@pytest.mark.parametrize("name", ["../../outside.txt", "..\\escape", "a\x00b", ""])
def test_embed_large_image_fallback_uses_positional_fallback_links(name):
    attachment = Attachment(name, "image/png", 100_000, b"x" * 100_000)
    email = ParsedEmail(attachments=[attachment])
    options = ConversionOptions(attachment_mode=AttachmentMode.EMBED)
    markdown = convert_to_markdown(email, options, "./attachments/mail")
    assert link_url(markdown) == "./attachments/mail/attachment_1.bin"


def test_unsafe_name_stays_as_link_label():
    email = ParsedEmail(attachments=[Attachment("../../outside.txt", "text/plain", 1, b"x")])
    options = ConversionOptions(attachment_mode=AttachmentMode.EXTRACT)
    markdown = convert_to_markdown(email, options, "./attachments/mail")
    assert "- [../../outside.txt](./attachments/mail/attachment_1.bin) (1 B)" in markdown


@pytest.mark.parametrize("name", ["../../outside.txt", "safe.txt"])
def test_attachment_path_overrides_win_unchanged(name):
    from urllib.parse import quote

    email = ParsedEmail(attachments=[Attachment(name, "text/plain", 1, b"x")])
    options = ConversionOptions(attachment_mode=AttachmentMode.EXTRACT)
    override = {0: "./attachments/mail/renamed #1.txt"}
    markdown = convert_to_markdown(email, options, "./attachments/mail", override)
    assert link_url(markdown) == quote(override[0], safe="/")


@pytest.mark.parametrize("name", ["report.txt", "image 1.png", "zażółć.txt", "report #%().txt"])
def test_safe_names_keep_filename_links(name):
    from urllib.parse import quote

    email = ParsedEmail(attachments=[Attachment(name, "text/plain", 1, b"x")])
    options = ConversionOptions(attachment_mode=AttachmentMode.EXTRACT)
    markdown = convert_to_markdown(email, options, "./attachments/mail")
    assert link_url(markdown) == quote(f"./attachments/mail/{name}", safe="/")
