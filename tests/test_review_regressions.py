"""Review regressions through the installed CLI and real planner."""

import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("target", ["markdown", "attachment"])
def test_overwrite_rechecks_hardlinks_after_planning(tmp_path, monkeypatch, target):
    from maildown import writer
    from maildown.converter import AttachmentMode, ConversionOptions
    from maildown.parser import Attachment, ParsedEmail

    output = tmp_path / "mail.md"
    destination = output if target == "markdown" else tmp_path / "attachments/mail/a.txt"
    sentinel = tmp_path / "outside"
    sentinel.write_bytes(b"original")
    original = writer.plan_write

    def plan_then_link(*args, **kwargs):
        plan = original(*args, **kwargs)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.hardlink_to(sentinel)
        return plan

    monkeypatch.setattr(writer, "plan_write", plan_then_link)
    with pytest.raises(ValueError, match="Hardlinked"):
        writer.write_markdown(
            ParsedEmail(attachments=[Attachment("a.txt", "text/plain", 1, b"x")]),
            output,
            ConversionOptions(attachment_mode=AttachmentMode.EXTRACT),
            on_conflict="overwrite",
        )
    assert sentinel.read_bytes() == b"original"


def test_shared_index_is_incremental_and_rolls_back_failed_email(tmp_path):
    from maildown import writer
    from maildown.converter import AttachmentMode, ConversionOptions
    from maildown.parser import Attachment, ParsedEmail

    assert hasattr(writer, "ReservationIndex")
    index = writer.ReservationIndex()
    empty = ParsedEmail()
    writer.plan_write(empty, tmp_path / "first.md", reservations=index)
    files = index.files
    directories = index.directories
    before = (files.copy(), directories.copy())
    duplicate = ParsedEmail(attachments=[Attachment("a", "text/plain", 1, b"x")] * 2)
    with pytest.raises(FileExistsError):
        writer.plan_write(
            duplicate,
            tmp_path / "failed.md",
            ConversionOptions(attachment_mode=AttachmentMode.EXTRACT),
            reservations=index,
        )
    assert (index.files, index.directories) == before
    writer.plan_write(empty, tmp_path / "failed.md", reservations=index)
    assert index.files is files and index.directories is directories
    assert len(files) == 2
    with pytest.raises(NotADirectoryError):
        writer.plan_write(empty, tmp_path / "first.md/child.md", reservations=index)
    renamed = writer.plan_write(empty, tmp_path, reservations=index, on_conflict="rename")
    assert renamed.output_path != tmp_path


@pytest.mark.parametrize("filename", ['; filename=""', ""])
@pytest.mark.parametrize("dry_run", [False, True])
def test_cli_unnamed_attachments_use_position(tmp_path, filename, dry_run):
    source = tmp_path / "mail.eml"
    source.write_text(
        'MIME-Version: 1.0\nContent-Type: multipart/mixed; boundary="x"\n\n'
        "--x\nContent-Type: text/plain\n\nbody\n"
        + "".join(
            f"--x\nContent-Type: application/octet-stream\n"
            f"Content-Disposition: attachment{filename}\n\n{body}\n"
            for body in ("first", "second")
        )
        + "--x--\n"
    )
    args = [source, "--attachments", "extract"]
    if dry_run:
        args.append("--dry-run")
    result = cli(*args)
    assert result.returncode == 0, result.stdout + result.stderr
    for position, content in enumerate((b"first", b"second"), 1):
        target = tmp_path / f"attachments/mail/attachment_{position}.bin"
        if dry_run:
            assert f"Would extract: {target}" in result.stdout
            assert not target.exists()
        else:
            assert target.read_bytes() == content
            assert f"(./attachments/mail/{target.name})" in source.with_suffix(".md").read_text()
    if dry_run:
        assert not (tmp_path / "attachments").exists()
        assert not source.with_suffix(".md").exists()


def cli(*args):
    return subprocess.run(
        [str(Path(sys.executable).parent / "maildown"), *map(str, args)],
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize("target", ["markdown", "attachment"])
@pytest.mark.parametrize("dry_run", [False, True])
def test_cli_overwrite_rejects_hardlinks(tmp_path, target, dry_run):
    source = tmp_path / "mail.eml"
    source.write_bytes((Path(__file__).parent / "fixtures/with-attachment.eml").read_bytes())
    destination = tmp_path / ("mail.md" if target == "markdown" else "attachments/mail/notes.txt")
    destination.parent.mkdir(parents=True, exist_ok=True)
    sentinel = tmp_path / "outside.txt"
    sentinel.write_bytes(b"original")
    destination.hardlink_to(sentinel)
    args = [source, "--attachments", "extract", "--on-conflict", "overwrite"]
    if dry_run:
        args.append("--dry-run")
    result = cli(*args)
    assert result.returncode == 2, result.stdout + result.stderr
    assert "Hardlinked" in result.stderr
    assert sentinel.read_bytes() == destination.read_bytes() == b"original"
    if target == "attachment":
        assert not source.with_suffix(".md").exists()
