"""Filesystem case semantics for destination reservations."""

import os
from pathlib import Path

import pytest

from maildown import writer
from maildown.converter import AttachmentMode, ConversionOptions
from maildown.parser import Attachment, ParsedEmail
from maildown.writer import write_markdown

EXTRACT = ConversionOptions(attachment_mode=AttachmentMode.EXTRACT)


@pytest.fixture
def macos_probe(monkeypatch):
    """Make the destination probe agree with forced case-insensitive indexes."""
    monkeypatch.setattr(writer, "_case_probe_cache", {})
    monkeypatch.setattr(writer, "probe_case_insensitive", lambda path: True)


@pytest.fixture
def sensitive_probe(monkeypatch):
    """Make the destination probe agree with forced case-sensitive indexes."""
    monkeypatch.setattr(writer, "_case_probe_cache", {})
    monkeypatch.setattr(writer, "probe_case_insensitive", lambda path: False)


def snapshot(root: Path):
    return sorted((str(path.relative_to(root)), path.is_dir()) for path in root.rglob("*"))


class TestProbe:
    def test_reports_case_sensitive_for_local_ext4_dir(self, tmp_path):
        (tmp_path / "Existing.txt").write_bytes(b"x")
        assert writer.probe_case_insensitive(tmp_path) is False

    def test_reports_case_sensitive_for_empty_dir(self, tmp_path):
        assert writer.probe_case_insensitive(tmp_path) is False

    def test_creates_and_modifies_nothing(self, tmp_path):
        (tmp_path / "Keep.txt").write_bytes(b"x")
        (tmp_path / "sub").mkdir()
        target = tmp_path / "missing" / "deeper"
        before = snapshot(tmp_path)
        assert writer.probe_case_insensitive(target) is False
        assert not (tmp_path / "missing").exists()
        assert snapshot(tmp_path) == before

    @pytest.mark.parametrize(
        "weird",
        ["nul", "newline", "file-as-ancestor", "symlink-loop", "broken-symlink"],
    )
    def test_weird_paths_do_not_raise(self, tmp_path, weird):
        if weird == "nul":
            path = Path(str(tmp_path / "x") + "\x00y")
        elif weird == "newline":
            path = tmp_path / "line\nbreak" / "child"
        elif weird == "file-as-ancestor":
            (tmp_path / "afile").write_bytes(b"x")
            path = tmp_path / "afile" / "child"
        elif weird == "symlink-loop":
            (tmp_path / "loop").symlink_to(tmp_path / "loop")
            path = tmp_path / "loop" / "child"
        else:
            (tmp_path / "broken").symlink_to(tmp_path / "missing" / "target")
            path = tmp_path / "broken" / "child"
        assert writer.probe_case_insensitive(path) is False

    def test_probe_is_cached_per_directory(self, tmp_path, monkeypatch):
        (tmp_path / "Anything.txt").write_bytes(b"x")
        calls = []
        real_listdir = os.listdir

        def counting_listdir(path):
            calls.append(path)
            return real_listdir(path)

        monkeypatch.setattr(writer, "_case_probe_cache", {})
        monkeypatch.setattr(os, "listdir", counting_listdir)
        first = writer.probe_case_insensitive(tmp_path / "missing1")
        second = writer.probe_case_insensitive(tmp_path / "missing2" / "deep")
        assert first is False and second is False
        assert len(calls) == 1

    def test_detects_case_insensitivity_when_swapcase_is_same_file(self, tmp_path, monkeypatch):
        (tmp_path / "Readme").write_bytes(b"x")
        monkeypatch.setattr(writer, "_case_probe_cache", {})
        monkeypatch.setattr(writer.os.path, "samefile", lambda a, b: True)
        assert writer.probe_case_insensitive(tmp_path) is True

    def test_inconclusive_probe_falls_back_to_platform_default(self, tmp_path, monkeypatch):
        import sys

        (tmp_path / "Readme").write_bytes(b"x")

        def missing(a, b):
            raise FileNotFoundError(b)

        monkeypatch.setattr(writer.os.path, "samefile", missing)
        monkeypatch.setattr(writer, "_case_probe_cache", {})
        monkeypatch.setattr(sys, "platform", "darwin")
        assert writer.probe_case_insensitive(tmp_path) is True
        monkeypatch.setattr(writer, "_case_probe_cache", {})
        monkeypatch.setattr(sys, "platform", "linux")
        assert writer.probe_case_insensitive(tmp_path) is False


def case_variant_email():
    return ParsedEmail(
        attachments=[
            Attachment("foo.txt", "text/plain", 3, b"one"),
            Attachment("FOO.txt", "text/plain", 3, b"two"),
        ]
    )


