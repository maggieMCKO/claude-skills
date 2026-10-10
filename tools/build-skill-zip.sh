#!/usr/bin/env bash
# Build an upload-ready Agent Skill zip for one plugin (or all of them).
#
# claude.ai's skill upload rejects plugin metadata ("A skill cannot contain a plugin
# manifest"), so the zip drops what only the Claude Code plugin system uses:
#   .claude-plugin/   plugin manifest
#   hooks/            plugin hooks (no effect outside Claude Code plugins)
#   tests/            development only
# Built from committed files (git archive), so caches and local junk never ship.
#
#   tools/build-skill-zip.sh provenance-log            # -> dist/provenance-log-<version>-skill.zip
#   tools/build-skill-zip.sh                           # every plugin under plugins/
#   REF=v1 OUT=/tmp tools/build-skill-zip.sh provenance-log
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"
REF=${REF:-HEAD}
OUT=${OUT:-dist}
mkdir -p "$OUT"

plugins=("$@")
if [ ${#plugins[@]} -eq 0 ]; then
  mapfile -t plugins < <(git ls-tree --name-only "$REF" plugins/ | xargs -n1 basename)
fi

for name in "${plugins[@]}"; do
  dir=plugins/$name
  git cat-file -e "$REF:$dir/SKILL.md" 2>/dev/null || { echo "skip $name: no SKILL.md at $REF" >&2; continue; }
  version=$(git show "$REF:$dir/.claude-plugin/plugin.json" 2>/dev/null \
            | python3 -c 'import json,sys; print(json.load(sys.stdin)["version"])' 2>/dev/null || echo dev)
  zip="$OUT/$name-$version-skill.zip"
  tmp=$(mktemp -d)
  git archive --format=tar --prefix="$name/" "$REF:$dir" | tar -x -C "$tmp"
  rm -rf "$tmp/$name/.claude-plugin" "$tmp/$name/hooks" "$tmp/$name/tests"
  rm -f "$zip"
  (cd "$tmp" && zip -qr - "$name") > "$zip"
  rm -rf "$tmp"
  echo "$zip"
done
