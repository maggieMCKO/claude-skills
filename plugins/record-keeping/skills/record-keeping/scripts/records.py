#!/usr/bin/env python3
"""Human-side record keeping for a computational project: README, decision log, git, archive.

Stdlib only, Python 3.8+. Complements provenance-log (which records *what ran*); this
records *what was decided and why*, keeps a text-only git history, and gets the project
off scratch storage before it expires.

    records.py init --title "..." [--expires 2026-10-31] [--archive-to /perm/path]
    records.py track samples.tsv refs/queries.faa      # whitelist text files in .gitignore
    records.py decide --what "..." --why "..." --by user [--supersedes D003]
    records.py checkpoint -m "Step 4: alignment done"  # provenance render + git commit
    records.py status                                  # expiry, uncommitted, OPEN, decisions
    records.py archive --to /perm/path --include results [--dry-run]

Every command takes --root (default: the current directory).
"""
import argparse
import datetime as dt
import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys

CONFIG = ".records.json"
DECISIONS = "DECISIONS.md"
HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, os.pardir, "assets")
BY_CHOICES = ("user", "user-confirmed", "claude", "agreed", "external")
WARN_DAYS = 14


# ---------------------------------------------------------------- helpers
def today():
    return dt.date.today().isoformat()


def git(root, *args, check=True):
    r = subprocess.run(["git", "-C", root] + list(args), capture_output=True, text=True)
    if check and r.returncode != 0:
        sys.exit("git %s failed: %s" % (" ".join(args), r.stderr.strip()))
    return r


def is_repo(root):
    return git(root, "rev-parse", "--is-inside-work-tree", check=False).returncode == 0


def load_config(root):
    p = os.path.join(root, CONFIG)
    if os.path.exists(p):
        with open(p) as fh:
            return json.load(fh)
    return {}


def save_config(root, cfg):
    with open(os.path.join(root, CONFIG), "w") as fh:
        json.dump(cfg, fh, indent=2, sort_keys=True)
        fh.write("\n")


def template(name, **subs):
    with open(os.path.join(ASSETS, name)) as fh:
        text = fh.read()
    for k, v in subs.items():
        text = text.replace("{{%s}}" % k, v)
    return text


def write_if_absent(path, text):
    if os.path.exists(path):
        print("kept existing %s" % os.path.basename(path))
        return False
    with open(path, "w") as fh:
        fh.write(text)
    print("wrote %s" % os.path.basename(path))
    return True


def find_provenance_cli():
    """provenance-log's CLI: $PROVENANCE_PY, the sibling plugin, or an installed copy."""
    env = os.environ.get("PROVENANCE_PY")
    if env and os.path.exists(env):
        return env
    home = os.path.expanduser("~")
    cands = [os.path.join(HERE, *([os.pardir] * 4),
                          "provenance-log", "skills", "provenance-log", "scripts", "provenance.py")]
    cached = glob.glob(os.path.join(home, ".claude", "plugins", "cache", "*", "provenance-log", "*",
                                    "skills", "provenance-log", "scripts", "provenance.py"))

    def vkey(p):
        v = p.split(os.sep)[-5]
        return [int(x) if x.isdigit() else 0 for x in re.split(r"[.-]", v)]

    cands += sorted(cached, key=vkey, reverse=True)
    cands += [os.path.join(home, ".claude", "skills", "provenance-log", "scripts", "provenance.py")]
    return next((os.path.abspath(c) for c in cands if os.path.exists(c)), None)


# ---------------------------------------------------------------- .gitignore whitelist
def whitelist_lines(relpath):
    """Lines that un-ignore one path under a '/*' whitelist .gitignore.

    Git cannot re-include a file whose parent directory is excluded, so every parent is
    re-included and its other contents excluded again: a/b/c.tsv ->
    !/a/  /a/*  !/a/b/  /a/b/*  !/a/b/c.tsv
    A trailing slash whitelists a whole directory.
    """
    is_dir = relpath.endswith("/")
    parts = relpath.strip("/").split("/")
    lines, prefix = [], ""
    for p in parts[:-1]:
        prefix += "/" + p
        lines += ["!%s/" % prefix, "%s/*" % prefix]
    last = prefix + "/" + parts[-1]
    lines.append("!%s/" % last if is_dir else "!%s" % last)
    return lines


def add_to_gitignore(root, paths):
    gi = os.path.join(root, ".gitignore")
    existing = open(gi).read().splitlines() if os.path.exists(gi) else ["/*", "!/.gitignore"]
    added = []
    for path in paths:
        rel = os.path.relpath(os.path.abspath(path), root)
        if rel.startswith(".."):
            sys.exit("%s is outside the project %s" % (path, root))
        if os.path.isdir(os.path.join(root, rel)) and not rel.endswith("/"):
            rel += "/"
        for line in whitelist_lines(rel):
            if line not in existing:
                existing.append(line)
                added.append(line)
    with open(gi, "w") as fh:
        fh.write("\n".join(existing) + "\n")
    return added


