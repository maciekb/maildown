# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Maildown is a CLI tool for converting EML (email) files to Markdown format. It supports batch processing, configurable output formats, and attachment handling.

## Development Commands

```bash
# Setup (always use venv, never system Python)
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Run tests
pytest                      # all tests
pytest tests/test_parser.py # single module
pytest -k "test_slugify"    # single test by name
pytest --cov=maildown       # with coverage

# Lint
ruff check .
ruff format .

# Run CLI
maildown --help
maildown tests/fixtures/simple-text.eml -o /tmp/out
```

## Architecture

Data flows through a pipeline:

```
EML file → parser.py → ParsedEmail dataclass → converter.py → Markdown string → writer.py → .md file
```

**Key modules:**
- `parser.py`: Parses EML using stdlib `email`, extracts headers/body/attachments into `ParsedEmail` dataclass
- `converter.py`: Transforms `ParsedEmail` to Markdown string, handles frontmatter generation, HTML→MD conversion via markdownify, attachment formatting
- `writer.py`: Determines output paths, writes files, extracts attachments
- `cli.py`: Click-based CLI, file collection (glob/recursive), batch processing with error handling

**Important behaviors:**
- Default output filename matches source (email.eml → email.md), use `--pattern` for custom naming
- Frontmatter uses manual YAML generation (not python-frontmatter library) to handle special characters in email addresses
- `slugify()` in converter.py has special character map for Polish letters (ł→l) that don't decompose in NFKD normalization

## Testing

Test fixtures in `tests/fixtures/` contain sample EML files (plain text, HTML, multipart, with attachments, UTF-8). Tests use pytest with Click's `CliRunner` for CLI integration tests.
