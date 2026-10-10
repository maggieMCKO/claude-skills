# claude-skills

Claude Code plugins and Agent Skills for reproducible computational research, by
Meng-Ching Ko. Each plugin lives in its own folder under `plugins/`, with its own README,
changelog, tests and citation metadata.

## Install

Add this repository as a plugin marketplace once:

```bash
claude plugin marketplace add maggieMCKO/claude-skills
```

Then install any plugin from it:

```bash
claude plugin install <plugin>@claude-skills
```

Inside Claude Code the same commands are `/plugin marketplace add maggieMCKO/claude-skills`
and `/plugin install <plugin>@claude-skills`. `claude plugin marketplace update claude-skills`
picks up new plugins and versions.

## Plugins

| Plugin | What it does | Version |
|---|---|---|
| [provenance-log](plugins/provenance-log/) | Records every step, software version, script and input/output checksum of a computational analysis while it runs, with an automatic Bash-command hook and a three-axis reproducibility checklist. | 0.3.1 |
| [record-keeping](plugins/record-keeping/) | Keeps a resumable README, a decision log (what, why, whose call, what it replaces), a text-only git history with one commit per step, and verified archiving before scratch storage expires. Pairs with provenance-log. | 0.1.0 |

## claude.ai and Claude Science (skill upload)

claude.ai's skill upload accepts Agent Skills, not plugins, and rejects a folder that contains
`.claude-plugin/`. Each release therefore carries a ready-made **`<plugin>-<version>-skill.zip`**
(no plugin manifest, hooks or tests): download it from the
[Releases](https://github.com/maggieMCKO/claude-skills/releases) page and upload it as a skill.
The automatic-capture hook is a Claude Code plugin feature and is not part of the skill zip.

**Claude Science** can instead *Import from GitHub* (`maggieMCKO/claude-skills`): it picks up
every `plugins/<plugin>/skills/<skill>/SKILL.md`. Imports are pinned to a commit and do not
update automatically, so re-import after a release.

To build one yourself: `tools/build-skill-zip.sh <plugin>` (writes `dist/`).

### Releasing a new version (maintainer)

1. Bump `version` in `plugins/<plugin>/.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`,
   `CITATION.cff` and the table above; add a `CHANGELOG.md` entry; merge to `main`.
2. Publish a GitHub release with tag `<plugin>-v<version>` (e.g. `provenance-log-v0.3.0`).
   The `skill zip` workflow checks the tag against `plugin.json` and attaches the skill zip.
3. Claude Code users: `claude plugin marketplace update claude-skills && claude plugin update <plugin>@claude-skills`.
   claude.ai users: replace the uploaded skill with the new zip.

## Without the plugin system

Every plugin keeps its skill(s) in `plugins/<plugin>/skills/<skill>/`, a plain Agent Skill folder.
Copy one into your agent's skills directory:

```bash
git clone https://github.com/maggieMCKO/claude-skills.git
cp -R claude-skills/plugins/provenance-log/skills/provenance-log ~/.claude/skills/    # or ~/.codex/skills/
```

## Citing

Each plugin carries its own `CITATION.cff` in its folder.

## Licence

MIT unless a plugin folder says otherwise. See `LICENSE`.