# ---------------------------------------------------------------- commands
def cmd_init(a):
    root = a.root
    os.makedirs(root, exist_ok=True)
    for d in ("scripts", "logs"):
        os.makedirs(os.path.join(root, d), exist_ok=True)
    cfg = load_config(root)
    cfg.setdefault("title", a.title)
    cfg.setdefault("created", today())
    if a.expires:
        dt.date.fromisoformat(a.expires)
        cfg["expires"] = a.expires
    if a.archive_to:
        cfg["archive_to"] = a.archive_to
    save_config(root, cfg)

    expiry = ("Storage expires **%s**: archive before then (`records.py archive`)."
              % cfg["expires"]) if cfg.get("expires") else "Storage expiry: none recorded."
    write_if_absent(os.path.join(root, "README.md"),
                    template("README.template.md", TITLE=cfg["title"], DATE=today(), EXPIRY=expiry))
    write_if_absent(os.path.join(root, DECISIONS), template("DECISIONS.template.md"))
    write_if_absent(os.path.join(root, ".gitignore"), template("gitignore.template"))
    add_to_gitignore(root, [os.path.join(root, p) for p in
                            ("README.md", DECISIONS, CONFIG, "scripts/")])
    if os.path.isdir(os.path.join(root, "provenance")):
        add_to_gitignore(root, [os.path.join(root, "provenance/")])

    if a.no_git:
        return
    if not is_repo(root):
        git(root, "init", "-q")
        print("git init")
    for key, val in (("user.name", a.git_name), ("user.email", a.git_email)):
        if val:
            git(root, "config", "--local", key, val)
    if not git(root, "config", "user.name", check=False).stdout.strip():
        print("note: no git user.name; set one with --git-name (stored in this repo only)")
    git(root, "add", "-A")
    if git(root, "diff", "--cached", "--quiet", check=False).returncode:
        git(root, "commit", "-q", "-m", "Record keeping: initialise project records")
        print("committed %s" % git(root, "rev-parse", "--short", "HEAD").stdout.strip())


def cmd_track(a):
    added = add_to_gitignore(a.root, a.paths)
    print("\n".join(added) if added else "already tracked")
    if is_repo(a.root):
        big = []
        for p in a.paths:
            for f in ([p] if os.path.isfile(p) else
                      [os.path.join(d, n) for d, _, ns in os.walk(p) for n in ns]):
                if os.path.getsize(f) > a.max_mb * 1e6:
                    big.append(f)
        if big:
            print("WARNING: larger than %g MB, keep data out of git: %s" % (a.max_mb, ", ".join(big)))


def read_decisions(root):
    p = os.path.join(root, DECISIONS)
    return open(p).read() if os.path.exists(p) else template("DECISIONS.template.md")


def cmd_decide(a):
    text = read_decisions(a.root)
    ids = [int(x) for x in re.findall(r"^## D(\d+)", text, re.M)]
    new = "D%03d" % (max(ids) + 1 if ids else 1)
    if a.supersedes:
        head = re.search(r"^## %s\b.*$" % re.escape(a.supersedes), text, re.M)
        if not head:
            sys.exit("no decision %s in %s" % (a.supersedes, DECISIONS))
        if "superseded by" not in head.group(0):
            text = text.replace(head.group(0),
                                head.group(0) + " (superseded by %s)" % new, 1)
    by = {"user": "user", "user-confirmed": "user (confirmed %s)" % (a.date or today()),
          "claude": "Claude (not yet confirmed by the user)", "agreed": "user and Claude",
          "external": "external"}[a.by]
    if a.who:
        by += ": %s" % a.who
    entry = ["## %s %s: %s" % (new, a.date or today(), a.what), "",
             "- **Why:** %s" % a.why, "- **Decided by:** %s" % by]
    if a.alternatives:
        entry.append("- **Alternatives rejected:** %s" % a.alternatives)
    if a.evidence:
        entry.append("- **Evidence:** %s" % a.evidence)
    if a.supersedes:
        entry.append("- **Supersedes:** %s" % a.supersedes)
    with open(os.path.join(a.root, DECISIONS), "w") as fh:
        fh.write(text.rstrip("\n") + "\n\n" + "\n".join(entry) + "\n")
    print(new)


def changed_record_files(root):
    out = []
    for f in ("README.md", DECISIONS):
        if not os.path.exists(os.path.join(root, f)):
            continue
        r = git(root, "status", "--porcelain", "--", f, check=False).stdout.strip()
        if r:
            out.append(f)
    return out


