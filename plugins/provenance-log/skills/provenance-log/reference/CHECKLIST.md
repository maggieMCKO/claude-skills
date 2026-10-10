# Three-axis reproducibility checklist

Built on published standards rather than invented. Use for auditing work that is already
done; use `SKILL.md` for capturing work as it happens.

Hand this to a reviewer that has the artifacts but **not** the transcript. A reviewer that
read the author's reasoning tends to accept its premises.

## Axis 1 — REFORMS: is the claim valid?

Kapoor et al., *Sci Adv* 2024, `10.1126/sciadv.adk3452`. 32 items, 8 modules, consensus of
19 researchers; field-agnostic because ML methods fail alike across disciplines.

1. **Study goals** — population the claim is about; why that population; why these methods
2. **Computational reproducibility** — dataset; code version; computing environment; documentation; **a script that reproduces every reported result**
3. **Data quality** — sources; sampling frame; fitness for the task; outcome variable; sample count; missingness; representativeness
4. **Data preprocessing** — excluded data and why; corrupt samples; transformations
5. **Modeling** — model description; why this model class; evaluation method; selection method; hyperparameters; baselines
6. **Data leakage** — train/test separation; duplicates or dependencies between datasets; **feature legitimacy**
7. **Metrics and uncertainty** — metrics used; uncertainty estimates; appropriate statistical tests
8. **Generalizability and limitations** — external validity; explicit boundaries of applicability

Module 6 is the one most often skipped and most often fatal. *Feature legitimacy* covers the
subtle case: marker genes, features or thresholds derived from the very output they are then
used to confirm. That is leakage even with no train/test split anywhere in the design.

Also relevant: **DOME** (`10.1038/s41592-021-01205-4`) for supervised ML in biology, and
**TRIPOD-LLM** (`10.1038/s41591-024-03425-5`) for studies of LLMs in health.

## Axis 2 — Claim provenance: did a computation actually happen?

**Not in any published standard**, because they all assume a human did the computing and is
reporting it. For an LLM analyst this is the dominant failure mode: fluency is free, so an
unsupported sentence costs nothing and reads exactly like a supported one.

1. Every reported number traces to a saved artifact, not to kernel memory or recall
2. No claim asserted without a computation behind it
3. Inputs the analyst invented — marker sets, thresholds, categories — labelled as invented
4. Recommendations postdate the analysis that tests them
5. Method substitutions flagged as deviations
6. Figure and table titles hold for **every** plotted row, not the headline ones
7. The analyst's own model, surface and loaded skills recorded alongside tool versions

Item 7 is the TRIPOD-LLM idea transposed: when an LLM does the analysis, the analyst is part
of the method section.

## Axis 3 — FAIR: can anyone else reuse this?

Wilkinson et al., *Sci Data* 2016, `10.1038/sdata.2016.18`; for code, **FAIR4RS**
(Barker et al. 2022, `10.1038/s41597-022-01710-x`).

**FAIR is not open access.** Sub-principle A1.2 requires only that the access protocol
support authentication and authorisation where necessary. Data can be fully FAIR and fully
closed, so an unpublished or embargoed project has no excuse to skip this axis.

Split the 15 sub-principles by whether they expire:

| When | Items | Why |
|---|---|---|
| **Now — expires** | F2 rich metadata; A2 metadata outliving the data; I1 standard formats; I2 FAIR vocabularies; I3 qualified references; R1 rich attributes; R1.2 provenance; R1.3 community standards | Depend on live files and living memory |
| At deposition — deferrable | F1 persistent identifier; F3 metadata names its data; F4 indexed in a searchable resource; A1/A1.1/A1.2 protocol retrieval | One mechanical submission act, any time |
| Either | R1.1 licence | Only needed when data leaves the group |

Two traps worth naming:

- **A2 — metadata must survive the data.** Lost raw data with surviving metadata is a
  setback; lost data with lost metadata is an unusable orphan. Assume any dataset can go.
- **I2 — the vocabularies must themselves be FAIR.** Genome-annotation identifiers are the
  classic failure: IDs get renamed or retired between releases, cross-release liftover may
  not exist, and cross-species symbol transfer silently fails. An interoperability failure
  here does not merely inconvenience an analysis, it produces wrong answers.

Automated FAIR scoring exists where REFORMS scoring does not — **F-UJI** (FAIRsFAIR) and
**FAIR-EVA** score datasets against the RDA FAIR Data Maturity Model.

## Sequencing

Run axis 3 first on any live project: it is the only axis whose failures expire. Axis 1
and 2 failures can be repaired later — a missing script can be written, circular features
replaced. A lost sampling frame cannot be recovered by any amount of later diligence.
