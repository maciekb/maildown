"""Plan and write converted email files without silent data loss."""

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from maildown.converter import (
    AttachmentMode,
    ConversionOptions,
    convert_to_markdown,
    generate_filename,
    should_embed,
)
from maildown.parser import ParsedEmail, _is_portable_filename, safe_attachment_name


def _platform_case_insensitive_default() -> bool:
    """Case-insensitive filesystems are the platform default on macOS and Windows."""
    return sys.platform in ("darwin", "win32")


_case_probe_cache: dict[str, bool] = {}


def probe_case_insensitive(path: Path) -> bool:
    """Report whether *path*'s filesystem compares names case-insensitively.

    Strictly read-only: walks up to the nearest existing directory ancestor,
    inspects entries already present there, and compares an entry containing
    letters with its case-swapped name via ``os.path.samefile``. Anything
    inconclusive falls back to the platform default. Nothing is created,
    modified, or deleted, and filesystem errors never raise.
    """
    probe_dir = Path(os.path.abspath(path))
    while True:
        try:
            if probe_dir.is_dir():
                break
        except (OSError, ValueError):
            pass
        parent = probe_dir.parent
        if parent == probe_dir:
            return _platform_case_insensitive_default()
        probe_dir = parent
    key = str(probe_dir)
    if key not in _case_probe_cache:
        _case_probe_cache[key] = _probe_existing_directory(probe_dir)
    return _case_probe_cache[key]


def _probe_existing_directory(directory: Path) -> bool:
    try:
        names = os.listdir(directory)
    except OSError:
        return _platform_case_insensitive_default()
    for name in names:
        if not any(char.isalpha() for char in name):
            continue
        swapped = name.swapcase()
        if swapped == name:
            continue
        try:
            if os.path.samefile(directory / name, directory / swapped):
                return True
        except OSError:
            # The swapped name does not resolve here; inconclusive.
            return _platform_case_insensitive_default()
    return _platform_case_insensitive_default()


def _fold_key(path: Path) -> str:
    """Case-folded canonical key used on case-insensitive filesystems."""
    return str(path).casefold()


@dataclass
class ReservationIndex:
    """Shared canonical file/directory index for incremental batch planning.

    Only successful plans commit their local delta. Reuse an instance rather
    than a legacy set to avoid rebuilding the directory index for every email.

    ``case_insensitive`` is the filesystem's destination-comparison semantics:
    ``None`` detects it on the first plan and remembers it; ``True``/``False``
    force it (tests use ``True`` to simulate macOS). When insensitive, folded
    key sets are kept alongside the canonical ones so case-variant destinations
    collide; on case-sensitive filesystems they stay empty and behavior is
    unchanged.
    """

    files: set[Path] = field(default_factory=set)
    directories: set[Path] = field(default_factory=set)
    case_insensitive: bool | None = field(default=None, compare=False)
    folded_files: set[str] = field(default_factory=set)
    folded_directories: set[str] = field(default_factory=set)
    _folded_seeded: bool = field(default=False, repr=False, compare=False)

    def ensure_case_insensitive(self, probe_path: Path) -> bool:
        """Detect case semantics once, and seed folded keys on the transition.

        A shared index serves a single filesystem: when a plan's destination
        probe disagrees with the remembered verdict, raise before any
        reservation for that plan is committed.
        """
        verdict = probe_case_insensitive(probe_path)
        if self.case_insensitive is None:
            self.case_insensitive = verdict
        elif self.case_insensitive != verdict:
            raise ValueError(
                "Destinations span filesystems with different case semantics; "
                "use a separate ReservationIndex per filesystem"
            )
        if self.case_insensitive and not self._folded_seeded:
            self.folded_files.update(_fold_key(path) for path in self.files)
            self.folded_directories.update(_fold_key(path) for path in self.directories)
        self._folded_seeded = True
        return self.case_insensitive


@dataclass
class WritePlan:
    """Final destinations, keyed by attachment position (not filename)."""

    output_path: Path
    attachments: dict[int, Path]


def _is_portable_component(component: str) -> bool:
    """Report whether *component* is a portable path component on Windows."""
    if not component or component in (".", ".."):
        return False
    return _is_portable_filename(component)


