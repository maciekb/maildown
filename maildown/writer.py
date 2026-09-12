"""Plan and write converted email files without silent data loss."""

from dataclasses import dataclass, field
from pathlib import Path

from maildown.converter import (
    AttachmentMode,
    ConversionOptions,
    convert_to_markdown,
    generate_filename,
    should_embed,
)
from maildown.parser import ParsedEmail, attachment_fallback_name


@dataclass
class ReservationIndex:
    """Shared canonical file/directory index for incremental batch planning.

    Only successful plans commit their local delta. Reuse an instance rather
    than a legacy set to avoid rebuilding the directory index for every email.
    """

    files: set[Path] = field(default_factory=set)
    directories: set[Path] = field(default_factory=set)


@dataclass
class WritePlan:
    """Final destinations, keyed by attachment position (not filename)."""

    output_path: Path
    attachments: dict[int, Path]


def plan_write(
    email: ParsedEmail,
    output_path: Path,
    options: ConversionOptions | None = None,
    *,
    on_conflict: str = "error",
    reservations: ReservationIndex | set[Path] | None = None,
) -> WritePlan:
    """Validate all destinations before creating any files or directories."""
    options = options or ConversionOptions()
    if on_conflict not in {"error", "rename", "overwrite"}:
        raise ValueError(f"Unknown conflict policy: {on_conflict}")
    if isinstance(reservations, ReservationIndex):
        shared = reservations
    else:
        # Compatibility for callers using the original mutable set API.
        files = {path.resolve() for path in (reservations or ())}
        shared = ReservationIndex(files, {parent for path in files for parent in path.parents})
    delta = ReservationIndex()

    def reserve(path: Path) -> Path:
        _reject_symlinks(path)
        for parent in path.resolve().parents:
            if (
                parent in shared.files
                or parent in delta.files
                or (parent.exists() and not parent.is_dir())
            ):
                raise NotADirectoryError(f"Output ancestor is not a directory: {parent}")
        original = path
        counter = 0
        canonical = path.resolve()
        while (
            path.exists()
            or canonical in shared.files
            or canonical in delta.files
            or canonical in shared.directories
            or canonical in delta.directories
        ):
            if (
                on_conflict == "overwrite"
                and path.is_file()
                and canonical not in shared.files
                and canonical not in delta.files
                and canonical not in shared.directories
                and canonical not in delta.directories
            ):
                _reject_hardlinks(path)
                break
            if on_conflict != "rename":
                raise FileExistsError(f"Destination already exists or is reserved: {path}")
            counter += 1
            path = original.with_name(f"{original.stem}_{counter}{original.suffix}")
            _reject_symlinks(path)
            canonical = path.resolve()
        delta.files.add(canonical)
        delta.directories.update(canonical.parents)
        return path

    output_path = reserve(output_path)
    attachments = {}
    if email.attachments and options.attachment_mode in (
        AttachmentMode.EXTRACT,
        AttachmentMode.EMBED,
    ):
        directory = Path(options.attachments_dir)
        if (
            directory.is_absolute()
            or ".." in directory.parts
            or any(c in options.attachments_dir for c in "\\:\x00")
        ):
            raise ValueError("Unsafe attachment directory")
        folder = output_path.parent / directory / output_path.stem
        for index, attachment in enumerate(email.attachments):
            if should_embed(attachment, options):
                continue
            name = attachment.filename
            if not name or name in (".", "..") or any(c in name for c in "/\\:\x00"):
                name = attachment_fallback_name(index)
            attachments[index] = reserve(folder / name)
    if isinstance(reservations, ReservationIndex):
        reservations.files.update(delta.files)
        reservations.directories.update(delta.directories)
    elif reservations is not None:
        reservations.update(delta.files)
    return WritePlan(output_path, attachments)


def write_markdown(
    email: ParsedEmail,
    output_path: Path,
    options: ConversionOptions | None = None,
    *,
    on_conflict: str = "error",
    reservations: ReservationIndex | set[Path] | None = None,
) -> Path:
    """Preflight destinations, then write with exclusive creation by default."""
    options = options or ConversionOptions()
    plan = plan_write(
        email, output_path, options, on_conflict=on_conflict, reservations=reservations
    )
    base = f"./{options.attachments_dir}/{plan.output_path.stem}"
    links = {
        index: "./" + path.relative_to(plan.output_path.parent).as_posix()
        for index, path in plan.attachments.items()
    }
    markdown = convert_to_markdown(email, options, base, links)
    for index, path in plan.attachments.items():
        _reject_symlinks(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if on_conflict == "overwrite":
            _reject_hardlinks(path)
        with path.open("wb" if on_conflict == "overwrite" else "xb") as stream:
            stream.write(email.attachments[index].content)
    _reject_symlinks(plan.output_path)
    plan.output_path.parent.mkdir(parents=True, exist_ok=True)
    if on_conflict == "overwrite":
        _reject_hardlinks(plan.output_path)
    with plan.output_path.open(
        "w" if on_conflict == "overwrite" else "x", encoding="utf-8"
    ) as stream:
        stream.write(markdown)
    return plan.output_path


def _reject_hardlinks(path: Path) -> None:
    """Do not truncate a regular file shared by another directory entry."""
    import stat

    try:
        info = path.stat()
    except FileNotFoundError:
        return
    if stat.S_ISREG(info.st_mode) and info.st_nlink > 1:
        raise ValueError(f"Hardlinked output file is not allowed: {path}")


def _reject_symlinks(path: Path) -> None:
    """Reject symlinks, including dangling links and every ancestor."""
    for component in (path.absolute(), *path.absolute().parents):
        if component.is_symlink():
            raise ValueError(f"Symlink output path is not allowed: {component}")


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
