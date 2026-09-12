"""Parse EML files into structured data."""

from dataclasses import dataclass, field
from datetime import datetime
from email import policy
from email.parser import BytesParser
from email.utils import parsedate_to_datetime
from pathlib import Path


@dataclass
class Attachment:
    """Represents an email attachment."""

    filename: str
    content_type: str
    size: int
    content: bytes


@dataclass
class ParsedEmail:
    """Represents a parsed email message."""

    subject: str | None = None
    from_address: str | None = None
    to_address: str | None = None
    cc: str | None = None
    bcc: str | None = None
    date: datetime | None = None
    message_id: str | None = None
    body_text: str | None = None
    body_html: str | None = None
    attachments: list[Attachment] = field(default_factory=list)

    @property
    def from_name(self) -> str | None:
        """Extract name from 'Name <email>' format."""
        if not self.from_address:
            return None
        if "<" in self.from_address:
            return self.from_address.split("<")[0].strip().strip('"')
        return None

    @property
    def from_email(self) -> str | None:
        """Extract email from 'Name <email>' format."""
        if not self.from_address:
            return None
        if "<" in self.from_address and ">" in self.from_address:
            start = self.from_address.index("<") + 1
            end = self.from_address.index(">")
            return self.from_address[start:end]
        return self.from_address


def parse_eml(path: Path) -> ParsedEmail:
    """Parse an EML file and return structured data.

    Args:
        path: Path to the EML file.

    Returns:
        ParsedEmail with extracted data.

    Raises:
        FileNotFoundError: If the file doesn't exist.
        ValueError: If the file cannot be parsed as email.
    """
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    with open(path, "rb") as f:
        msg = BytesParser(policy=policy.default).parse(f)

    result = ParsedEmail()

    # Extract headers
    result.subject = msg.get("Subject")
    result.from_address = msg.get("From")
    result.to_address = msg.get("To")
    result.cc = msg.get("Cc")
    result.bcc = msg.get("Bcc")
    result.message_id = msg.get("Message-ID")

    # Parse date
    date_str = msg.get("Date")
    if date_str:
        try:
            result.date = parsedate_to_datetime(date_str)
        except (ValueError, TypeError):
            result.date = None

    # Extract body and attachments
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            disposition = part.get_content_disposition()

            if disposition == "attachment":
                _extract_attachment(part, result)
            elif content_type == "text/plain" and result.body_text is None:
                result.body_text = _get_text_content(part)
            elif content_type == "text/html" and result.body_html is None:
                result.body_html = _get_text_content(part)
    else:
        content_type = msg.get_content_type()
        if content_type == "text/plain":
            result.body_text = _get_text_content(msg)
        elif content_type == "text/html":
            result.body_html = _get_text_content(msg)

    return result


def _get_text_content(part) -> str | None:
    """Extract text content from email part."""
    try:
        content = part.get_content()
        if isinstance(content, str):
            return content
        if isinstance(content, bytes):
            try:
                return content.decode("utf-8")
            except UnicodeDecodeError:
                return content.decode("latin-1")
    except Exception:
        return None


def attachment_fallback_name(index: int) -> str:
    """Deterministic filename for a zero-based attachment position."""
    return f"attachment_{index + 1}.bin"


_WINDOWS_RESERVED = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{number}" for number in range(1, 10)),
        *(f"LPT{number}" for number in range(1, 10)),
    }
)


def _is_portable_filename(name: str) -> bool:
    """Report whether *name* is a portable filename on Windows and POSIX."""
    if name.split(".")[0].upper() in _WINDOWS_RESERVED:
        return False
    if name != name.rstrip(". "):
        return False
    return not any(char in name for char in '<>"|?*')


def safe_attachment_name(name: str | None, index: int) -> str:
    """Return *name* unchanged when it is a portable filename, else the fallback.

    Names that are empty, dot/dot-dot, contain path separators, a colon, or a
    NUL byte, Windows-reserved device names (``CON``, ``COM1``…, with or
    without an extension), the forbidden characters ``< > " | ? *``, or a
    trailing dot or space cannot be used as a portable filename and get the
    deterministic ``attachment_<1-based-position>.bin`` fallback for *index*.
    """
    if (
        not name
        or name in (".", "..")
        or any(c in name for c in "/\\:\x00")
        or not _is_portable_filename(name)
    ):
        return attachment_fallback_name(index)
    return name


def _extract_attachment(part, result: ParsedEmail) -> None:
    """Extract attachment from email part."""
    filename = part.get_filename() or attachment_fallback_name(len(result.attachments))
    content_type = part.get_content_type()

    try:
        content = part.get_payload(decode=True)
        if content is None:
            content = b""
    except Exception:
        content = b""

    result.attachments.append(
        Attachment(
            filename=filename,
            content_type=content_type,
            size=len(content),
            content=content,
        )
    )
