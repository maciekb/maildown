# Email conversion

Maildown converts emails into Markdown documents and optionally saves their attachments.

## Language

**Destination**:
A path chosen for a converted Markdown document or an extracted attachment.

**Destination reservation**:
A claim on a destination within a conversion batch, preventing another output
from occupying that path or using it as a directory.

**Write plan**:
The final destinations for one email's Markdown document and extracted attachments.
A successful plan reserves those destinations even if writing later fails.
