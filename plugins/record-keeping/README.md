# record-keeping

An Agent Skill for the human side of a computational research project. Its companion,
[provenance-log](../provenance-log/), records *what ran*. This one records *why*, and
*how to pick the work up again*:

- **README.md** with a *How to resume* section and an *OPEN* list, updated at every step.
- **DECISIONS.md**: numbered decisions with the reason, whose call it was (user,
  user-confirmed, Claude-unconfirmed, agreed, external), the date, evidence, and what each
  replaces. Old entries are never rewritten.
- **Text-only git**: a whitelist `.gitignore` (data never enters git), local identity,
  one commit per pipeline step, never pushed unless you ask.
- **Expiry and archiving**: the storage expiry date is recorded; `status` warns two weeks
  ahead; `archive` copies scripts, records and chosen results to permanent storage and
  verifies every file by checksum.

## Commands

`skills/record-keeping/scripts/records.py` (Python 3.8+, stdlib only):

| Command | Does |
|---|---|
| `init --title T [--expires DATE] [--archive-to PATH] [--git-name N --git-email E]` | Creates README, DECISIONS.md, `.gitignore`, `scripts/`, `logs/`, git repo. Never overwrites. |
| `track PATH...` | Whitelists text files or folders in `.gitignore` (handles nested paths); warns on large files. |
| `decide --what --why --by {user,user-confirmed,claude,agreed,external} [--supersedes Dnnn]` | Appends a numbered decision. |
| `checkpoint -m MSG` | provenance-log step for README/decision edits, `render`, git commit. |
| `status` | Days to expiry, last archive, uncommitted files, OPEN items, unconfirmed and recent decisions. |
| `archive --to PATH [--include DIR]... [--dry-run] [--verify sha256\|size]` | Copies and verifies; writes `ARCHIVE_MANIFEST.tsv`. |

## Install

As a plugin (Claude Code): `claude plugin install record-keeping@claude-skills` after adding
the marketplace (see the repository README). As a plain skill: copy
`plugins/record-keeping/skills/record-keeping` into `~/.claude/skills/`, or upload the
`record-keeping-<version>-skill.zip` from the Releases page to claude.ai.

`checkpoint` uses provenance-log when the project has a `provenance/` folder; it finds the CLI
via `$PROVENANCE_PY`, the sibling plugin folder, or the Claude Code plugin cache. Without
provenance-log everything else works.

## Tests

```bash
python3 plugins/record-keeping/tests/test_records.py -v
```
