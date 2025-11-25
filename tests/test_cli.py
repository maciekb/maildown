"""Integration tests for CLI."""

from pathlib import Path

import pytest
from click.testing import CliRunner

from maildown.cli import main

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def runner():
    return CliRunner()


class TestSingleFileConversion:
    def test_converts_single_file(self, runner, tmp_path):
        result = runner.invoke(
            main,
            [str(FIXTURES / "simple-text.eml"), "-o", str(tmp_path)],
        )
        assert result.exit_code == 0
        # Check file was created
        files = list(tmp_path.glob("*.md"))
        assert len(files) == 1

    def test_output_contains_content(self, runner, tmp_path):
        runner.invoke(
            main,
            [str(FIXTURES / "simple-text.eml"), "-o", str(tmp_path)],
        )
        md_file = list(tmp_path.glob("*.md"))[0]
        content = md_file.read_text()
        assert "Hello Anna" in content


class TestDirectoryConversion:
    def test_converts_all_eml_files(self, runner, tmp_path):
        result = runner.invoke(
            main,
            [str(FIXTURES), "-o", str(tmp_path)],
        )
        assert result.exit_code == 0
        files = list(tmp_path.glob("*.md"))
        # Should convert all .eml files in fixtures
        assert len(files) >= 3


class TestDryRun:
    def test_dry_run_no_files_created(self, runner, tmp_path):
        result = runner.invoke(
            main,
            [str(FIXTURES / "simple-text.eml"), "-o", str(tmp_path), "--dry-run"],
        )
        assert result.exit_code == 0
        assert "Would write:" in result.output
        files = list(tmp_path.glob("*.md"))
        assert len(files) == 0


class TestOptions:
    def test_prefer_html(self, runner, tmp_path):
        runner.invoke(
            main,
            [str(FIXTURES / "multipart.eml"), "-o", str(tmp_path), "--prefer-html"],
        )
        md_file = list(tmp_path.glob("*.md"))[0]
        content = md_file.read_text()
        # HTML version has italic "HTML version"
        assert "*HTML version*" in content or "_HTML version_" in content

    def test_no_frontmatter(self, runner, tmp_path):
        runner.invoke(
            main,
            [str(FIXTURES / "simple-text.eml"), "-o", str(tmp_path), "--no-frontmatter"],
        )
        md_file = list(tmp_path.glob("*.md"))[0]
        content = md_file.read_text()
        # Should not start with YAML frontmatter
        assert not content.startswith("---")

    def test_custom_pattern(self, runner, tmp_path):
        runner.invoke(
            main,
            [
                str(FIXTURES / "simple-text.eml"),
                "-o",
                str(tmp_path),
                "-p",
                "{from}-{subject}",
            ],
        )
        files = list(tmp_path.glob("*.md"))
        assert len(files) == 1
        assert "jan-kowalski" in files[0].name.lower()


class TestAttachments:
    def test_attachments_list_mode(self, runner, tmp_path):
        runner.invoke(
            main,
            [
                str(FIXTURES / "with-attachment.eml"),
                "-o",
                str(tmp_path),
                "--attachments=list",
            ],
        )
        md_file = list(tmp_path.glob("*.md"))[0]
        content = md_file.read_text()
        assert "## Attachments" in content
        assert "notes.txt" in content

    def test_attachments_extract_mode(self, runner, tmp_path):
        runner.invoke(
            main,
            [
                str(FIXTURES / "with-attachment.eml"),
                "-o",
                str(tmp_path),
                "--attachments=extract",
            ],
        )
        # Check attachment was extracted
        attachment_dirs = list((tmp_path / "attachments").glob("*"))
        assert len(attachment_dirs) >= 1
        attachment_files = list(attachment_dirs[0].glob("*.txt"))
        assert len(attachment_files) == 1


class TestErrorHandling:
    def test_nonexistent_file(self, runner, tmp_path):
        result = runner.invoke(
            main,
            ["/nonexistent/file.eml", "-o", str(tmp_path)],
        )
        assert result.exit_code == 2  # Total failure

    def test_fail_fast(self, runner, tmp_path):
        result = runner.invoke(
            main,
            ["/nonexistent/file.eml", str(FIXTURES / "simple-text.eml"), "--fail-fast"],
        )
        # Should stop at first error
        assert result.exit_code != 0


class TestVersionFlag:
    def test_version(self, runner):
        result = runner.invoke(main, ["--version"])
        assert result.exit_code == 0
        assert "0.1.0" in result.output
