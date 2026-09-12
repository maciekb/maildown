# Maildown

Convert EML files to Markdown.

## Installation

```bash
git clone https://github.com/maciekb/maildown.git
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Usage

```bash
# Convert single file
maildown email.eml

# Convert directory
maildown ./inbox/

# Convert recursively, preserving folders to avoid flattened filename collisions
maildown ./mail/ -r --preserve-structure -o ./converted/

# Use glob pattern
maildown "*.eml"
```

### Output Options

```bash
-o, --output DIR              # Output directory (default: next to source)
-p, --pattern TEMPLATE        # Filename pattern (default: source filename)
    --preserve-structure      # Preserve folders for a single directory input
    --on-conflict POLICY      # error|rename|overwrite (default: error)
```

**Pattern placeholders:** `{date}`, `{datetime}`, `{subject}`, `{from}`, `{from_email}`

```bash
maildown email.eml -p "{date}-{subject}"   # → 2024-03-15-meeting-notes.md
```

### Content Options

```bash
--prefer-html                 # Prefer HTML body over plain text
--no-frontmatter              # Disable YAML frontmatter
--include-headers LIST        # Headers in frontmatter (comma-separated)
```

### Attachment Handling

```bash
--attachments MODE            # ignore|list|extract|embed (default: list)
--attachments-dir DIR         # Directory for extracted attachments
```

| Mode | Behavior |
|------|----------|
| `ignore` | Skip attachments |
| `list` | List filenames in Markdown |
| `extract` | Save to disk, link in Markdown |
| `embed` | Embed images <100,000 decoded bytes; extract and link everything else |

Extracted files live in `DIR/<final-markdown-stem>/` beside the Markdown file
(`DIR` defaults to `attachments`). `--attachments-dir` must be a relative path
without `..`, Windows drive syntax, or backslashes. Nested relative directories
are supported. Unsafe attachment names (empty, dot/dot-dot, path separators,
colon, or NUL) become `attachment_<1-based-position>.bin` deterministically.
Missing or empty MIME filenames use the same positional fallback during parsing.
Links use each attachment's actual final filename, with URL special characters
percent-encoded, including renamed duplicates. The original name remains the
link label. Embedded images are **not also extracted**; images of exactly
100,000 bytes and all non-images are extracted. Image eligibility uses the MIME
content type, not image decoding or validation.

### Conflicts and dry runs

Existing files are **never overwritten by default**. The policy applies to both
Markdown and extracted attachments:

- `error` (default): report a conflict and fail that email before writing any of
  its files when a conflict is found during preflight.
- `rename`: choose the first free `_1`, `_2`, … suffix before the extension.
  Renaming the Markdown file also changes its attachment subdirectory.
  When extracting attachments, skip Markdown candidates whose stem-specific
  attachment directory is an existing or reserved file, even if the Markdown
  file itself is absent. A blocked common ancestor (such as `attachments`),
  symlinks, or a hardlinked stem blocker still fail rather than triggering retries.
- `overwrite`: explicitly replace existing regular files. Directories and
  symlinks are never overwritten; regular files with multiple hardlinks are
  rejected during planning and rechecked immediately before overwrite.
  Duplicate destinations within an email or
  across a batch still fail, rather than counting overwritten conversions as
  successes. Use `rename` to retain all colliding emails or attachments.

All output paths, including attachment paths and their ancestors, are checked
for symlinks (including dangling links) and rejected under every policy. Use a
real output directory, not a symlink. These checks are not a sandbox against
another process concurrently replacing paths or adding hardlinks between a check
and a write; use a trusted output tree.
Writes are not a multi-file transaction: an I/O failure after preflight can leave
partial output. Default/rename writes use exclusive file creation, so a file
created by another process after planning is not silently overwritten.

Batch destinations are reserved in sorted input-path order, including during
`--dry-run`, using an incremental file/directory index. Python batch callers
should share a `maildown.writer.ReservationIndex` across calls; the legacy
`set[Path]` argument remains supported but rebuilds its directory index per call.
Failed plans do not commit reservations. Reservations from a successful plan
remain if a later write fails, since partial files may already exist.

Dry runs create no directories or files, report the final planned
Markdown and extracted-attachment paths, detect conflicts, and show `Planned`
rather than `Success` counts. They cannot predict later permission, disk-space,
or concurrent filesystem changes. Exit codes have the same success/partial/
failure meanings for planning as for writing; `--quiet` still reports errors.

```bash
maildown ./mail/ -r --preserve-structure -o ./converted/ --attachments extract --dry-run
maildown ./mail/ -r -o ./converted/ --attachments extract --on-conflict rename
```

Structure preservation requires a **single directory input**; multiple inputs
or glob inputs retain the flat-output behavior. Even with preserved folders,
custom filename patterns can collide, so the conflict policy still applies.

### Other Options

```bash
--fail-fast                   # Stop on first error
-v, --verbose                 # Verbose output
-q, --quiet                   # Only show errors
--dry-run                     # Preview without writing
```

## Output Format

```markdown
---
date: 2024-03-15T10:30:00+01:00
from: "Jan Kowalski <jan@example.com>"
to: "Anna Nowak <anna@example.com>"
subject: Meeting notes
---

# Meeting notes

Email body content here...

## Attachments

- document.pdf (245 KB)
- image.png (12 KB)
```

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Partial success (some errors) |
| 2 | Complete failure |

## License

MIT
