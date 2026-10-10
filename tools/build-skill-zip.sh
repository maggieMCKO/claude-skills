#!/usr/bin/env bash
# Build upload-ready Agent Skill zips for claude.ai from plugins/<plugin>/skills/<skill>/.
#
# Each skill folder is self-contained and carries no plugin metadata (claude.ai's skill
# upload rejects .claude-plugin/), so the zip is that folder as committed (git archive:
# caches and local junk never ship). Prints one zip path per skill.
#
#   tools/build-skill-zip.sh provenance-log     # -> dist/provenance-log-<version>-skill.zip
#   tools/build-skill-zip.sh                    # every plugin under plugins/
#   REF=main OUT=/tmp tools/build-skill-zip.sh provenance-log
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"
REF=${REF:-HEAD}
OUT=${OUT:-dist}
mkdir -p "$OUT"

plugins=("$@")
if [ ${#plugins[@]} -eq 0 ]; then
  mapfile -t plugins < <(git ls-tree --name-only "$REF" plugins/ | xargs -n1 basename)
fi

for plugin in "${plugins[@]}"; do
  dir=plugins/$plugin
  version=$(git show "$REF:$dir/.claude-plugin/plugin.json" 2>/dev/null \
            | python3 -c 'import json,sys; print(json.load(sys.stdin)["version"])' 2>/dev/null || echo dev)
  skills=$(git ls-tree --name-only "$REF" "$dir/skills/" 2>/dev/null | xargs -rn1 basename)
  [ -n "$skills" ] || { echo "skip $plugin: no skills/ at $REF" >&2; continue; }
  for skill in $skills; do
    git cat-file -e "$REF:$dir/skills/$skill/SKILL.md" 2>/dev/null \
      || { echo "skip $plugin/$skill: no SKILL.md" >&2; continue; }
    zip="$OUT/$skill-$version-skill.zip"
    rm -f "$zip"
    git archive --format=zip --prefix="$skill/" -o "$zip" "$REF:$dir/skills/$skill"
    echo "$zip"
  done
done
