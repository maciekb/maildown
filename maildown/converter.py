"""Convert parsed email to Markdown format."""

import base64
import re
import unicodedata
from dataclasses import dataclass
from enum import Enum
from urllib.parse import quote

from markdownify import markdownify

from maildown.parser import Attachment, ParsedEmail, safe_attachment_name


class AttachmentMode(Enum):
    """How to handle attachments."""

    IGNORE = "ignore"
    LIST = "list"
    EXTRACT = "extract"
    EMBED = "embed"


@dataclass
class ConversionOptions:
    """Options for converting email to Markdown."""

    prefer_html: bool = False
    include_frontmatter: bool = True
    include_headers: list[str] | None = None  # None = all standard headers
    attachment_mode: AttachmentMode = AttachmentMode.LIST
    attachments_dir: str = "attachments"

    def __post_init__(self):
        if self.include_headers is None:
            self.include_headers = ["from", "to", "date", "subject", "cc", "message_id"]


def slugify(text: str) -> str:
    """Convert text to URL-friendly slug, preserving UTF-8 characters.

    Args:
        text: Text to convert.

    Returns:
        Slugified text.
    """
    if not text:
        return ""
    # Normalize unicode (NFC for consistent representation)
    text = unicodedata.normalize("NFC", text)
    # Convert to lowercase
    text = text.lower()
    # Replace any non-word characters (except hyphens) with hyphens
    # \w with re.UNICODE includes letters from all languages
    text = re.sub(r"[^\w-]+", "-", text, flags=re.UNICODE)
    # Replace underscores with hyphens
    text = text.replace("_", "-")
    # Collapse multiple hyphens
    text = re.sub(r"-+", "-", text)
    # Remove leading/trailing hyphens
    text = text.strip("-")
    # Limit length
    return text[:100] if len(text) > 100 else text


