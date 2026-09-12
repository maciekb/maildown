"""Round-3 review regressions: portable names, dir validation, lexical paths, index contract."""

import os
from pathlib import Path

import pytest

from maildown import writer
from maildown.converter import AttachmentMode, ConversionOptions
from maildown.parser import Attachment, ParsedEmail, safe_attachment_name
from maildown.writer import ReservationIndex, plan_write, write_markdown

EXTRACT = ConversionOptions(attachment_mode=AttachmentMode.EXTRACT)


def message(*names):
    return ParsedEmail(attachments=[Attachment(n, "text/plain", 1, b"x") for n in names])


class TestPortableAttachmentNames:
    @pytest.mark.parametrize(
        "name",
        [
            "CON",
            "con",
            "Con.txt",
            "CON.txt",
            "aux.tar.gz",
            "NUL",
            "nul.png",
            "com1",
            "COM9",
            "LPT4",
            "lpt1.tar",
        ],
    )
    def test_windows_reserved_names_use_positional_fallback(self, name):
        assert safe_attachment_name(name, 0) == "attachment_1.bin"

    @pytest.mark.parametrize("name", ["report.txt.", "report.txt ", "dir "])
    def test_trailing_dot_or_space_uses_positional_fallback(self, name):
        assert safe_attachment_name(name, 0) == "attachment_1.bin"

    @pytest.mark.parametrize("char", list('<>"|?*'))
    def test_windows_forbidden_chars_use_positional_fallback(self, char):
        assert safe_attachment_name(f"bad{char}name.txt", 0) == "attachment_1.bin"

    @pytest.mark.parametrize(
        "name",
        [
            "report.txt",
            "image 1.png",
            "zażółć.txt",
            "name[1].txt",
            "report #%%().txt",
            ".hidden",
            "report..txt",
            "report .txt",
            " report.txt",
        ],
    )
    def test_portable_safe_names_are_kept(self, name):
        assert safe_attachment_name(name, 0) == name

    def test_reserved_name_falls_back_when_writing(self, tmp_path):
        output = write_markdown(message("CON.txt"), tmp_path / "mail.md", EXTRACT)
        files = list((tmp_path / "attachments" / "mail").iterdir())
        assert [path.name for path in files] == ["attachment_1.bin"]
        assert "attachment_1.bin" in output.read_text()


class TestPortableAttachmentDirectories:
    @pytest.mark.parametrize(
        "directory",
        [
            "bad?dir",
            "CON",
            "con",
            "attachments/CON",
            "a/bad dir ",
            "bad.",
            "x|y",
            'a"b',
            "a<b",
            "attachments/nested/x*y",
        ],
    )
    @pytest.mark.parametrize("mode", [AttachmentMode.EXTRACT, AttachmentMode.EMBED])
    def test_unsafe_directory_components_are_rejected(self, tmp_path, directory, mode):
        with pytest.raises(ValueError, match="Unsafe attachment directory"):
            plan_write(
                message("file.txt"),
                tmp_path / "mail.md",
                ConversionOptions(attachment_mode=mode, attachments_dir=directory),
            )
        assert not list(tmp_path.iterdir())

    @pytest.mark.parametrize("directory", ["attachments", "a/b"])
    def test_portable_directories_are_allowed(self, tmp_path, directory):
        write_markdown(
            message("file.txt"),
            tmp_path / "mail.md",
            ConversionOptions(attachment_mode=AttachmentMode.EXTRACT, attachments_dir=directory),
        )
        assert (tmp_path / directory / "mail" / "file.txt").read_bytes() == b"x"


class TestLexicallyNormalizedDestinations:
    def test_parent_reference_output_is_normalized_and_writes_no_spurious_dirs(self, tmp_path):
        plan = plan_write(message(), tmp_path / "nested/../mail.md")
        assert plan.output_path == tmp_path / "mail.md"
        write_markdown(message("file.txt"), tmp_path / "nested/../mail.md", EXTRACT)
        assert (tmp_path / "mail.md").exists()
        assert (tmp_path / "attachments/mail/file.txt").read_bytes() == b"x"
        assert not (tmp_path / "nested").exists()

    def test_parent_reference_collision_is_detected(self, tmp_path):
        (tmp_path / "real.md").write_text("original")
        with pytest.raises(FileExistsError):
            plan_write(message(), tmp_path / "nested/../real.md", on_conflict="error")
        assert (tmp_path / "real.md").read_text() == "original"
        assert not (tmp_path / "nested").exists()

    def test_rename_candidates_are_normalized_through_lexical_alias(self, tmp_path):
        (tmp_path / "mail.md").write_text("original")
        plan = plan_write(message(), tmp_path / "deep/deeper/../../mail.md", on_conflict="rename")
        assert plan.output_path == tmp_path / "mail_1.md"
        assert "deep" not in plan.output_path.parts
        assert "deeper" not in plan.output_path.parts

    @pytest.mark.parametrize(
        "alias", ["a//b/./mail.md", "./mail.md", "nested/../nested/../mail.md"]
    )
    def test_alias_reservations_collide_in_dry_run_without_creating_dirs(self, tmp_path, alias):
        reservations = ReservationIndex()
        first = plan_write(message(), tmp_path / alias, reservations=reservations)
        assert first.output_path == Path(os.path.normpath(tmp_path / alias))
        with pytest.raises(FileExistsError):
            plan_write(message(), tmp_path / alias, on_conflict="error", reservations=reservations)
        assert not list(tmp_path.iterdir())


class TestSingleFilesystemContract:
    def test_forced_index_conflicting_probe_verdict_raises_before_reserving(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(writer, "_case_probe_cache", {str(tmp_path): False})
        index = writer.ReservationIndex(case_insensitive=True)
        with pytest.raises(ValueError, match="different case semantics"):
            plan_write(message("file.txt"), tmp_path / "mail.md", EXTRACT, reservations=index)
        assert index.files == set() and index.directories == set()
        assert index.folded_files == set() and index.folded_directories == set()

    def test_conflicting_probe_verdict_message_names_the_remedy(self, tmp_path, monkeypatch):
        monkeypatch.setattr(writer, "probe_case_insensitive", lambda path: False)
        index = writer.ReservationIndex(case_insensitive=True)
        with pytest.raises(ValueError, match="use a separate ReservationIndex per filesystem"):
            plan_write(message(), tmp_path / "mail.md", reservations=index)
        assert index.files == set()

    def test_matching_verdicts_plan_across_multiple_emails(self, tmp_path, monkeypatch):
        monkeypatch.setattr(writer, "probe_case_insensitive", lambda path: True)
        index = writer.ReservationIndex(case_insensitive=True)
        plan_write(message("a.txt"), tmp_path / "one.md", EXTRACT, reservations=index)
        plan_write(message("b.txt"), tmp_path / "two.md", EXTRACT, reservations=index)
        assert len(index.files) == 4

    def test_first_plan_stores_probed_verdict(self, tmp_path):
        index = writer.ReservationIndex()
        plan_write(message(), tmp_path / "mail.md", reservations=index)
        assert index.case_insensitive is writer.probe_case_insensitive(tmp_path)

    def test_legacy_set_callers_keep_single_verdict_behavior(self, tmp_path, monkeypatch):
        monkeypatch.setattr(writer, "_case_probe_cache", {str(tmp_path): False})
        reservations = set()
        plan_write(message(), tmp_path / "one.md", reservations=reservations)
        plan_write(message(), tmp_path / "two.md", reservations=reservations)
        assert len(reservations) == 2
