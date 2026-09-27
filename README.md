# provenance-log

An [Agent Skill](https://code.claude.com/docs/en/skills) that records what a computational
analysis actually did — every step, every software version, every script, and a checksum for
every input and output — while the work happens rather than afterwards.

Built for scientific analyses where the result will be reported: bioinformatics pipelines,
statistical analyses, ML experiments, simulation runs. It is deliberately not a general-purpose
activity logger.

## Why

Documentation written at the end is reconstruction. Reconstruction is where the errors live:
a version misremembered, a threshold that changed halfway through, a figure regenerated from
an input that has since been overwritten. This skill makes the record a by-product of running
the analysis, so it does not depend on anyone remembering.

It is also designed for the case where an **LLM agent** is doing the analysis. That shifts the
dominant failure mode. A fluent agent produces an unsupported sentence at the same cost as a
supported one, so "every number traces to a saved artifact" stops being a formality and becomes
the thing most worth checking. `reference/CHECKLIST.md` addresses this directly.

## Install

Requires Python 3.8+ (`python3` on your PATH). No other dependencies.

### Claude Code (recommended): as a plugin

From a shell:

```bash
claude plugin marketplace add maggieMCKO/provenance-log && claude plugin install provenance-log@provenance-log
```

or inside Claude Code:

```
/plugin marketplace add maggieMCKO/provenance-log
/plugin install provenance-log@provenance-log
```

This installs the skill **and** the automatic-capture hook in one step, with no settings file
to edit. Restart Claude Code (or run `/reload-plugins`) afterwards. Update with
`claude plugin update provenance-log@provenance-log`; remove with
`claude plugin uninstall provenance-log@provenance-log`.

### Other agents, or a pinned copy: copy the folder

```bash
git clone https://github.com/maggieMCKO/provenance-log.git
cp -R provenance-log ~/.claude/skills/     # or ~/.codex/skills/ for Codex CLI
```

| Agent | Personal (all projects) | Project-local |
|---|---|---|
| Claude Code | `~/.claude/skills/` | `<repo>/.claude/skills/` |
| Codex CLI | `~/.codex/skills/` | — |

`SKILL.md` follows the open Agent Skills format, so the same folder works in any agent that
reads it. Recent Claude Code versions also load a folder under `~/.claude/skills/` that carries
a `.claude-plugin/` manifest as a plugin, hook included.

**Personal or project?** Personal (the plugin, or `~/.claude/skills/`) is the right default: it
is a general tool you want in every analysis project, and it costs nothing when idle because
the hook stays silent unless a manifest exists. Add a project-local copy when a specific repo
should pin its own version — for a paper's repository, so the tooling travels with the code
and reviewers get the same behaviour you had.

## Use

```bash
P=~/.claude/skills/provenance-log/scripts/provenance.py

python3 $P init --title "Variant calling, cohort A"
python3 $P env --probe bwa --probe samtools --probe bcftools
python3 $P step --cmd "bwa mem ref.fa reads.fq.gz > aligned.sam" \
                --in reads.fq.gz --out aligned.sam --script scripts/align.sh
python3 $P finalize        # writes provenance/PROVENANCE.md
python3 $P verify          # re-checksums; exit 1 if anything drifted
```

`init` captures platform, interpreter, git commit and dirty-tree state. `env` captures every
installed package with a real version — via `importlib.metadata`, not `pip freeze`, because
conda-installed packages appear in `pip freeze` as `name @ file:///...` with the version
stripped — plus a version probe for each external binary you name.

`verify` is the part that earns its keep. Run it immediately before quoting numbers into a
manuscript: it catches a result reported from a file that was later overwritten.

Use `--deviation` whenever you depart from the intended method. Deviations get their own
section in the report, which is exactly what a reader needs and what is otherwise forgotten.

## Automatic capture

Claude Code supports [hooks](https://code.claude.com/docs/en/hooks-guide). A `PostToolUse`
hook on `Bash` appends every command the agent runs to the manifest with no cooperation from
the agent — capture that does not depend on the agent choosing to log.

**Plugin installs get this automatically** (`hooks/hooks.json`). It stays silent in any
directory without a `provenance/manifest.json`, so it has no effect on projects you have not
initialised, and it adds nothing to the model's context. To keep the skill but switch
automatic capture off, set `PROVENANCE_HOOK=0` in your environment.

For a copied (non-plugin) install, `install_hook.py` merges the same hook into a settings file:

```bash
python3 ~/.claude/skills/provenance-log/install_hook.py            # dry run
python3 ~/.claude/skills/provenance-log/install_hook.py --apply    # write it
python3 ~/.claude/skills/provenance-log/install_hook.py --remove --apply   # undo
```

Restart the agent afterwards. `--project` writes `./.claude/settings.json` instead of the
global config and points the hook at the project's own copy of the skill. The installer backs
up the existing settings file with a timestamp, preserves every other setting and every other
hook, appends rather than replaces if you already have a `PostToolUse` Bash hook, is
idempotent, and refuses to modify a file that is not valid JSON.

**Upgrading from 0.1.x to the plugin?** Remove the settings-file hook first
(`install_hook.py --remove --apply`), otherwise both fire. Nothing is double-counted either
way — `provenance.py` drops a step whose command is identical to the previous one within
2 seconds (`PROVENANCE_DEDUPE_SECONDS` to change) — but you only need one.

The hook is a floor, not a replacement for explicit `step` calls. It sees the command string
but cannot know which file was an input and which a deliverable, nor that a substitution was a
deviation. Use the hook so nothing is missed, and explicit steps so the record is
interpretable. It skips its own bookkeeping calls and bare navigation commands (`ls`, `pwd`,
`cd`, …); set `PROVENANCE_LOG_ALL=1` to record everything.

## Privacy — read before committing a manifest

**The manifest records whole command lines.** `provenance.py` redacts named secret assignments
(`API_KEY=…`, `--token …`, `Authorization: Bearer …`) and unambiguous provider token shapes
(`ghp_…`, `sk-…`, `AKIA…`). That is best-effort pattern matching, **not a guarantee**. A
credential in an unusual position will survive it.

Treat a manifest from a session that handled credentials as sensitive, and review before
committing. Note also that `manifest.json` records absolute paths and therefore your username,
and `PROVENANCE.md` embeds the full package list — both are fine inside a group and worth a
glance before a public push.

## Context cost

The skill is cheap to have installed: only the `description` frontmatter is always in context,
and the body loads when it triggers. The heavy logic lives in scripts, which run rather than
being read.

The one real cost is the **output**. With the hook enabled, `PROVENANCE.md` and `manifest.json`
accumulate, and having an agent read one in full to "check the provenance" can pull in tens of
thousands of tokens. Query them instead — `verify` for integrity, `grep` for a section, a
one-line `json.load` for a count. `SKILL.md` tells the agent this explicitly.

## `kernel.py`

Some runtimes (Claude Science) execute a `kernel.py` sidecar when a skill loads, which defines
`prov_init`, `prov_env`, `prov_step`, `prov_finalize` and `prov_verify` as in-kernel Python
functions. Claude Code and Codex CLI do not — they call the CLI instead, which is the primary
interface. **`kernel.py` is an optional convenience; nothing breaks without it.**

## Where the manifest is found

The **hook** resolves the agent's working directory and then walks *up* the tree looking for
a `provenance/` folder. That is what lets logging continue after the agent `cd`s into a
subdirectory — but it has a consequence worth knowing: **a `provenance/` folder high up in
your tree will capture commands from every project beneath it.** Do not run `init` in a home
directory or a shared parent such as a synced cloud folder; run it in the specific analysis
directory.

`step` and `verify`, by contrast, do **not** walk up — they resolve `provenance/` relative to
the current directory. Run them from the same directory you ran `init` in, or pass `--dir`.
This fails loudly with `no manifest at …` rather than silently doing nothing, so nothing is
lost either way.

## Verifying the install

```bash
mkdir -p /tmp/provcheck && cd /tmp/provcheck
P=~/.claude/skills/provenance-log/scripts/provenance.py
python3 $P init --title "install check"
python3 $P env --probe git
```

You should see a package count and a real version string for git. Then, with the agent running
in that directory, ask it to run any shell command and check that the hook fired:

```bash
python3 -c "import json;print(len(json.load(open('provenance/manifest.json'))['steps']),'steps logged')"
```

A count above zero means the hook is live.

## If the hook does not fire

1. **Restart the agent.** Settings are read at startup.
2. **Is there a manifest?** The hook is deliberately silent without one — run `init` first.
3. **Is the path right?** Run the hook command by hand; it should exit 0 and print nothing:
   `echo '{"tool_input":{"command":"test"}}' | python3 "$HOME/.claude/skills/provenance-log/scripts/provenance.py" hook`
4. **Is `python3` on the hook's PATH?** Hooks may run with a reduced environment. If so, put
   an absolute interpreter path in `settings.json` (`which python3`).
5. **Has the schema changed?** Compare against the hooks documentation linked above, or use
   the agent's interactive `/hooks` command if it has one.

## Tests

```bash
python3 tests/test_provenance.py -v
```

15 tests, stdlib only. Each corresponds to a defect that was observed rather than imagined:
capped-hash false positives, lost steps under concurrent hook writes, usage lines recorded as
versions, hooks failing when the agent has changed directory, and secret leakage.

## The reproducibility checklist

`reference/CHECKLIST.md` is for auditing analyses that are already finished. Three axes:

1. **REFORMS** — is the claim valid? (Kapoor et al., *Sci Adv* 2024, [10.1126/sciadv.adk3452](https://doi.org/10.1126/sciadv.adk3452))
2. **Claim provenance** — did a computation actually happen? Not in any published standard, because they all assume a human did the computing.
3. **FAIR** — can anyone else reuse this? ([10.1038/sdata.2016.18](https://doi.org/10.1038/sdata.2016.18); FAIR4RS for software, [10.1038/s41597-022-01710-x](https://doi.org/10.1038/s41597-022-01710-x))

FAIR is not open access — sub-principle A1.2 explicitly allows authentication and
authorisation — so an unpublished or embargoed project has no excuse to skip axis 3. Run it
first: it is the only axis whose failures expire. A missing script can be written later; a
sampling frame nobody recorded is gone.

## Citing

`CITATION.cff` carries machine-readable metadata; GitHub renders a "Cite this
repository" button from it. Current version: **0.2.0**.

For a citable, versioned archive, enable the Zenodo–GitHub integration and cut a
release: Zenodo mints a DOI per release plus a concept DOI that always resolves to
the newest one. Add it to `CITATION.cff` under `identifiers` afterwards.

## Development and AI assistance

This tool was developed with the assistance of Claude (Anthropic), used for code
drafting, review and test design. All design decisions, verification and the final
content are the author's responsibility.

Specifically, and in the spirit of what the tool itself asks of its users: seven
defects were found and fixed before the first release — false `CHANGED` reports on
capped hashes, lost steps under concurrent hook writes, usage lines recorded as
versions, hooks failing after a directory change, credential leakage into the
manifest, a project-scoped install pointing at the personal copy, and duplicate
steps when the hook is installed both globally and per project. Each was reproduced
by a failing test before being fixed, and each has a regression test in
`tests/test_provenance.py` (15 tests, 44 assertions, covering both
`scripts/provenance.py` and `install_hook.py`).

Two of those were found by review rather than by me, and one — the timezone skew
that silently disabled duplicate suppression — was found by the test I wrote for
the fix, which is the argument for writing the test first.

Consistent with the position of the ICMJE, COPE and most journals, an AI assistant
is not credited as an author: it cannot take responsibility for the work, and AI
tools should not be listed as authors or cited as such. Disclosure belongs here and
in a methods or acknowledgements section, not in the copyright notice or the author
list.

If you reuse this code in published work, disclose your own tool use according to
your venue's policy rather than relying on this statement.

## Licence

MIT. See `LICENSE`.