def format_size(size_bytes: int) -> str:
    """Format file size in human-readable format."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f} MB"


def convert_to_markdown(
    email: ParsedEmail,
    options: ConversionOptions | None = None,
    attachment_base_path: str | None = None,
    attachment_paths: dict[int, str] | None = None,
) -> str:
    """Convert parsed email to Markdown format.

    Args:
        email: Parsed email data.
        options: Conversion options.
        attachment_base_path: Base path for attachment links (used with extract mode).
        attachment_paths: Final relative paths by zero-based attachment position;
            overrides filename-derived links. Pass unquoted paths (URLs are quoted here).

    Returns:
        Markdown formatted string.
    """
    if options is None:
        options = ConversionOptions()

    parts = []

    # Build frontmatter
    if options.include_frontmatter:
        metadata = _build_frontmatter(email, options)
        fm_lines = ["---"]
        for key, value in metadata.items():
            # Quote values that contain special YAML characters
            if any(
                c in str(value)
                for c in [":", "<", ">", "[", "]", "{", "}", "#", "&", "*", "!", "|", "'", '"']
            ):
                # Use double quotes and escape internal quotes
                escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
                fm_lines.append(f'{key}: "{escaped}"')
            else:
                fm_lines.append(f"{key}: {value}")
        fm_lines.append("---")
        parts.append("\n".join(fm_lines))

    # Add title
    if email.subject:
        parts.append(f"\n# {email.subject}\n")

    # Add body
    body = _get_body(email, options)
    if body:
        parts.append(body)

    # Add attachments section
    if email.attachments and options.attachment_mode != AttachmentMode.IGNORE:
        attachments_md = _format_attachments(
            email.attachments, options, attachment_base_path, attachment_paths
        )
        if attachments_md:
            parts.append(attachments_md)

    return "\n".join(parts)


def _build_frontmatter(email: ParsedEmail, options: ConversionOptions) -> dict:
    """Build frontmatter metadata dictionary."""
    metadata = {}
    headers = options.include_headers or []

    if "date" in headers and email.date:
        metadata["date"] = email.date.isoformat()
    if "from" in headers and email.from_address:
        metadata["from"] = email.from_address
    if "to" in headers and email.to_address:
        metadata["to"] = email.to_address
    if "subject" in headers and email.subject:
        metadata["subject"] = email.subject
    if "cc" in headers and email.cc:
        metadata["cc"] = email.cc
    if "bcc" in headers and email.bcc:
        metadata["bcc"] = email.bcc
    if "message_id" in headers and email.message_id:
        metadata["message_id"] = email.message_id

    return metadata


def _get_body(email: ParsedEmail, options: ConversionOptions) -> str:
    """Get email body, converting HTML if needed."""
    if not options.prefer_html and email.body_text:
        return email.body_text
    if email.body_html:
        return markdownify(email.body_html, heading_style="ATX", strip=["script", "style"])
    return email.body_text or ""


def _attachment_link_path(
    index: int,
    attachment: Attachment,
    options: ConversionOptions,
    base_path: str | None,
    attachment_paths: dict[int, str] | None,
) -> str:
    """Return the unquoted link path for a non-embedded attachment.

    A caller-supplied override always wins unchanged. Otherwise the filename
    gets the same safety fallback used when extracting, so links never point
    outside the attachment directory.
    """
    override = (attachment_paths or {}).get(index)
    if override is not None:
        return override
    name = safe_attachment_name(attachment.filename, index)
    if base_path:
        return f"{base_path}/{name}"
    return f"./{options.attachments_dir}/{name}"


def _format_attachments(
    attachments: list[Attachment],
    options: ConversionOptions,
    base_path: str | None,
    attachment_paths: dict[int, str] | None = None,
) -> str:
    """Format attachments section."""
    lines = ["\n## Attachments\n"]

    for index, att in enumerate(attachments):
        size_str = format_size(att.size)
        label = att.filename.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")

        if options.attachment_mode == AttachmentMode.LIST:
            lines.append(f"- {att.filename} ({size_str})")

        elif should_embed(att, options):
            encoded = base64.b64encode(att.content).decode("ascii")
            lines.append(f"\n![{label}](data:{att.content_type};base64,{encoded})\n")

        elif options.attachment_mode in (AttachmentMode.EXTRACT, AttachmentMode.EMBED):
            link_path = _attachment_link_path(index, att, options, base_path, attachment_paths)
            link_path = quote(link_path, safe="/")
            lines.append(f"- [{label}]({link_path}) ({size_str})")

    return "\n".join(lines)


def should_embed(attachment: Attachment, options: ConversionOptions) -> bool:
    """Embed only images strictly smaller than 100,000 decoded bytes."""
    return (
        options.attachment_mode == AttachmentMode.EMBED
        and attachment.content_type.startswith("image/")
        and attachment.size < 100_000
    )


def generate_filename(email: ParsedEmail, pattern: str = "{date}-{subject}") -> str:
    """Generate output filename from pattern.

    Supported placeholders:
        - {date}: Date in YYYY-MM-DD format
        - {datetime}: Date and time in YYYY-MM-DDTHH-MM-SS format
        - {subject}: Slugified subject
        - {from}: Slugified sender name
        - {from_email}: Sender email address

    Args:
        email: Parsed email data.
        pattern: Filename pattern with placeholders.

    Returns:
        Generated filename (without extension).
    """
    replacements = {
        "{date}": email.date.strftime("%Y-%m-%d") if email.date else "unknown-date",
        "{datetime}": email.date.strftime("%Y-%m-%dT%H-%M-%S") if email.date else "unknown-date",
        "{subject}": slugify(email.subject) if email.subject else "no-subject",
        "{from}": slugify(email.from_name) if email.from_name else "unknown-sender",
        "{from_email}": email.from_email or "unknown@email",
    }

    result = pattern
    for placeholder, value in replacements.items():
        result = result.replace(placeholder, value)

    # Sanitize any remaining invalid filename characters
    result = re.sub(r'[<>:"/\\|?*]', "-", result)

    return result
