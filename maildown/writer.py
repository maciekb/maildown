"""Plan and write converted email files without silent data loss."""

import os
import sys
from dataclasses import dataclass
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


class ReservationIndex:
    """Own destination reservations for incremental batch planning.

    Seed paths are copied and canonicalized once, including file ancestors.
    Only successful plans commit their staged reservations. Reuse an instance
    rather than a legacy set to avoid rebuilding the index for every email.

    ``case_insensitive=None`` adopts the first plan's filesystem comparison
    semantics. An explicit value must agree with the planner's filesystem probe.
    Backing sets are private; subsequent changes to seed sets have no effect.
    """

    def __init__(
        self,
        files: set[Path] | None = None,
        directories: set[Path] | None = None,
        case_insensitive: bool | None = None,
    ):
        self._case_insensitive = case_insensitive
        canonical_files = {path.resolve() for path in (files or ())}
        canonical_directories = {path.resolve() for path in (directories or ())}
        canonical_directories.update(parent for path in canonical_files for parent in path.parents)
        self._files = {self._key(path) for path in canonical_files}
        self._directories = {self._key(path) for path in canonical_directories}

    @property
    def case_insensitive(self) -> bool | None:
        """The remembered comparison semantics, or None before detection."""
        return self._case_insensitive

    def _key(self, canonical: Path) -> str:
        key = str(canonical)
        return key.casefold() if self._case_insensitive else key

    def _begin(self, case_insensitive: bool) -> "_ReservationBatch":
        """Stage one plan using the planner's read-only filesystem verdict."""
        if self._case_insensitive is None:
            self._case_insensitive = case_insensitive
            if case_insensitive:
                self._files = {key.casefold() for key in self._files}
                self._directories = {key.casefold() for key in self._directories}
        elif self._case_insensitive != case_insensitive:
            raise ValueError(
                "Destinations span filesystems with different case semantics; "
                "use a separate ReservationIndex per filesystem"
            )
        return _ReservationBatch(self)


class _ReservationBatch:
    """Private staging for one plan; discarded unless the planner commits it.

    Paths are canonical: the planner resolves them while checking filesystem
    safety. Membership includes committed destinations without copying them.
    """

    def __init__(self, index: ReservationIndex):
        self._index = index
        self._paths: set[Path] = set()
        self._files: set[str] = set()
        self._directories: set[str] = set()

    def known_file(self, canonical: Path) -> bool:
        key = self._index._key(canonical)
        return key in self._files or key in self._index._files

    def known_directory(self, canonical: Path) -> bool:
        key = self._index._key(canonical)
        return key in self._directories or key in self._index._directories

    def reserve(self, canonical: Path) -> None:
        self._paths.add(canonical)
        self._files.add(self._index._key(canonical))
        self._directories.update(self._index._key(parent) for parent in canonical.parents)

    def commit(self, legacy: set[Path] | None = None) -> None:
        self._index._files.update(self._files)
        self._index._directories.update(self._directories)
        if legacy is not None:
            legacy.update(self._paths)


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
        shared = ReservationIndex(reservations)
    batch = shared._begin(probe_case_insensitive(output_path))

    def namespace_blocked(path: Path) -> bool:
        """Only a stem-specific blocker can be avoided by another Markdown name."""
        folder = path.parent / options.attachments_dir / path.stem
        _reject_symlinks(folder)
        for parent in folder.resolve().parents:
            if parent.exists() and not parent.is_dir():
                raise NotADirectoryError(f"Output ancestor is not a directory: {parent}")
        if batch.known_file(folder.resolve()) or (folder.exists() and not folder.is_dir()):
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
            if batch.known_file(parent) or (parent.exists() and not parent.is_dir()):
                raise NotADirectoryError(f"Output ancestor is not a directory: {parent}")
        original = path
        counter = 0
        canonical = path.resolve()
        while (
            path.exists()
            or batch.known_file(canonical)
            or batch.known_directory(canonical)
            or (check_namespace and namespace_blocked(path))
        ):
            if (
                on_conflict == "overwrite"
                and path.is_file()
                and not batch.known_file(canonical)
                and not batch.known_directory(canonical)
            ):
                _reject_hardlinks(path)
                break
            if on_conflict != "rename":
                raise FileExistsError(f"Destination already exists or is reserved: {path}")
            counter += 1
            path = original.with_name(f"{original.stem}_{counter}{original.suffix}")
            _reject_symlinks(path)
            canonical = path.resolve()
        # Only the complete successful plan commits these reservations.
        batch.reserve(canonical)
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
    batch.commit(reservations if isinstance(reservations, set) else None)
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
