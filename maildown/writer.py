"""Write converted email to files."""

from pathlib import Path

from maildown.converter import AttachmentMode, ConversionOptions, convert_to_markdown, generate_filename
from maildown.parser import ParsedEmail


def write_markdown(
    email: ParsedEmail,
    output_path: Path,
    options: ConversionOptions | None = None,
) -> Path:
    """Write email as Markdown file.

    Args:
        email: Parsed email data.
        output_path: Path to output file (including .md extension).
        options: Conversion options.

    Returns:
        Path to written file.
    """
    if options is None:
        options = ConversionOptions()

    # Handle attachment extraction
    attachment_base_path = None
    if options.attachment_mode in (AttachmentMode.EXTRACT, AttachmentMode.EMBED):
        if email.attachments:
            attachments_dir = output_path.parent / options.attachments_dir / output_path.stem
            attachment_base_path = f"./{options.attachments_dir}/{output_path.stem}"
            _extract_attachments(email, attachments_dir)

    # Convert and write
    markdown = convert_to_markdown(email, options, attachment_base_path)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(markdown, encoding="utf-8")

    return output_path


def _extract_attachments(email: ParsedEmail, output_dir: Path) -> list[Path]:
    """Extract attachments to directory.

    Args:
        email: Parsed email with attachments.
        output_dir: Directory to write attachments to.

    Returns:
        List of paths to extracted files.
    """
    if not email.attachments:
        return []

    output_dir.mkdir(parents=True, exist_ok=True)
    paths = []

    for attachment in email.attachments:
        file_path = output_dir / attachment.filename
        # Handle duplicate filenames
        if file_path.exists():
            stem = file_path.stem
            suffix = file_path.suffix
            counter = 1
            while file_path.exists():
                file_path = output_dir / f"{stem}_{counter}{suffix}"
                counter += 1

        file_path.write_bytes(attachment.content)
        paths.append(file_path)

    return paths


def determine_output_path(
    source_path: Path,
    output_dir: Path | None,
    pattern: str | None,
    email: ParsedEmail,
    preserve_structure: bool = False,
    base_input_dir: Path | None = None,
) -> Path:
    """Determine output file path based on options.

    Args:
        source_path: Path to source EML file.
        output_dir: Output directory (None = same as source).
        pattern: Filename pattern (None = use source filename).
        email: Parsed email for pattern substitution.
        preserve_structure: Whether to preserve directory structure.
        base_input_dir: Base input directory for structure preservation.

    Returns:
        Path for output Markdown file.
    """
    # Generate filename
    if pattern is None:
        # Use source filename with .md extension
        filename = source_path.stem + ".md"
    else:
        filename = generate_filename(email, pattern) + ".md"

    if output_dir is None:
        # Output next to source file
        return source_path.parent / filename

    if preserve_structure and base_input_dir:
        # Preserve relative directory structure
        try:
            relative = source_path.parent.relative_to(base_input_dir)
            return output_dir / relative / filename
        except ValueError:
            # source_path is not relative to base_input_dir
            return output_dir / filename

    return output_dir / filename