class TestFoldedReservations:
    def test_same_email_case_variant_attachments_conflict(self, tmp_path, macos_probe):
        index = writer.ReservationIndex(case_insensitive=True)
        with pytest.raises(FileExistsError):
            write_markdown(case_variant_email(), tmp_path / "mail.md", EXTRACT, reservations=index)
        assert not list(tmp_path.iterdir())
        writer.plan_write(ParsedEmail(), tmp_path / "MAIL.md", reservations=index)
        writer.plan_write(ParsedEmail(), tmp_path / "ATTACHMENTS/MAIL", reservations=index)

    def test_rename_policy_keeps_case_variant_attachments_distinct(self, tmp_path, macos_probe):
        index = writer.ReservationIndex(case_insensitive=True)
        output = write_markdown(
            case_variant_email(),
            tmp_path / "mail.md",
            EXTRACT,
            on_conflict="rename",
            reservations=index,
        )
        folder = tmp_path / "attachments" / "mail"
        assert (folder / "foo.txt").read_bytes() == b"one"
        assert (folder / "FOO_1.txt").read_bytes() == b"two"
        text = output.read_text()
        assert "(./attachments/mail/foo.txt)" in text
        assert "(./attachments/mail/FOO_1.txt)" in text

    def test_overwrite_policy_still_rejects_case_variant_duplicates(self, tmp_path, macos_probe):
        index = writer.ReservationIndex(case_insensitive=True)
        with pytest.raises(FileExistsError):
            write_markdown(
                case_variant_email(),
                tmp_path / "mail.md",
                EXTRACT,
                on_conflict="overwrite",
                reservations=index,
            )
        assert not list(tmp_path.iterdir())
        writer.plan_write(ParsedEmail(), tmp_path / "MAIL.md", reservations=index)

    def test_overwrite_rejects_duplicates_when_case_variant_exists_on_disk(
        self, tmp_path, macos_probe
    ):
        index = writer.ReservationIndex(case_insensitive=True)
        folder = tmp_path / "attachments" / "mail"
        folder.mkdir(parents=True)
        (folder / "FOO.txt").write_bytes(b"disk")
        with pytest.raises(FileExistsError):
            write_markdown(
                case_variant_email(),
                tmp_path / "mail.md",
                EXTRACT,
                on_conflict="overwrite",
                reservations=index,
            )
        assert (folder / "FOO.txt").read_bytes() == b"disk"
        assert not (tmp_path / "mail.md").exists()
        assert not (folder / "foo.txt").exists()

    def test_forced_case_sensitive_index_plans_both_variants(self, tmp_path, sensitive_probe):
        index = writer.ReservationIndex(case_insensitive=False)
        output = write_markdown(
            case_variant_email(), tmp_path / "mail.md", EXTRACT, reservations=index
        )
        folder = tmp_path / "attachments" / "mail"
        assert (folder / "foo.txt").read_bytes() == b"one"
        assert (folder / "FOO.txt").read_bytes() == b"two"
        text = output.read_text()
        assert "(./attachments/mail/foo.txt)" in text
        assert "(./attachments/mail/FOO.txt)" in text

    def test_undetected_index_keeps_case_variants_distinct_on_sensitive_host(self, tmp_path):
        if writer.probe_case_insensitive(tmp_path):
            pytest.skip("host filesystem is case-insensitive")
        index = writer.ReservationIndex()
        output = write_markdown(
            case_variant_email(), tmp_path / "mail.md", EXTRACT, reservations=index
        )
        assert index.case_insensitive is False
        folder = tmp_path / "attachments" / "mail"
        assert (folder / "foo.txt").read_bytes() == b"one"
        assert (folder / "FOO.txt").read_bytes() == b"two"
        assert "(./attachments/mail/FOO.txt)" in output.read_text()

    def test_batch_shared_index_detects_case_variant_output_across_emails(
        self, tmp_path, macos_probe
    ):
        index = writer.ReservationIndex(case_insensitive=True)
        first = ParsedEmail(attachments=[Attachment("foo.txt", "text/plain", 3, b"one")])
        writer.plan_write(first, tmp_path / "mail.md", EXTRACT, reservations=index)
        second = ParsedEmail(attachments=[Attachment("FOO.txt", "text/plain", 3, b"two")])
        with pytest.raises(FileExistsError):
            writer.plan_write(second, tmp_path / "MAIL.md", EXTRACT, reservations=index)
        assert not list(tmp_path.iterdir())

    def test_batch_reserved_attachment_blocks_case_variant_destination(self, tmp_path, macos_probe):
        index = writer.ReservationIndex(case_insensitive=True)
        first = ParsedEmail(attachments=[Attachment("foo.txt", "text/plain", 3, b"one")])
        writer.plan_write(first, tmp_path / "mail.md", EXTRACT, reservations=index)
        target = tmp_path / "attachments" / "mail" / "FOO.txt"
        with pytest.raises(FileExistsError):
            writer.plan_write(ParsedEmail(), target, EXTRACT, reservations=index)

    def test_cli_dry_run_reports_case_variant_collision(self, tmp_path, monkeypatch, macos_probe):
        from click.testing import CliRunner

        from maildown import cli as cli_module
        from maildown.cli import main

        monkeypatch.setattr(
            cli_module,
            "ReservationIndex",
            lambda *args, **kwargs: writer.ReservationIndex(case_insensitive=True),
        )
        source = tmp_path / "mail.eml"
        source.write_text(
            'MIME-Version: 1.0\nContent-Type: multipart/mixed; boundary="x"\n\n'
            "--x\nContent-Type: text/plain\n\nbody\n"
            "--x\nContent-Type: application/octet-stream\n"
            'Content-Disposition: attachment; filename="foo.txt"\n\none\n'
            "--x\nContent-Type: application/octet-stream\n"
            'Content-Disposition: attachment; filename="FOO.txt"\n\ntwo\n'
            "--x--\n"
        )
        result = CliRunner().invoke(main, [str(source), "--attachments", "extract", "--dry-run"])
        assert result.exit_code == 2, result.output
        assert "Error processing" in result.output
        assert "reserved" in result.output
        assert "Planned: 0" in result.output
        assert not list(tmp_path.glob("**/attachments"))

    def test_detection_applies_case_semantics_to_seeded_reservations(self, tmp_path, monkeypatch):
        reserved = (tmp_path / "attachments" / "mail" / "foo.txt").resolve()
        index = writer.ReservationIndex({reserved}, {reserved.parent, tmp_path.resolve()})
        monkeypatch.setattr(writer, "_case_probe_cache", {})
        monkeypatch.setattr(writer, "probe_case_insensitive", lambda path: True)
        with pytest.raises(FileExistsError):
            writer.plan_write(
                ParsedEmail(attachments=[Attachment("FOO.txt", "text/plain", 1, b"x")]),
                tmp_path / "mail.md",
                EXTRACT,
                reservations=index,
            )
        assert index.case_insensitive is True

    def test_rename_plan_reserves_final_case_variant_destinations(self, tmp_path, macos_probe):
        index = writer.ReservationIndex(case_insensitive=True)
        plan = writer.plan_write(
            case_variant_email(),
            tmp_path / "mail.md",
            EXTRACT,
            on_conflict="rename",
            reservations=index,
        )
        folder = tmp_path / "attachments" / "mail"
        assert plan.attachments == {0: folder / "foo.txt", 1: folder / "FOO_1.txt"}
        for path in (tmp_path / "MAIL.md", folder / "FOO.txt", folder / "foo_1.txt"):
            with pytest.raises(FileExistsError):
                writer.plan_write(ParsedEmail(), path, reservations=index)
        with pytest.raises(FileExistsError):
            writer.plan_write(ParsedEmail(), tmp_path / "ATTACHMENTS/MAIL", reservations=index)
        assert (
            writer.plan_write(ParsedEmail(), folder / "foo_2.txt", reservations=index).output_path
            == folder / "foo_2.txt"
        )

    def test_stem_namespace_blocked_by_case_variant_reserved_file(self, tmp_path, macos_probe):
        index = writer.ReservationIndex(case_insensitive=True)
        writer.plan_write(
            ParsedEmail(), tmp_path / "attachments" / "MAIL", EXTRACT, reservations=index
        )
        plan = writer.plan_write(
            ParsedEmail(attachments=[Attachment("file.txt", "text/plain", 1, b"x")]),
            tmp_path / "mail.md",
            EXTRACT,
            on_conflict="rename",
            reservations=index,
        )
        assert plan.output_path == tmp_path / "mail_1.md"
        assert plan.attachments[0] == tmp_path / "attachments" / "mail_1" / "file.txt"

    def test_legacy_set_api_prefolds_existing_reservations(self, tmp_path, monkeypatch):
        reserved = tmp_path / "attachments" / "mail" / "foo.txt"
        reservations = {reserved}
        monkeypatch.setattr(writer, "_case_probe_cache", {})
        monkeypatch.setattr(writer, "probe_case_insensitive", lambda path: True)
        with pytest.raises(FileExistsError):
            writer.plan_write(
                ParsedEmail(attachments=[Attachment("FOO.txt", "text/plain", 1, b"x")]),
                tmp_path / "mail.md",
                EXTRACT,
                reservations=reservations,
            )
        assert reservations == {reserved}
