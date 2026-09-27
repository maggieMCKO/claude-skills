---
name: provenance-log
description: "Capture reproducible provenance for a computational data analysis: every step with its command, every software version, every script, and checksums of inputs and outputs. Writes provenance/manifest.json plus a human-readable PROVENANCE.md. Use for scientific and computational analysis work — bioinformatics pipelines, statistical analyses, ML experiments, simulation runs — at the START of the analysis and before reporting results. Not for general file editing, web development, or routine shell work. Also carries a three-axis reproducibility checklist (REFORMS validity, claim provenance, FAIR stewardship) for auditing finished analyses. Triggers on: make this analysis reproducible, record the pipeline, what versions did we use, provenance, audit trail, METHODS section for this analysis."
---

# provenance-log

Documentation written at the end is reconstruction, and reconstruction is where the errors
live. This skill captures provenance *while the work happens*, mechanically, so the record
does not depend on anyone remembering.

`scripts/provenance.py` is stdlib-only Python 3.8+. It runs in an agent kernel, in a bare
shell, or inside a job script. No dependencies to install.

**Scope.** This is for computational analysis whose results will be reported — a pipeline, a
statistical analysis, an ML experiment, a simulation. Do not start a manifest for ordinary
file editing, code refactoring or web work; it adds noise and buys nothing.

## Start here, not at the end

```bash
python scripts/provenance.py init --title "<what this run is>"
python scripts/provenance.py env --probe samtools --probe bwa --probe bcftools
```

`init` records platform, interpreter, git commit and whether the working tree was dirty.
`env` records every installed package with a real version, plus a version probe for each
external tool you name. Name every binary the pipeline shells out to — an unprobed tool is
an undocumented one.

Then wrap each step:

```bash
python scripts/provenance.py step \
  --cmd "bwa mem ref.fa reads.fq.gz > aligned.sam" \
  --in reads.fq.gz --out aligned.sam --script scripts/align.sh \
  --deviation "bwa used instead of the planned aligner: the planned one mis-reports read counts on this platform"
```

And close the run:

```bash
python scripts/provenance.py finalize   # writes PROVENANCE.md
python scripts/provenance.py verify     # re-checksums everything; exit 1 on drift
```

## Reading the record back

**Do not read `PROVENANCE.md` or `manifest.json` in full to "check the provenance".** With
the hook enabled they accumulate every command plus a full package list, and reading one
wholesale can cost tens of thousands of tokens. Query them instead:

```bash
python scripts/provenance.py verify                      # the integrity question
python -c "import json;m=json.load(open('provenance/manifest.json'));print(len(m['steps']),'steps')"
grep -n 'Deviations' -A20 provenance/PROVENANCE.md       # just the deviations
```

## In an agent kernel

If your runtime executes `kernel.py` sidecars (Claude Science does; plain Claude Code does
not), loading this skill defines the helpers directly:

```python
prov_init("Variant calling, cohort A")
prov_env(probes=["samtools", "bcftools"])
prov_step("bcftools call -mv", inputs=["aligned.bam"], outputs=["calls.vcf"])
prov_finalize()
```

Everywhere else, call `scripts/provenance.py` directly — the CLI is the primary interface and
`kernel.py` is a thin convenience wrapper around it.

## Why `verify` matters

`step` checksums every file it touches. `verify` re-checksums them and exits non-zero if
anything changed since it was recorded. This catches the failure mode that no amount of prose
prevents: a figure or table reported from a file that was later overwritten. Run `verify`
immediately before quoting numbers into a manuscript or report.

If `step` sees a file it recorded before under a different checksum, it flags `CHANGED` at
capture time too, so silent overwrites surface as they happen.

## Recording what you could not record

A field you cannot fill is information. Write it down as unknown rather than omitting it: an
omission looks identical to a value nobody thought to question. Wet-lab and instrument
metadata are the usual casualties — sample counts, batch dates, protocol details — and none
of it is recoverable from the processed data later.

## Auditing finished work

`reference/CHECKLIST.md` carries a three-axis checklist for work that is already done:
REFORMS (is the claim valid?), claim provenance (did a computation actually happen?), and
FAIR (can anyone else reuse this?). Its most useful property is that an LLM analyst fails the
middle axis far more often than the first — fluent prose costs nothing, so an unsupported
sentence reads exactly like a supported one.

Hand the checklist to a *fresh* reviewer that has the artifacts but not the transcript. A
reviewer that read the reasoning tends to accept its premises.

## Installing

See the repository `README.md` for plugin and manual install, the automatic-capture hook
(on by default in the plugin; `PROVENANCE_HOOK=0` turns it off), privacy notes and
troubleshooting.
