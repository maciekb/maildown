"""Regression tests for safe output planning and attachment writes."""

import pytest

from maildown.converter import AttachmentMode, ConversionOptions
from maildown.parser import Attachment, ParsedEmail
from maildown.writer import write_markdown


@pytest.mark.parametrize("target", ["output", "attachment", "duplicate"])
def test_default_conflicts_fail_without_partial_writes(tmp_path, target):
    output = tmp_path / "mail.md"
    attachment = tmp_path / "attachments" / "mail" / "test.txt"
    existing = output if target == "output" else attachment
    if target != "duplicate":
        existing.parent.mkdir(parents=True, exist_ok=True)
        existing.write_bytes(b"original")
    email = (
        message("test.txt", "test.txt") if target == "duplicate" else message("new.txt", "test.txt")
    )
    with pytest.raises(FileExistsError):
        write_markdown(email, output, ConversionOptions(attachment_mode=AttachmentMode.EXTRACT))
    if target != "duplicate":
        assert existing.read_bytes() == b"original"
    assert not (attachment.parent / "new.txt").exists()
    if target != "output":
        assert not output.exists()


def test_links_follow_attachment_identity_and_quote_urls(tmp_path):
    from urllib.parse import quote

    name = "report #?%().txt"
    email = message(name, name, "../unsafe")
    email.attachments[1].content = b"second"
    folder = tmp_path / "attachments" / "mail"
    folder.mkdir(parents=True)
    (folder / name).write_bytes(b"existing")
    output = write_markdown(
        email,
        tmp_path / "mail.md",
        ConversionOptions(attachment_mode=AttachmentMode.EXTRACT),
        on_conflict="rename",
    )
    text = output.read_text()
    for filename in ["report #?%()_1.txt", "report #?%()_2.txt", "attachment_3.bin"]:
        assert f"({quote('./attachments/mail/' + filename, safe='/')})" in text
    assert (folder / "report #?%()_2.txt").read_bytes() == b"second"
    assert (folder / name).read_bytes() == b"existing"


@pytest.mark.parametrize("size", [99_999, 100_000])
def test_embed_boundary_only_extracts_fallbacks(tmp_path, size):
    email = message("image #.png", "image #.png")
    for attachment in email.attachments:
        attachment.content_type = "image/png"
        attachment.content = b"x" * size
        attachment.size = size
    output = write_markdown(
        email,
        tmp_path / "mail.md",
        ConversionOptions(attachment_mode=AttachmentMode.EMBED),
        on_conflict="rename",
    )
    if size < 100_000:
        assert "data:image/png;base64," in output.read_text()
        assert not (tmp_path / "attachments").exists()
    else:
        assert "data:image/png" not in output.read_text()
        assert "(./attachments/mail/image%20%23_1.png)" in output.read_text()
        assert (tmp_path / "attachments/mail/image #_1.png").stat().st_size == size


def test_reserved_files_cannot_be_attachment_directories(tmp_path):
    from maildown.writer import plan_write

    reservations = set()
    plan_write(message(), tmp_path / "mail.md", reservations=reservations)
    with pytest.raises((FileExistsError, NotADirectoryError)):
        plan_write(
            message("test.txt"),
            tmp_path / "other.md",
            ConversionOptions(attachment_mode=AttachmentMode.EXTRACT, attachments_dir="mail.md"),
            reservations=reservations,
        )
    assert not list(tmp_path.iterdir())


def test_reserved_directories_cannot_be_output_files(tmp_path):
    from maildown.writer import plan_write

    reservations = set()
    plan_write(
        message("test.txt"),
        tmp_path / "mail.md",
        ConversionOptions(attachment_mode=AttachmentMode.EXTRACT, attachments_dir="other.md"),
        reservations=reservations,
    )
    plan = plan_write(
        message(), tmp_path / "other.md", on_conflict="rename", reservations=reservations
    )
    assert plan.output_path == tmp_path / "other_1.md"


def test_reservations_normalize_lexical_aliases(tmp_path):
    from maildown.writer import plan_write

    (tmp_path / "nested").mkdir()
    reservations = set()
    plan_write(message(), tmp_path / "mail.md", reservations=reservations)
    with pytest.raises(FileExistsError):
        plan_write(message(), tmp_path / "nested/../mail.md", reservations=reservations)