def _portable_attachments_dir(attachments_dir: str) -> bool:
    """Report whether every *attachments_dir* component is portable.

    A bare ``.`` keeps the CLI's "extract beside the Markdown file" mode;
    pathlib drops it when joining, so it never reaches the filesystem as a
    directory name. Any other ``.`` component (or empty component from ``//``)
    is rejected along with the other unportable names.
    """
    if attachments_dir == ".":
        return True
    return all(_is_portable_component(component) for component in attachments_dir.split("/"))


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
    insensitive = shared.ensure_case_insensitive(output_path)
    delta = ReservationIndex()

    def known_file(path: Path) -> bool:
        """Membership test using the filesystem's own comparison semantics."""
        if path in shared.files or path in delta.files:
            return True
        if insensitive:
            key = _fold_key(path)
            return key in shared.folded_files or key in delta.folded_files
        return False

    def known_directory(path: Path) -> bool:
        """Reserved-directory membership, folded when the filesystem is."""
        if path in shared.directories or path in delta.directories:
            return True
        if insensitive:
            key = _fold_key(path)
            return key in shared.folded_directories or key in delta.folded_directories
        return False

    def namespace_blocked(path: Path) -> bool:
        """Only a stem-specific blocker can be avoided by another Markdown name."""
        folder = path.parent / options.attachments_dir / path.stem
        _reject_symlinks(folder)
        for parent in folder.resolve().parents:
            if parent.exists() and not parent.is_dir():
                raise NotADirectoryError(f"Output ancestor is not a directory: {parent}")
        if known_file(folder.resolve()) or (folder.exists() and not folder.is_dir()):
            _reject_hardlinks(folder)
            if on_conflict != "rename":
                raise NotADirectoryError(f"Output ancestor is not a directory: {folder}")
            return True
        return False

    def reserve(path: Path, *, check_namespace: bool = False) -> Path:
        # Normalize lexically once so exists()/is_symlink() checks, index keys,
        # and the returned plan path never carry ``..`` or redundant separators
        # (symlinked ancestors are already rejected by _reject_symlinks, which
        # makes lexical normalization filesystem-consistent here).
        path = Path(os.path.normpath(path))
        _reject_symlinks(path)
        for parent in path.resolve().parents:
            if known_file(parent) or (parent.exists() and not parent.is_dir()):
                raise NotADirectoryError(f"Output ancestor is not a directory: {parent}")
        original = path
        counter = 0
        canonical = path.resolve()
        while (
            path.exists()
            or known_file(canonical)
            or known_directory(canonical)
            or (check_namespace and namespace_blocked(path))
        ):
            if (
                on_conflict == "overwrite"
                and path.is_file()
                and not known_file(canonical)
                and not known_directory(canonical)
            ):
                _reject_hardlinks(path)
                break
            if on_conflict != "rename":
                raise FileExistsError(f"Destination already exists or is reserved: {path}")
            counter += 1
            path = original.with_name(f"{original.stem}_{counter}{original.suffix}")
            _reject_symlinks(path)
            canonical = path.resolve()
        # Rejected candidates never enter the local delta; only the complete
        # successful email plan below commits that delta to shared reservations.
        delta.files.add(canonical)
        delta.directories.update(canonical.parents)
        if insensitive:
            delta.folded_files.add(_fold_key(canonical))
            delta.folded_directories.update(_fold_key(parent) for parent in canonical.parents)
        return path

    extracts = False
    directory = Path(options.attachments_dir)
    if email.attachments and options.attachment_mode in (
        AttachmentMode.EXTRACT,
        AttachmentMode.EMBED,
    ):
        if (
            directory.is_absolute()
            or ".." in directory.parts
            or not _portable_attachments_dir(options.attachments_dir)
            or any(c in options.attachments_dir for c in "\\:\x00")
        ):
            raise ValueError("Unsafe attachment directory")
        extracts = any(not should_embed(attachment, options) for attachment in email.attachments)
    output_path = reserve(output_path, check_namespace=extracts)
    attachments = {}
    if extracts:
        folder = output_path.parent / directory / output_path.stem
        for index, attachment in enumerate(email.attachments):
            if should_embed(attachment, options):
                continue
            name = safe_attachment_name(attachment.filename, index)
            attachments[index] = reserve(folder / name)
    if isinstance(reservations, ReservationIndex):
        reservations.files.update(delta.files)
        reservations.directories.update(delta.directories)
        reservations.folded_files.update(delta.folded_files)
        reservations.folded_directories.update(delta.folded_directories)
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