def already_recorded(prov_dir, key, path):
    """True if the manifest's latest checksum for this file matches its current content."""
    try:
        with open(os.path.join(prov_dir, "manifest.json")) as fh:
            info = json.load(fh).get("files", {}).get(key) or {}
    except (OSError, ValueError):
        return False
    return bool(info.get("sha256")) and not info.get("partial_hash") and info["sha256"] == sha256(path)


def cmd_checkpoint(a):
    root = a.root
    if not is_repo(root):
        sys.exit("%s is not a git repository; run init first" % root)
    prov_dir = os.path.join(root, "provenance")
    if os.path.isdir(prov_dir) and not a.no_provenance:
        cli = find_provenance_cli()
        if cli is None:
            print("WARNING: provenance/ exists but provenance.py not found; set PROVENANCE_PY")
        else:
            base = [sys.executable, cli, "--dir", prov_dir]
            recs = changed_record_files(root)
            # The provenance-log hook already logs agent edits to tracked files; a
            # second step for the same content is noise, so skip what is recorded.
            done = [f for f in recs if already_recorded(prov_dir, f, os.path.join(root, f))]
            if done:
                print("already in provenance: %s" % ", ".join(done))
            recs = [f for f in recs if f not in done]
            if recs:
                cmd = base + ["step", "--cmd", "records: %s" % a.message,
                              "--note", "README/decision-log update recorded by records.py checkpoint"]
                for f in recs:
                    cmd += ["--out", os.path.join(root, f)]
                r = subprocess.run(cmd, capture_output=True, text=True, cwd=root)
                print(("provenance step: %s" % ", ".join(recs)) if r.returncode == 0
                      else "WARNING: provenance step failed: %s" % r.stderr.strip())
            r = subprocess.run(base + ["render"], capture_output=True, text=True, cwd=root)
            if r.returncode:
                print("WARNING: provenance render failed: %s" % r.stderr.strip())
    git(root, "add", "-A")
    if not git(root, "diff", "--cached", "--quiet", check=False).returncode:
        print("nothing to commit")
        return
    files = git(root, "diff", "--cached", "--name-only").stdout.split()
    git(root, "commit", "-q", "-m", a.message)
    print("committed %s (%d files)" % (git(root, "rev-parse", "--short", "HEAD").stdout.strip(),
                                       len(files)))


def open_items(root):
    p = os.path.join(root, "README.md")
    if not os.path.exists(p):
        return []
    m = re.search(r"^## OPEN\s*$(.*?)(?=^## |\Z)", open(p).read(), re.M | re.S)
    return [l.strip()[2:] for l in m.group(1).splitlines() if l.startswith("- ")] if m else []


def days_left(cfg):
    if not cfg.get("expires"):
        return None
    return (dt.date.fromisoformat(cfg["expires"]) - dt.date.today()).days


def cmd_status(a):
    root = a.root
    cfg = load_config(root)
    print("project: %s" % cfg.get("title", os.path.basename(os.path.abspath(root))))
    left = days_left(cfg)
    if left is not None:
        flag = "  <-- ARCHIVE NOW" if left <= WARN_DAYS else ""
        print("expires: %s (%d days left)%s" % (cfg["expires"], left, flag))
        arch = cfg.get("archived")
        print("archived: %s" % (("%s -> %s" % (arch["date"], arch["to"])) if arch else "never"))
    if is_repo(root):
        dirty = git(root, "status", "--porcelain").stdout.splitlines()
        print("uncommitted: %d file(s)%s" % (len(dirty), "" if not dirty else
                                              " -> records.py checkpoint -m ..."))
        for l in dirty[:10]:
            print("  " + l)
        last = git(root, "log", "-1", "--format=%h %cs %s", check=False).stdout.strip()
        print("last commit: %s" % (last or "none"))
    else:
        print("git: not a repository")
    items = open_items(root)
    print("OPEN items in README: %d" % len(items))
    for it in items:
        print("  - " + (it if len(it) < 100 else it[:97] + "..."))
    text = read_decisions(root)
    entries = re.split(r"^(?=## D\d+)", text, flags=re.M)[1:]
    heads = [e.splitlines()[0][3:] for e in entries]
    unconfirmed = [h.split()[0] for h, e in zip(heads, entries)
                   if "Claude (not yet" in e and "superseded by" not in h]
    print("decisions: %d (%d awaiting user confirmation%s)" % (
        len(heads), len(unconfirmed), ": " + ", ".join(unconfirmed) if unconfirmed else ""))
    for h in heads[-a.last:]:
        print("  " + h)


def sha256(path, bufsize=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(bufsize), b""):
            h.update(chunk)
    return h.hexdigest()


