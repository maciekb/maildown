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

# Convert recursively with output directory
maildown ./mail/ -r -o ./converted/

# Use glob pattern
maildown "*.eml"
```

### Output Options

```bash
-o, --output DIR              # Output directory (default: next to source)
-p, --pattern TEMPLATE        # Filename pattern (default: source filename)
    --preserve-structure      # Preserve directory structure with -r
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
| `embed` | Base64 encode images inline |

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
