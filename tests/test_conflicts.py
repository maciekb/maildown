"""Conflict policy integration regressions."""

from pathlib import Path

import pytest
from click.testing import CliRunner

from maildown.cli import main


@pytest.mark.parametrize(
    "policy,code,count", [("error", 1, 1), ("rename", 0, 2), ("overwrite", 1, 1)]
)
@pytest.mark.parametrize("dry_run", [False, True])
def test_batch_destinations_are_reserved(tmp_path, policy, code, count, dry_run):
    for folder in ("a", "b"):
        source = tmp_path / folder / "same.eml"
        source.parent.mkdir()
        source.write_text(f"Subject: {folder}\n\n{folder}")
    out = tmp_path / "out"
    args = [str(tmp_path), "-r", "-o", str(out), "--on-conflict", policy]
    if dry_run:
        args.append("--dry-run")
    result = CliRunner().invoke(main, args)
    assert result.exit_code == code, result.output
    assert f"{'Planned' if dry_run else 'Success'}: {count}" in result.output
    if dry_run:
        assert not out.exists()
        if policy == "rename":
            assert f"Would write: {out / 'same_1.md'}" in result.output
    else:
        assert len(list(out.glob("*.md"))) == count
        assert "# a" in (out / "same.md").read_text()


@pytest.mark.parametrize("policy,code", [("error", 2), ("rename", 0), ("overwrite", 0)])
def test_existing_output_policy(tmp_path, policy, code):
    source = tmp_path / "mail.eml"
    source.write_text("Subject: new\n\nbody")
    output = source.with_suffix(".md")
    output.write_text("original")
    result = CliRunner().invoke(main, [str(source), "--on-conflict", policy])
    assert result.exit_code == code, result.output
    if policy != "overwrite":
        assert output.read_text() == "original"
    else:
        assert "# new" in output.read_text()
    if policy == "rename":
        assert f"Created: {tmp_path / 'mail_1.md'}" in result.output


@pytest.mark.parametrize("dry_run", [False, True])
def test_attachment_conflict_is_preflighted_in_cli(tmp_path, dry_run):
    source = tmp_path / "mail.eml"
    source.write_bytes((Path(__file__).parent / "fixtures/with-attachment.eml").read_bytes())
    target = tmp_path / "attachments/mail/notes.txt"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"original")
    args = [str(source), "--attachments", "extract", "--on-conflict", "rename"]
    if dry_run:
        args.append("--dry-run")
    result = CliRunner().invoke(main, args)
    assert result.exit_code == 0, result.output
    assert target.read_bytes() == b"original"
    renamed = target.with_name("notes_1.txt")
    if dry_run:
        assert f"Would extract: {renamed}" in result.output
        assert not renamed.exists()
        assert not source.with_suffix(".md").exists()
    else:
        assert renamed.exists()
        assert "notes_1.txt)" in source.with_suffix(".md").read_text()


@pytest.mark.parametrize("policy", ["error", "rename", "overwrite"])
def test_dry_run_detects_file_as_ancestor(tmp_path, policy):
    source = tmp_path / "mail.eml"
    source.write_text("Subject: test\n\nbody")
    blocked = tmp_path / "blocked"
    blocked.write_text("original")
    result = CliRunner().invoke(
        main, [str(source), "-o", str(blocked / "nested"), "--dry-run", "--on-conflict", policy]
    )
    assert result.exit_code == 2
    assert "Planned: 0" in result.output
    assert blocked.read_text() == "original"


def test_preserve_structure_keeps_same_named_emails(tmp_path):
    for folder in ("a", "b"):
        source = tmp_path / "input" / folder / "same.eml"
        source.parent.mkdir(parents=True)
        source.write_text(f"Subject: {folder}\n\nbody")
    out = tmp_path / "out"
    result = CliRunner().invoke(
        main, [str(tmp_path / "input"), "-r", "--preserve-structure", "-o", str(out)]
    )
    assert result.exit_code == 0, result.output
    assert "# a" in (out / "a/same.md").read_text()
    assert "# b" in (out / "b/same.md").read_text()


def test_quiet_still_reports_conflict(tmp_path):
    source = tmp_path / "mail.eml"
    source.write_text("Subject: test\n\nbody")
    source.with_suffix(".md").write_text("original")
    result = CliRunner().invoke(main, [str(source), "--quiet"])
    assert result.exit_code == 2
    assert "Error processing" in result.output