def test_attachment_link_labels_escape_markdown(tmp_path):
    output = write_markdown(
        message("a[link]\\\\name.txt"),
        tmp_path / "mail.md",
        ConversionOptions(attachment_mode=AttachmentMode.EXTRACT),
    )
    assert r"[a\[link\]\\\\name.txt](./attachments/mail/attachment_1.bin)" in output.read_text()


def test_overwrite_replaces_existing_attachment(tmp_path):
    folder = tmp_path / "attachments/mail"
    folder.mkdir(parents=True)
    (folder / "test.txt").write_bytes(b"original")
    write_markdown(
        message("test.txt"),
        tmp_path / "mail.md",
        ConversionOptions(attachment_mode=AttachmentMode.EXTRACT),
        on_conflict="overwrite",
    )
    assert (folder / "test.txt").read_bytes() == b"x"


def test_overwrite_rejects_duplicate_attachments(tmp_path):
    with pytest.raises(FileExistsError):
        write_markdown(
            message("test.txt", "test.txt"),
            tmp_path / "mail.md",
            ConversionOptions(attachment_mode=AttachmentMode.EXTRACT),
            on_conflict="overwrite",
        )
    assert not list(tmp_path.iterdir())


def test_output_rename_moves_attachment_namespace(tmp_path):
    (tmp_path / "mail.md").write_text("original")
    output = write_markdown(
        message("test.txt"),
        tmp_path / "mail.md",
        ConversionOptions(attachment_mode=AttachmentMode.EXTRACT),
        on_conflict="rename",
    )
    assert "(./attachments/mail_1/test.txt)" in output.read_text()
    assert (tmp_path / "attachments/mail_1/test.txt").read_bytes() == b"x"


def message(*names):
    return ParsedEmail(attachments=[Attachment(n, "text/plain", 1, b"x") for n in names])


@pytest.mark.parametrize(
    "name",
    [
        "../escape",
        "/absolute",
        r"C:\escape",
        r"..\escape",
        "C:escape",
        "",
        ".",
        "..",
        "a/b",
        "a\x00b",
    ],
)
def test_unsafe_attachment_names_have_deterministic_fallback(tmp_path, name):
    options = ConversionOptions(attachment_mode=AttachmentMode.EXTRACT)
    for folder in ("one", "two"):
        output = tmp_path / folder / "mail.md"
        write_markdown(message(name), output, options)
        files = list((output.parent / "attachments" / "mail").iterdir())
        assert [p.name for p in files] == ["attachment_1.bin"]
        assert files[0].read_bytes() == b"x"


@pytest.mark.parametrize("policy", ["error", "rename", "overwrite"])
@pytest.mark.parametrize("dangling", [False, True])
@pytest.mark.parametrize("location", ["ancestor", "directory", "attachment", "output"])
def test_symlinks_are_rejected_before_any_writes(tmp_path, location, policy, dangling):
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "sentinel"
    sentinel.write_bytes(b"original")
    root = tmp_path / "out"
    root.mkdir()
    output = root / "mail.md"
    if location == "ancestor":
        (root / "alias").symlink_to(outside, target_is_directory=True)
        output = root / "alias" / "nested" / "mail.md"
    elif location == "directory":
        (root / "attachments").symlink_to(outside, target_is_directory=True)
    elif location == "attachment":
        folder = root / "attachments" / "mail"
        folder.mkdir(parents=True)
        (folder / "test.txt").symlink_to(sentinel)
    else:
        output.symlink_to(sentinel)
    if dangling:
        sentinel.unlink()
        if location in ("ancestor", "directory"):
            outside.rmdir()
    with pytest.raises(ValueError, match="[Ss]ymlink"):
        write_markdown(
            message("test.txt"),
            output,
            ConversionOptions(attachment_mode=AttachmentMode.EXTRACT),
            on_conflict=policy,
        )
    if not dangling:
        assert sentinel.read_bytes() == b"original"
        assert sorted(p.name for p in outside.iterdir()) == ["sentinel"]
    else:
        assert not sentinel.exists()


@pytest.mark.parametrize("directory", ["../outside", "/absolute", r"C:\outside", r"..\outside"])
def test_attachment_directory_must_be_contained(tmp_path, directory):
    with pytest.raises(ValueError, match="attachment directory"):
        write_markdown(
            message("test.txt"),
            tmp_path / "mail.md",
            ConversionOptions(attachment_mode=AttachmentMode.EXTRACT, attachments_dir=directory),
        )
    assert not (tmp_path / "mail.md").exists()
