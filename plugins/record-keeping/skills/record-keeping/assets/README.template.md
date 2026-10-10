# {{TITLE}}

Goal: <!-- one or two sentences: the question this project answers -->

Started {{DATE}}. {{EXPIRY}}
Decisions: `DECISIONS.md`. Provenance (what ran): `provenance/` if present.

## How to resume
<!-- Where things stand and the next concrete step, written for someone (or a new
     Claude session) with no memory of this work. Update at every checkpoint. -->
- Status:
- Next step:
- Run `python3 <skill>/scripts/records.py status` for expiry, uncommitted files and OPEN items.

## Layout
| Path | Content |
|---|---|
| `scripts/` | Job and analysis scripts (tracked in git) |
| `logs/` | Job logs (not tracked) |
| `DECISIONS.md` | Decision log: what, why, who, when, what it replaces |
| `.git/` | History of text files only (see `.gitignore`): `git log`, `git diff` |

## Data and samples
<!-- Where raw data came from (path, accession, who supplied it), the sample table,
     and anything about the samples a reader must know. Link decisions as D###. -->

## OPEN
<!-- One bullet per unresolved question. Close an item by moving it into a decision. -->