def archive_files(root, includes):
    files = set()
    if is_repo(root):
        files.update(git(root, "ls-files").stdout.splitlines())
    for inc in includes:
        p = os.path.join(root, inc)
        if os.path.isfile(p):
            files.add(os.path.relpath(p, root))
        elif os.path.isdir(p):
            for d, _, ns in os.walk(p):
                files.update(os.path.relpath(os.path.join(d, n), root) for n in ns)
        else:
            sys.exit("--include %s does not exist" % inc)
    return sorted(f for f in files if not f.startswith(".git/"))


def cmd_archive(a):
    root = os.path.abspath(a.root)
    cfg = load_config(root)
    dest = a.to or cfg.get("archive_to")
    if not dest:
        sys.exit("no destination: pass --to or init --archive-to")
    dest = os.path.abspath(dest)
    if dest == root or dest.startswith(root + os.sep):
        sys.exit("destination is inside the project")
    files = archive_files(root, a.include)
    total = sum(os.path.getsize(os.path.join(root, f)) for f in files)
    print("%d files, %.2f GB -> %s" % (len(files), total / 1e9, dest))
    if a.dry_run:
        for f in files[:50]:
            print("  " + f)
        if len(files) > 50:
            print("  ... %d more" % (len(files) - 50))
        return
    rows, bad = [], []
    for f in files:
        src, dst = os.path.join(root, f), os.path.join(dest, f)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        st = os.stat(src)
        if not (os.path.exists(dst) and os.path.getsize(dst) == st.st_size
                and int(os.path.getmtime(dst)) == int(st.st_mtime)):
            shutil.copy2(src, dst)
        if a.verify == "sha256":
            s, d = sha256(src), sha256(dst)
            if s != d:
                bad.append(f)
            rows.append("%s\t%d\t%s" % (f, st.st_size, s))
        else:
            if os.path.getsize(dst) != st.st_size:
                bad.append(f)
            rows.append("%s\t%d\t-" % (f, st.st_size))
    with open(os.path.join(dest, "ARCHIVE_MANIFEST.tsv"), "w") as fh:
        fh.write("# archived from %s on %s; verify=%s\npath\tbytes\tsha256\n"
                 % (root, today(), a.verify))
        fh.write("\n".join(rows) + "\n")
    if bad:
        sys.exit("VERIFY FAILED for %d file(s): %s" % (len(bad), ", ".join(bad[:10])))
    cfg["archived"] = {"date": today(), "to": dest, "files": len(files), "bytes": total,
                       "verify": a.verify}
    save_config(root, cfg)
    print("archived and verified (%s); manifest: %s"
          % (a.verify, os.path.join(dest, "ARCHIVE_MANIFEST.tsv")))


# ---------------------------------------------------------------- CLI
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--root", default=".", help="project directory (default: .)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", help="create README, decision log, whitelist .gitignore, git repo")
    p.add_argument("--title", required=True)
    p.add_argument("--expires", help="storage expiry date YYYY-MM-DD")
    p.add_argument("--archive-to", help="permanent storage destination")
    p.add_argument("--git-name", help="git user.name for this repository only")
    p.add_argument("--git-email", help="git user.email for this repository only")
    p.add_argument("--no-git", action="store_true")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("track", help="whitelist text files/dirs in .gitignore")
    p.add_argument("paths", nargs="+")
    p.add_argument("--max-mb", type=float, default=5.0, help="warn above this size")
    p.set_defaults(func=cmd_track)

    p = sub.add_parser("decide", help="append a decision to DECISIONS.md; prints its id")
    p.add_argument("--what", required=True)
    p.add_argument("--why", required=True)
    p.add_argument("--by", required=True, choices=BY_CHOICES)
    p.add_argument("--who", help="name/role, e.g. 'collaborator J.'")
    p.add_argument("--alternatives")
    p.add_argument("--evidence", help="file, command output or message supporting it")
    p.add_argument("--supersedes", help="earlier decision id, e.g. D003")
    p.add_argument("--date", help="YYYY-MM-DD (default today)")
    p.set_defaults(func=cmd_decide)

    p = sub.add_parser("checkpoint", help="provenance step for README/decisions + render + commit")
    p.add_argument("-m", "--message", required=True)
    p.add_argument("--no-provenance", action="store_true")
    p.set_defaults(func=cmd_checkpoint)

    p = sub.add_parser("status", help="expiry, uncommitted files, OPEN items, recent decisions")
    p.add_argument("--last", type=int, default=5)
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("archive", help="copy tracked files + --include paths, verify, write manifest")
    p.add_argument("--to")
    p.add_argument("--include", action="append", default=[],
                   help="results/data path to archive in addition to git-tracked files")
    p.add_argument("--verify", choices=("sha256", "size"), default="sha256")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_archive)

    a = ap.parse_args(argv)
    a.root = os.path.abspath(a.root)
    a.func(a)


if __name__ == "__main__":
    main()
