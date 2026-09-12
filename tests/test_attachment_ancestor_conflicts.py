"""Attachment namespaces participate in Markdown rename selection."""

import subprocess
import sys
from email.message import EmailMessage
from pathlib import Path

import pytest

from maildown.converter import AttachmentMode, ConversionOptions
from maildown.parser import Attachment, ParsedEmail
from maildown.writer import ReservationIndex, plan_write


@pytest.mark.parametrize("dry_run", [False, True])
@pytest.mark.parametrize("existing_markdown", [False, True])
def test_cli_rename_skips_blocked_attachment_stem(tmp_path, dry_run, existing_markdown):
    source = tmp_path / "mail.eml"
    message = EmailMessage()
    message.set_content("body")
    message.add_attachment(b"payload", maintype="text", subtype="plain", filename="file.txt")
    source.write_bytes(message.as_bytes())
    if existing_markdown:
        source.with_suffix(".md").write_text("original markdown")
    blocked = tmp_path / "attachments" / ("mail_1" if existing_markdown else "mail")
    blocked.parent.mkdir()
    blocked.write_bytes(b"original attachment blocker")
    before = {p.relative_to(tmp_path) for p in tmp_path.rglob("*")}
    args = [str(source), "--attachments", "extract", "--on-conflict", "rename"]
    if dry_run:
        args.append("--dry-run")
    result = subprocess.run(
        [str(Path(sys.executable).parent / "maildown"), *args],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    stem = "mail_2" if existing_markdown else "mail_1"
    output = tmp_path / f"{stem}.md"
    attachment = tmp_path / "attachments" / stem / "file.txt"
    if dry_run:
        assert f"Would write: {output}" in result.stdout
        assert f"Would extract: {attachment}" in result.stdout
        assert "Planned: 1" in result.stderr
        assert {p.relative_to(tmp_path) for p in tmp_path.rglob("*")} == before
    else:
        assert f"Created: {output}" in result.stdout
        assert "Success: 1" in result.stderr
        assert f"(./attachments/{stem}/file.txt)" in output.read_text()
        assert attachment.read_bytes() == b"payload"
    assert blocked.read_bytes() == b"original attachment blocker"
    if existing_markdown:
        assert source.with_suffix(".md").read_text() == "original markdown"


@pytest.mark.parametrize("legacy", [False, True])
def test_reserved_stems_retry_without_leaking_candidate_reservations(tmp_path, legacy):
    reservations = set() if legacy else ReservationIndex()
    for name in ("mail", "mail_1"):
        plan_write(ParsedEmail(), tmp_path / "attachments" / name, reservations=reservations)
    plan_write(ParsedEmail(), tmp_path / "mail_2.md", reservations=reservations)
    before = reservations.copy() if legacy else None
    plan = plan_write(
        ParsedEmail(attachments=[Attachment("file.txt", "text/plain", 1, b"x")]),
        tmp_path / "mail.md",
        ConversionOptions(attachment_mode=AttachmentMode.EXTRACT),
        on_conflict="rename",
        reservations=reservations,
    )
    assert plan.output_path == tmp_path / "mail_3.md"
    assert plan.attachments == {0: tmp_path / "attachments/mail_3/file.txt"}
    if legacy:
        assert reservations == before | {plan.output_path, *plan.attachments.values()}
    for path in (plan.output_path, *plan.attachments.values()):
        with pytest.raises(FileExistsError):
            plan_write(ParsedEmail(), path, reservations=reservations)
    for name in ("mail.md", "mail_1.md"):
        assert (
            plan_write(ParsedEmail(), tmp_path / name, reservations=reservations).output_path
            == tmp_path / name
        )
    assert not list(tmp_path.iterdir())


def test_rename_rejects_hardlinked_stem_instead_of_retrying(tmp_path, bounded_path_checks):
    sentinel = tmp_path / "sentinel"
    sentinel.write_bytes(b"original")
    blocked = tmp_path / "attachments/mail"
    blocked.parent.mkdir()
    blocked.hardlink_to(sentinel)
    reservations = ReservationIndex()
    with pytest.raises(ValueError, match="Hardlinked"):
        plan_write(
            ParsedEmail(attachments=[Attachment("file.txt", "text/plain", 1, b"x")]),
            tmp_path / "mail.md",
            ConversionOptions(attachment_mode=AttachmentMode.EXTRACT),
            on_conflict="rename",
            reservations=reservations,
        )
    assert (
        plan_write(ParsedEmail(), tmp_path / "mail.md", reservations=reservations).output_path
        == tmp_path / "mail.md"
    )
    assert sentinel.read_bytes() == blocked.read_bytes() == b"original"
    assert not (tmp_path / "mail_1.md").exists()


@pytest.fixture
def bounded_path_checks(monkeypatch):
    """Fail promptly if an unrecoverable error starts an unbounded suffix search."""
    from maildown import writer

    original = writer._reject_symlinks
    calls = []

    def check(path):
        calls.append(path)
        assert len(calls) <= 10, "Unrecoverable conflict retried too many candidates"
        original(path)

    monkeypatch.setattr(writer, "_reject_symlinks", check)
    return calls


@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("reserved", [False, True])
@pytest.mark.parametrize("directory", ["attachments", "attachments/nested"])
def test_common_ancestor_failure_is_bounded_and_atomic(
    tmp_path, bounded_path_checks, legacy, reserved, directory
):
    reservations = set() if legacy else ReservationIndex()
    blocked = tmp_path / "attachments"
    if reserved:
        plan_write(ParsedEmail(), blocked, reservations=reservations)
    else:
        blocked.write_bytes(b"original")
    before = reservations.copy() if legacy else None
    with pytest.raises(NotADirectoryError, match="Output ancestor"):
        plan_write(
            ParsedEmail(attachments=[Attachment("file.txt", "text/plain", 1, b"x")]),
            tmp_path / "mail.md",
            ConversionOptions(attachment_mode=AttachmentMode.EXTRACT, attachments_dir=directory),
            on_conflict="rename",
            reservations=reservations,
        )
    if legacy:
        assert reservations == before
    if not reserved:
        assert blocked.read_bytes() == b"original"
    assert not (tmp_path / "mail.md").exists()
    plan_write(ParsedEmail(), tmp_path / "mail.md", reservations=reservations)


@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("location", ["stem", "late_attachment"])
@pytest.mark.parametrize("dangling", [False, True])
def test_security_failure_after_retry_discards_entire_delta(
    tmp_path, bounded_path_checks, legacy, location, dangling
):
    reservations = set() if legacy else ReservationIndex()
    plan_write(ParsedEmail(), tmp_path / "unrelated.md", reservations=reservations)
    before = reservations.copy() if legacy else None
    blocked = tmp_path / "attachments/mail"
    blocked.parent.mkdir()
    blocked.write_bytes(b"blocker")
    sentinel = tmp_path / "sentinel"
    if not dangling:
        sentinel.write_bytes(b"original")
    link = tmp_path / "attachments/mail_1"
    if location == "late_attachment":
        link.mkdir()
        link /= "second.txt"
    link.symlink_to(sentinel)
    with pytest.raises(ValueError, match="Symlink"):
        plan_write(
            ParsedEmail(
                attachments=[Attachment(n, "text/plain", 1, b"x") for n in ("first", "second.txt")]
            ),
            tmp_path / "mail.md",
            ConversionOptions(attachment_mode=AttachmentMode.EXTRACT),
            on_conflict="rename",
            reservations=reservations,
        )
    if legacy:
        assert reservations == before
    assert link.is_symlink()
    assert blocked.read_bytes() == b"blocker"
    assert not (tmp_path / "mail_1.md").exists()
    if not dangling:
        assert sentinel.read_bytes() == b"original"
    # Removing the filesystem blocker makes the same candidate reusable.
    link.unlink()
    if location == "late_attachment":
        link.parent.rmdir()
    bounded_path_checks.clear()
    plan_write(ParsedEmail(), tmp_path / "mail_1.md", reservations=reservations)
    plan_write(ParsedEmail(), tmp_path / "attachments/mail_1", reservations=reservations)
    with pytest.raises(FileExistsError):
        plan_write(ParsedEmail(), tmp_path / "unrelated.md", reservations=reservations)


@pytest.mark.parametrize("case_insensitive", [False, True])
def test_retry_does_not_scan_shared_index(tmp_path, monkeypatch, case_insensitive):
    from maildown import writer

    monkeypatch.setattr(writer, "probe_case_insensitive", lambda path: case_insensitive)

    class MembershipOnlySet(set):
        def __iter__(self):
            pytest.fail("Incremental planning must not scan shared reservations")

        def copy(self):
            pytest.fail("Incremental planning must not copy shared reservations")

    reservations = ReservationIndex()
    plan_write(ParsedEmail(), tmp_path / "attachments/mail", reservations=reservations)
    # Instrument only after the initial plan: seed ingestion and case detection may scan once.
    reservations._files = MembershipOnlySet(reservations._files)
    reservations._directories = MembershipOnlySet(reservations._directories)
    plan = plan_write(
        ParsedEmail(attachments=[Attachment("file.txt", "text/plain", 1, b"x")]),
        tmp_path / "mail.md",
        ConversionOptions(attachment_mode=AttachmentMode.EXTRACT),
        on_conflict="rename",
        reservations=reservations,
    )
    assert plan.output_path == tmp_path / "mail_1.md"
    assert (
        plan_write(ParsedEmail(), tmp_path / "mail.md", reservations=reservations).output_path
        == tmp_path / "mail.md"
    )


def test_embedded_only_email_still_validates_attachment_directory(tmp_path):
    with pytest.raises(ValueError, match="Unsafe attachment directory"):
        plan_write(
            ParsedEmail(attachments=[Attachment("image.png", "image/png", 1, b"x")]),
            tmp_path / "mail.md",
            ConversionOptions(attachment_mode=AttachmentMode.EMBED, attachments_dir="../outside"),
            on_conflict="rename",
        )


@pytest.mark.parametrize("mode", [AttachmentMode.IGNORE, AttachmentMode.LIST, AttachmentMode.EMBED])
def test_no_extracted_files_do_not_require_attachment_namespace(tmp_path, mode):
    blocked = tmp_path / "attachments/mail"
    blocked.parent.mkdir()
    blocked.write_bytes(b"original")
    plan = plan_write(
        ParsedEmail(attachments=[Attachment("image.png", "image/png", 1, b"x")]),
        tmp_path / "mail.md",
        ConversionOptions(attachment_mode=mode),
        on_conflict="rename",
    )
    assert plan.output_path == tmp_path / "mail.md"
    assert plan.attachments == {}
    assert blocked.read_bytes() == b"original"


@pytest.mark.parametrize("policy", ["error", "overwrite"])
def test_nonrename_policy_rejects_blocked_stem(tmp_path, bounded_path_checks, policy):
    blocked = tmp_path / "attachments/mail"
    blocked.parent.mkdir()
    blocked.write_bytes(b"original")
    reservations = ReservationIndex()
    with pytest.raises(NotADirectoryError):
        plan_write(
            ParsedEmail(attachments=[Attachment("file.txt", "text/plain", 1, b"x")]),
            tmp_path / "mail.md",
            ConversionOptions(attachment_mode=AttachmentMode.EXTRACT),
            on_conflict=policy,
            reservations=reservations,
        )
    assert (
        plan_write(ParsedEmail(), tmp_path / "mail.md", reservations=reservations).output_path
        == tmp_path / "mail.md"
    )
    assert blocked.read_bytes() == b"original"


@pytest.mark.parametrize("dry_run", [False, True])
def test_cli_batch_attachment_reservation_blocks_later_stem(tmp_path, dry_run):
    inputs = tmp_path / "input"
    for relative, name, content in (
        ("a.eml", "mail", b"earlier"),
        ("z/mail.eml", "file.txt", b"later"),
    ):
        source = inputs / relative
        source.parent.mkdir(parents=True, exist_ok=True)
        message = EmailMessage()
        message["Subject"] = "z" if relative == "a.eml" else "mail"
        message.set_content("body")
        message.add_attachment(content, maintype="text", subtype="plain", filename=name)
        source.write_bytes(message.as_bytes())
    output = tmp_path / "out"
    args = [
        str(inputs),
        "-r",
        "--preserve-structure",
        "--pattern",
        "{subject}",
        "-o",
        str(output),
        "--attachments",
        "extract",
        "--attachments-dir",
        ".",
        "--on-conflict",
        "rename",
    ]
    if dry_run:
        args.append("--dry-run")
    result = subprocess.run(
        [str(Path(sys.executable).parent / "maildown"), *args],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    if dry_run:
        assert "Planned: 2" in result.stderr
        assert f"Would write: {output / 'z/mail_1.md'}" in result.stdout
        assert f"Would extract: {output / 'z/mail_1/file.txt'}" in result.stdout
        assert not output.exists()
    else:
        assert "Success: 2" in result.stderr
        assert (output / "z/mail").read_bytes() == b"earlier"
        assert (output / "z/mail_1/file.txt").read_bytes() == b"later"
        assert "(./z/mail)" in (output / "z.md").read_text()
        assert "(./mail_1/file.txt)" in (output / "z/mail_1.md").read_text()
        assert not (output / "z/mail.md").exists()
