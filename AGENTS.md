# Agent instructions

Shared project instructions for coding agents. Maintain common guidance here;
`CLAUDE.md` imports this file for Claude Code.

## Project Overview

Maildown is a CLI tool for converting EML (email) files to Markdown format. It supports batch processing, configurable output formats, and attachment handling.

## Development Commands

```bash
# Setup (always use venv, never system Python)
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"

# Run tests
.venv/bin/python -m pytest                      # all tests
.venv/bin/python -m pytest tests/test_parser.py # single module
.venv/bin/python -m pytest -k "test_slugify"    # single test by name
.venv/bin/python -m pytest --cov=maildown       # with coverage

# Lint
.venv/bin/ruff check .
.venv/bin/ruff format --check .
# Apply formatting when needed
.venv/bin/ruff format .

# Run CLI
.venv/bin/maildown --help
.venv/bin/maildown tests/fixtures/simple-text.eml -o /tmp/out
```

## Architecture

The CLI shares a `ReservationIndex` across a batch. Both dry runs and writes
use `plan_write`; writing converts the email only after final paths are known.
For changes to output planning or attachments, read README.md sections
"Attachment Handling" and "Conflicts and dry runs", plus the writer tests.

Data flows through a pipeline:

```
EML → parse → plan destinations → convert using final attachment paths → write
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

## Validation and handoff

After code or tooling changes, run the full test suite, Ruff lint, and Ruff
format check using the commands above. For documentation-only edits, check
links and `git diff --check`. Report checks run and any failures.

Switch agents between tasks. When handing off unfinished work, include the task
or issue, changed files, checks and results, and remaining work in the handoff
message. Keep durable project knowledge in tracked documentation so the next
agent can work without the previous agent's private memory.

## Agent skills

### Issue tracker

Track issues and specs in GitHub Issues. Before tracker operations, read `docs/agents/issue-tracker.md`.

### Triage labels

Use the five default triage labels. Before triaging, read `docs/agents/triage-labels.md`.

### Domain docs

Use a single-context layout. Before exploring the codebase, read `docs/agents/domain.md`.
