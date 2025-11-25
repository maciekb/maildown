"""Command-line interface for maildown."""

import glob
import sys
from dataclasses import dataclass
from pathlib import Path

import click

from maildown import __version__
from maildown.converter import AttachmentMode, ConversionOptions
from maildown.parser import parse_eml
from maildown.writer import determine_output_path, write_markdown


@dataclass
class ProcessingResult:
    """Result of processing files."""

    success: int = 0
    errors: list[tuple[Path, str]] = None

    def __post_init__(self):
        if self.errors is None:
            self.errors = []


def collect_files(inputs: tuple[str, ...], recursive: bool) -> list[Path]:
    """Collect all EML files to process.

    Args:
        inputs: Input paths or glob patterns.
        recursive: Whether to search recursively.

    Returns:
        List of EML file paths.
    """
    files = []

    for input_path in inputs:
        path = Path(input_path)

        if path.is_file():
            files.append(path)
        elif path.is_dir():
            pattern = "**/*.eml" if recursive else "*.eml"
            files.extend(path.glob(pattern))
        elif "*" in input_path or "?" in input_path:
            # Glob pattern
            if recursive:
                matches = glob.glob(input_path, recursive=True)
            else:
                matches = glob.glob(input_path)
            files.extend(Path(m) for m in matches if Path(m).is_file())
        else:
            # Path doesn't exist - will be handled as error during processing
            files.append(path)

    return sorted(set(files))


@click.command()
@click.argument("input", nargs=-1, required=True)
@click.option("-o", "--output", type=click.Path(path_type=Path), help="Output directory")
@click.option(
    "-p",
    "--pattern",
    default=None,
    help="Output filename pattern (e.g. {date}-{subject}). Default: source filename",
)
@click.option("-r", "--recursive", is_flag=True, help="Process directories recursively")
@click.option("--preserve-structure", is_flag=True, help="Preserve directory structure in output")
@click.option("--prefer-html", is_flag=True, help="Prefer HTML body over plain text")
@click.option("--no-frontmatter", is_flag=True, help="Disable YAML frontmatter")
@click.option(
    "--include-headers",
    default="from,to,date,subject,cc,message_id",
    help="Headers to include in frontmatter (comma-separated)",
)
@click.option(
    "--attachments",
    type=click.Choice(["ignore", "list", "extract", "embed"]),
    default="list",
    help="How to handle attachments (default: list)",
)
@click.option(
    "--attachments-dir",
    default="attachments",
    help="Directory for extracted attachments (default: attachments)",
)
@click.option("--fail-fast", is_flag=True, help="Stop on first error")
@click.option("-v", "--verbose", is_flag=True, help="Verbose output")
@click.option("-q", "--quiet", is_flag=True, help="Only show errors")
@click.option("--dry-run", is_flag=True, help="Show what would be done without writing files")
@click.version_option(__version__)
def main(
    input: tuple[str, ...],
    output: Path | None,
    pattern: str,
    recursive: bool,
    preserve_structure: bool,
    prefer_html: bool,
    no_frontmatter: bool,
    include_headers: str,
    attachments: str,
    attachments_dir: str,
    fail_fast: bool,
    verbose: bool,
    quiet: bool,
    dry_run: bool,
):
    """Convert EML files to Markdown.

    INPUT can be files, directories, or glob patterns.

    Examples:

        maildown email.eml

        maildown ./inbox/

        maildown ./mail/ -r -o ./converted/

        maildown "*.eml" --attachments=extract
    """
    # Build conversion options
    options = ConversionOptions(
        prefer_html=prefer_html,
        include_frontmatter=not no_frontmatter,
        include_headers=[h.strip() for h in include_headers.split(",")],
        attachment_mode=AttachmentMode(attachments),
        attachments_dir=attachments_dir,
    )

    # Collect files
    files = collect_files(input, recursive)

    if not files:
        click.echo("No EML files found.", err=True)
        sys.exit(2)

    if verbose and not quiet:
        click.echo(f"Found {len(files)} file(s) to process")

    # Determine base input directory for structure preservation
    base_input_dir = None
    if preserve_structure and len(input) == 1:
        base_path = Path(input[0])
        if base_path.is_dir():
            base_input_dir = base_path

    # Process files
    result = ProcessingResult()

    for file_path in files:
        try:
            if verbose and not quiet:
                click.echo(f"Processing: {file_path}")

            # Parse
            email = parse_eml(file_path)

            # Determine output path
            output_path = determine_output_path(
                source_path=file_path,
                output_dir=output,
                pattern=pattern,
                email=email,
                preserve_structure=preserve_structure,
                base_input_dir=base_input_dir,
            )

            if dry_run:
                click.echo(f"Would write: {output_path}")
            else:
                write_markdown(email, output_path, options)
                if not quiet:
                    click.echo(f"Created: {output_path}")

            result.success += 1

        except Exception as e:
            error_msg = str(e)
            result.errors.append((file_path, error_msg))

            if not quiet:
                click.echo(f"Error processing {file_path}: {error_msg}", err=True)

            if fail_fast:
                break

    # Print summary
    if not quiet:
        click.echo(f"\nProcessed: {result.success + len(result.errors)} files", err=True)
        click.echo(f"Success: {result.success}", err=True)
        if result.errors:
            click.echo(f"Errors: {len(result.errors)}", err=True)
            for path, error in result.errors:
                click.echo(f"  - {path}: {error}", err=True)

    # Exit code
    if result.success == 0:
        sys.exit(2)
    elif result.errors:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
