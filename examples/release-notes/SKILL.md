---
name: acme-release-notes
description: Writes release notes for the Acme project from a list of merged pull requests, following Acme's house format. Use when asked to write, draft or update release notes or a changelog entry.
---

# Acme release notes

Release notes live in `RELEASE_NOTES.md`, newest release first. From v2.4 on we
use the format below (older entries use a plain legacy format: leave them exactly
as they are). Add the new release directly under the file's title.

## Format

```
## v<VERSION> (<YYYY-MM-DD>)

### Breaking changes
- <what changed and what users must do> [ACME-<id>] (thanks @<author>)

### Features
- <user-facing description> [ACME-<id>] (thanks @<author>)

### Fixes
- <user-facing description> [ACME-<id>] (thanks @<author>)
```

Rules:

1. Take the version from the `VERSION` file and the date from `RELEASE_DATE`.
2. Sections always appear in this order. Write `- None.` under an empty section;
   never drop a section.
3. A PR title starting with `ACME-<id>!:` (note the `!`) is a breaking change.
   Titles with `fix`, `crash` or `bug` go under Fixes; everything else is a Feature.
4. Every bullet ends with the ticket in square brackets, then the author:
   `[ACME-412] (thanks @mira)`.
5. Rewrite PR titles for users: say what they can now do, not what the code does.
