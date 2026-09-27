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
| [provenance-log](plugins/provenance-log/) | Records every step, software version, script and input/output checksum of a computational analysis while it runs, with an automatic Bash-command hook and a three-axis reproducibility checklist. | 0.2.1 |

## Without the plugin system

Every plugin folder is also a plain Agent Skill folder. Copy one into your agent's skills
directory:

```bash
git clone https://github.com/maggieMCKO/claude-skills.git
cp -R claude-skills/plugins/provenance-log ~/.claude/skills/    # or ~/.codex/skills/
```

## Citing

Each plugin carries its own `CITATION.cff` in its folder.

## Licence

MIT unless a plugin folder says otherwise. See `LICENSE`.
