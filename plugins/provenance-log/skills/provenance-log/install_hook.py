#!/usr/bin/env python3
"""Merge the provenance-log PostToolUse hook into a Claude Code settings.json.

Safe to run repeatedly: it backs up the existing file, preserves every other
setting and every other hook, and does nothing if the hook is already present.

    python3 install_hook.py              # dry run: show what would change
    python3 install_hook.py --apply      # write it
    python3 install_hook.py --apply --project   # .claude/settings.json here
    python3 install_hook.py --remove --apply    # undo

Authoritative schema reference: https://code.claude.com/docs/en/hooks-guide
If that page disagrees with the block written here, the page is correct: the hook
settings schema can change between agent versions. Some versions also provide an
interactive `/hooks` command, which writes the configuration directly and makes
this script unnecessary.
"""
import argparse
import json
import os
import shutil
import sys
import time

EVENT = "PostToolUse"
# Bash: log commands. Edit tools: re-record a tracked file the agent edits (0.3.0).
# Separate groups, so another tool's hook sharing the Bash group is never made
# to fire on edits as well.
MATCHERS = ("Bash", "Edit|Write|MultiEdit|NotebookEdit")
# $HOME / $CLAUDE_PROJECT_DIR rather than ~ : hook commands are not guaranteed to
# go through a shell that performs tilde expansion, but these are expanded by any
# POSIX shell. A project install must point at the project's own copy of the
# skill, not at the personal one -- otherwise --project silently depends on a
# personal install being present too.
COMMAND_PERSONAL = 'python3 "$HOME/.claude/skills/provenance-log/scripts/provenance.py" hook'
COMMAND_PROJECT = ('python3 "${CLAUDE_PROJECT_DIR:-$PWD}/.claude/skills/'
                   'provenance-log/scripts/provenance.py" hook')


def hook_command(project):
    return COMMAND_PROJECT if project else COMMAND_PERSONAL


def settings_path(project, explicit=None):
    if explicit:
        return os.path.abspath(os.path.expanduser(explicit))
    if project:
        return os.path.join(os.getcwd(), ".claude", "settings.json")
    return os.path.expanduser("~/.claude/settings.json")


def load(path):
    if not os.path.exists(path):
        return {}, False
    with open(path) as fh:
        text = fh.read().strip()
    if not text:
        return {}, True
    try:
        return json.loads(text), True
    except json.JSONDecodeError as exc:
        sys.exit("%s is not valid JSON (%s).\nFix or move it before running this."
                 % (path, exc))


def find_entry(cfg, matcher):
    """Locate an existing PostToolUse group for `matcher`, if any."""
    for group in (cfg.get("hooks", {}).get(EVENT) or []):
        if group.get("matcher") == matcher:
            return group
    return None


def has_our_hook(group):
    return any("provenance-log" in (h.get("command") or "")
               for h in (group.get("hooks") or []))


def merge(cfg, command):
    """Add our hook for each matcher, preserving all other settings and hooks.

    Returns the action taken. Re-running is idempotent, and upgrades a 0.2.x
    install (Bash only) by adding the edit-tool group.
    """
    cfg.setdefault("hooks", {}).setdefault(EVENT, [])
    done = []
    for matcher in MATCHERS:
        group = find_entry(cfg, matcher)
        if group is None:
            cfg["hooks"][EVENT].append(
                {"matcher": matcher, "hooks": [{"type": "command", "command": command}]})
            done.append("added a new %s/%s group" % (EVENT, matcher))
        elif not has_our_hook(group):
            group.setdefault("hooks", []).append({"type": "command", "command": command})
            done.append("appended to the existing %s/%s group (%d hook(s) already there)"
                        % (EVENT, matcher, len(group["hooks"]) - 1))
    return "; ".join(done) if done else "already installed"


def unmerge(cfg):
    removed = False
    for matcher in MATCHERS:
        group = find_entry(cfg, matcher)
        if not group or not has_our_hook(group):
            continue
        removed = True
        group["hooks"] = [h for h in group["hooks"]
                          if "provenance-log" not in (h.get("command") or "")]
        if not group["hooks"]:
            cfg["hooks"][EVENT] = [g for g in cfg["hooks"][EVENT] if g is not group]
    if removed and EVENT in cfg.get("hooks", {}) and not cfg["hooks"][EVENT]:
        del cfg["hooks"][EVENT]
    if removed and not cfg.get("hooks"):
        cfg.pop("hooks", None)
    return "removed" if removed else "not present"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    ap.add_argument("--project", action="store_true",
                    help="use ./.claude/settings.json instead of ~/.claude/settings.json")
    ap.add_argument("--remove", action="store_true", help="uninstall the hook")
    ap.add_argument("--path", help="explicit settings.json path (overrides the defaults)")
    a = ap.parse_args()

    path = settings_path(a.project, a.path)
    cfg, existed = load(path)
    before = json.dumps(cfg, indent=2, sort_keys=True)

    action = unmerge(cfg) if a.remove else merge(cfg, hook_command(a.project))
    after = json.dumps(cfg, indent=2, sort_keys=True)

    print("settings file : %s%s" % (path, "" if existed else "  (does not exist yet)"))
    print("action        : %s" % action)
    if before == after:
        print("\nNothing to do.")
        return 0

    other = sorted(k for k in cfg if k != "hooks")
    print("preserved keys: %s" % (", ".join(other) if other else "(none)"))

    # A global and a project hook are different command strings, so the agent
    # runs both and each would append the same step. provenance.py suppresses
    # the duplicate, but the overlap is still worth flagging.
    if a.project and not a.remove:
        global_path = settings_path(project=False)
        gcfg, gexists = load(global_path)
        gbash = find_entry(gcfg, MATCHERS[0]) if gexists else None
        if gbash and has_our_hook(gbash):
            print("\nNOTE: the global hook is already installed at %s." % global_path)
            print("      Both will fire for every command. provenance.py drops the")
            print("      duplicate (identical command within %s s), so logging stays"
                  % "2")
            print("      correct -- but you only need one. Remove the global one with:")
            print("        python3 %s --remove --apply" % os.path.basename(__file__))

    if not a.apply:
        print("\n--- resulting hooks block (dry run; re-run with --apply to write) ---")
        print(json.dumps({"hooks": cfg.get("hooks", {})}, indent=2))
        return 0

    os.makedirs(os.path.dirname(path), exist_ok=True)
    if existed:
        backup = "%s.bak-%s" % (path, time.strftime("%Y%m%dT%H%M%S"))
        shutil.copy2(path, backup)
        print("backup        : %s" % backup)
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(cfg, fh, indent=2)
        fh.write("\n")
    json.load(open(tmp))  # re-parse before committing
    os.replace(tmp, path)
    print("written       : %s" % path)
    if a.remove:
        print("\nHook removed. Restart Claude Code for it to take effect.")
    else:
        print("\nRestart Claude Code, then run `provenance.py init` in a project.\n"
              "The hook stays silent until a manifest exists, so it never interferes\n"
              "with projects you have not initialised.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
