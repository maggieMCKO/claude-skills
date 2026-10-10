# Changelog

Follows [Semantic Versioning](https://semver.org). Versions below 1.0.0 signal
that the command-line interface may still change.

## 0.3.0 - 2026-10-10

Fixes found while using the tool on a multi-day RNA-seq analysis. Each has a regression test
that fails on 0.2.1 (23 tests, 69 assertions).

### Fixed
- **Duplicate file entries.** Paths were stored as typed, so `scripts/a.sh` and
  `/abs/project/scripts/a.sh` were two unrelated entries; re-recording a script under one form
  left the other reporting `CHANGED` forever. Files inside the project are now keyed by their
  path relative to the project root (the directory holding `provenance/`), and other files by
  absolute real path (symlinks resolved).
- **False drift after moving a project.** With project-relative keys, moving the whole project
  needs no rewrite and `verify` stays clean.
- **Lost script versions.** Only the latest checksum was kept per file, so an earlier step could
  not say which version of a since-edited script it ran, and the old text was gone. Each step now
  stores its own `hashes`, and every recorded script is snapshotted to
  `provenance/scripts/<sha256-prefix>-<name>` (2 MB limit, `PROVENANCE_SNAPSHOT_MAX`).
- **Unrecorded edits.** The plugin hook now also fires on `Edit|Write|MultiEdit|NotebookEdit`;
  when the agent changes a file the manifest already tracks, the new version is logged as its own
  step. Untracked files and no-op writes are ignored. Shell edits (`sed -i`, …) still need an
  explicit `step`; `SKILL.md` now says so.
- **Uncorrectable mistakes.** A wrong entry could never be removed (steps are append-only).
- **`finalize` misused for interim reports**, stamping unfinished runs as finished.

### Added
- `render`: write `PROVENANCE.md` without marking the run finished.
- `supersede --step N --reason ... [--retire FILE]`: mark a step corrected and stop verifying a
  stale entry, which moves to `retired_files` with its reason and appears in the report.
- `migrate [--from OLD --to NEW]`: upgrade a `provenance-log/1` manifest (merging keys that named
  one file two ways; the most recently seen entry wins) and optionally rewrite a moved path prefix.
  Command strings are left as run.
- Per-step git state (`commit`, `dirty`) when the project is a git repository; previously only at
  `init`, so a repository created later was never recorded.
- Report: per-step checksums, git commit, superseded markers, snapshot column, retired entries.
- `kernel.py`: `prov_render`, `prov_supersede`, `prov_migrate`.
- `SKILL.md`: "Keeping the record current" rules.

### Changed
- Manifest schema `provenance-log/2`. `/1` manifests remain readable and verifiable as before;
  `step` and `verify` print a hint to run `migrate`.
- `install_hook.py` (copied installs) adds a second `PostToolUse` group for the edit tools, kept
  separate from the Bash group so other tools' Bash hooks are not widened; re-running it upgrades
  a 0.2.x install. `--remove` removes both.

## 0.2.1 - 2026-09-27

### Changed
- Moved into the `maggieMCKO/claude-skills` collection (the repository formerly named
  `provenance-log`, which GitHub now redirects). The plugin lives in
  `plugins/provenance-log/`, and the marketplace is now named `claude-skills`.
- New install command:
  `claude plugin marketplace add maggieMCKO/claude-skills && claude plugin install provenance-log@claude-skills`.
  Anyone who installed 0.2.0 as `provenance-log@provenance-log` should uninstall it and
  reinstall from the new marketplace.
- No change to the skill, script or hook behaviour.

## 0.2.0 - 2026-09-27

Packaged as a Claude Code plugin, so the skill and its hook install in one command.

### Added
- `.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json`: the repository is
  now its own plugin marketplace. Install with
  `claude plugin marketplace add maggieMCKO/provenance-log && claude plugin install provenance-log@provenance-log`.
- `hooks/hooks.json`: the `PostToolUse` Bash hook ships with the plugin, referencing the
  script through `${CLAUDE_PLUGIN_ROOT}`; no settings file to edit.
- `PROVENANCE_HOOK=0` (also `off`/`false`/`no`) disables automatic capture while keeping
  the skill, since a plugin hook is on by default.
- Regression test for the opt-out (15 tests, 44 assertions).

### Changed
- `install_hook.py` is now only needed for copied (non-plugin) installs. Users upgrading
  from 0.1.x to the plugin should run `install_hook.py --remove --apply` first.

### Unchanged
- Repository layout: the root is still the skill folder, so copying it into
  `~/.claude/skills/` or `~/.codex/skills/` works as before.

## 0.1.0 - 2026-09-26

First release.

### Added
- `scripts/provenance.py`: stdlib-only CLI with `init`, `env`, `step`, `hook`,
  `finalize` and `verify` subcommands. Writes `provenance/manifest.json` and a
  human-readable `PROVENANCE.md`.
- Package versions captured via `importlib.metadata` rather than `pip freeze`,
  which reports conda-installed packages as `name @ file:///...` with the
  version stripped.
- Per-tool version probes that distinguish three states: absent,
  present-but-unversionable, and versioned.
- `--deviation` flag, surfaced as its own section in the report.
- `verify`: re-checksums every tracked file and exits non-zero on drift.
- Best-effort redaction of named secrets and known provider token shapes from
  recorded command strings.
- `install_hook.py`: idempotent merge of a `PostToolUse` hook into an agent
  settings file, with timestamped backup and JSON validation.
- `kernel.py`: optional in-kernel helpers for runtimes that execute sidecars.
- `reference/CHECKLIST.md`: three-axis reproducibility checklist.
- Duplicate-step suppression: a command identical to the previous step within
  2 seconds is dropped, so a hook installed both globally and per project does
  not double-count. Window configurable via `PROVENANCE_DEDUPE_SECONDS`.
- `install_hook.py --project` warns when the global hook is already installed.
- `tests/test_provenance.py`: 14 regression tests, 41 assertions, stdlib only,
  covering both `scripts/provenance.py` and `install_hook.py`.

### Known limitations
- The agent hook settings schema is not verified against a live installation.
  Compare against the agent's own hooks documentation before relying on it.
- Secret redaction is pattern-based and is not a guarantee. Review a manifest
  before committing it.
- `step` and `verify` resolve `provenance/` relative to the current directory
  and do not search upwards; run them from the directory used for `init`.
