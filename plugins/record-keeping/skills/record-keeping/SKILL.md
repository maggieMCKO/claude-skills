---
name: record-keeping
description: "Keep the human-readable records of a multi-day computational research project: a README that says how to resume, a decision log (what was decided, why, whose call, what it replaces), a text-only git history with one commit per step, and archiving off scratch storage before it expires. Use at the START of any analysis that will span sessions or be reported (bioinformatics pipelines, HPC jobs, statistical analyses), whenever the user makes or confirms a choice about samples, methods or parameters, after each completed pipeline step, and when a workspace or scratch directory has an expiry date. Pairs with provenance-log (which records what ran); this records why. Triggers on: set up the project, keep a record, log this decision, write that down, what did we decide, README, commit this step, where were we, workspace expires, archive results, hand this over. Not for software repositories with their own conventions or one-off shell tasks."
---

# record-keeping

provenance-log answers *what ran*: commands, versions, checksums. It cannot answer *why
this sample was dropped*, *who said the palate samples are the tip*, or *what to do next
on Monday*. Those live in people's heads and in a chat transcript that will be compacted
or lost. This skill puts them in four files that outlive the session:

| File | Answers | Updated |
|---|---|---|
| `README.md` | What is this, where is everything, how do I resume, what is still open | At every checkpoint |
| `DECISIONS.md` | What was decided, why, by whom, when, what it replaced | Whenever a choice is made or confirmed |
| `.git/` (text only) | What changed between steps | One commit per step |
| `.records.json` | Title, storage expiry, archive destination, last archive | By the script |

`scripts/records.py` (stdlib Python 3.8+) does the mechanical parts. Call it with
`--root <project>` or from the project directory. Below, `REC` means
`python3 <this skill>/scripts/records.py --root <project>`.

## At the start

```bash
$REC init --title "Bird RNA-seq: sugar-gene expression" \
          --expires 2026-10-31 --archive-to /permanent/storage/project \
          --git-name "<user's name>" --git-email "<user's email>"
```

Creates (never overwrites) `README.md`, `DECISIONS.md`, a whitelist `.gitignore`,
`scripts/`, `logs/`, and a git repository with a *local* identity; commits. Ask the user
for the expiry date if the project sits on scratch or a time-limited workspace: it is the
one date that, if missed, deletes the work.

If provenance-log is in use, `init` it in the same project root so `provenance/` sits next to
the README, then `$REC track provenance/`.

Then fill the README's *Goal* and *Data and samples* sections from what the user said. Keep
the README in the user's terms; it is for them and their collaborators, not for you.

### Git: text only

The `.gitignore` is a whitelist (`/*` ignores everything; each tracked path is un-ignored).
Data, BAMs, indices, logs never enter git: they are large, they are reproducible from the
scripts, and a repository holding them cannot be copied or pushed. Add each small text file
the analysis depends on as it appears:

```bash
$REC track samples.tsv refs/queries.faa scripts/
```

`track` writes the parent-directory re-include lines git needs for nested paths and warns
about files over 5 MB. Never push, add a remote, or put credentials on a shared machine
unless the user asks: the repository is a local history, and the user decides where it goes.

## Decisions

Record a decision when a choice changes what the analysis does or how a result is read:
which samples are in or out and why, a sample identity or label mapping, a method or
reference choice, a parameter that deviates from default, a workaround for a failure, a
grouping for comparison. Record it at the moment it is made, while the reason is known.

```bash
$REC decide --what "Palate group = PN5_2, PN6_1, PN7_3 (top palate tip); PN7_4 (base) analysed separately" \
            --why "PN7_4 is a different region; mixing it would confound tissue with region" \
            --by user --evidence "user message 2026-10-10"
```

`--by` is whose call it was, and it matters later when someone asks whether a choice was
reviewed:

- `user`: the user decided it.
- `user-confirmed`: you proposed it and the user explicitly agreed (date is stamped).
- `claude`: you chose it and the user has not confirmed it. `status` lists these. Ask the
  user at a natural moment, then record a `user-confirmed` decision with `--supersedes`.
- `agreed`: worked out together. `external`: a collaborator or reviewer (`--who`).

Do not rewrite an old decision. Record a new one with `--supersedes D004`; the old entry
is marked *superseded by D009* and keeps its original reasoning. A decision log that only
shows the current state hides how you got there, which is exactly what a reviewer asks.

Facts you verified (read counts match the SRA record, a file is truncated at the source)
go in as `--evidence` on the decision they support, with the file or command that shows it.

Unresolved questions go under `## OPEN` in the README, one bullet each. When one is
answered, delete the bullet and record the answer as a decision.

## After each step: checkpoint

A step is a unit of work you would describe in one line of a methods section: data
downloaded, index built, all samples aligned, counts table made. After each:

1. If provenance-log is in use, record the step there (command, inputs, outputs, script).
2. Update the README's *How to resume* (status, next step) and *Layout* if new folders
   appeared. Record any decisions made during the step.
3. `$REC checkpoint -m "Align all 192 libraries (HISAT2)"`

`checkpoint` records a provenance step for README/DECISIONS changes (so documentation
edits are themselves in the record; a file whose current content provenance-log already
holds, e.g. logged by its edit hook, is skipped rather than recorded twice), runs `provenance.py render` (an interim report; do not
`finalize` mid-project, it marks the run finished), and commits everything git tracks. It
finds provenance-log via `$PROVENANCE_PY`, the sibling plugin, or the plugin cache.

Commit messages say what the step achieved, not which files changed: `git log --oneline`
should read as the project's lab notebook.

## Before reporting results

Run `$REC status` and provenance-log's `verify`. Report numbers only from files that
verify clean, and say which decisions they depend on (by D-number) when the user will
quote them. If a result rests on a `claude` decision that was never confirmed, say so.

## Resuming

At the start of a new session in an existing project, read the README (*How to resume*
and *OPEN*) and run `$REC status` before doing anything else. Do not reread the full
decision log or provenance; `status` lists the recent decisions and the unconfirmed ones.

## Expiry and archiving

`status` prints days left and flags *ARCHIVE NOW* inside 14 days. Raise it with the user
when it appears, without waiting to be asked; a missed expiry deletes the work. Archive
early and again at the end:

```bash
$REC archive --to /permanent/path --include results/ --include align/ --dry-run
$REC archive --to /permanent/path --include results/ --include align/
```

Copies every git-tracked file plus each `--include`, skips files already copied (same size
and mtime), verifies each by SHA-256 (`--verify size` for very large data when time is
short), writes `ARCHIVE_MANIFEST.tsv` at the destination, and stores the date in
`.records.json`. On HPC, run large archives on the transfer/data node or in a batch job, not
on a login node. Check the site documentation for which node that is before saying so.

Decide with the user what to include: results and the scripts that made them always;
intermediate files (BAMs, indices) only if they are expensive to regenerate.

## Adopting an existing project

`init` keeps every existing file. In a project that already has a README, add the missing
sections (*How to resume*, *OPEN*) by hand, move decisions scattered in the README into
`decide` entries (with their original dates via `--date`), and `track` the text files
already there.
