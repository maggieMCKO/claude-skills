# Changelog

Follows [Semantic Versioning](https://semver.org). Versions below 1.0.0 signal
that the command-line interface may still change.

## 0.1.0 - 2026-10-10

First version, distilled from the conventions improvised during a multi-day RNA-seq
analysis on an HPC workspace that expires (README with a resume section, decisions with
"confirmed by user" dates, a whitelist `.gitignore`, a commit per step, archiving).

### Added
- `SKILL.md`: when to set up records, what counts as a decision, who-decided categories,
  checkpoint routine, resuming, expiry and archiving.
- `scripts/records.py` (stdlib): `init`, `track`, `decide`, `checkpoint`, `status`, `archive`.
  - `decide` numbers entries D001…, supersedes without rewriting history, and keeps
    Claude's unconfirmed choices visible in `status` until the user confirms them.
  - `checkpoint` records README/DECISIONS edits as a provenance-log step, renders
    PROVENANCE.md and commits.
  - `archive` copies git-tracked files plus chosen result paths, verifies by SHA-256 and
    writes `ARCHIVE_MANIFEST.tsv`.
- Templates for README, DECISIONS.md and the whitelist `.gitignore`.
- Tests (`tests/test_records.py`, stdlib).
