#!/usr/bin/env python3
"""Tests for records.py. Stdlib only; no pytest required.

    python3 test_records.py            # run all
    python3 test_records.py -v         # show each assertion
"""
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
CLI = os.path.join(HERE, os.pardir, "skills", "record-keeping", "scripts", "records.py")
PROV = os.path.join(HERE, os.pardir, os.pardir, "provenance-log", "skills", "provenance-log",
                    "scripts", "provenance.py")
VERBOSE = "-v" in sys.argv
FAILED = []
ENV = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")


def run(root, *args, ok=True):
    r = subprocess.run([sys.executable, CLI, "--root", root] + list(args),
                       capture_output=True, text=True, env=ENV)
    if ok and r.returncode:
        raise AssertionError("records.py %s failed:\n%s%s" % (args, r.stdout, r.stderr))
    return r


def git(root, *args):
    return subprocess.run(["git", "-C", root] + list(args), capture_output=True, text=True,
                          env=ENV).stdout


def check(name, cond, detail=""):
    if not cond:
        FAILED.append(name)
        print("FAIL %s %s" % (name, detail))
    elif VERBOSE:
        print("ok   %s" % name)


def fresh():
    d = tempfile.mkdtemp(prefix="records-test-")
    run(d, "init", "--title", "Test project", "--expires",
        (dt.date.today() + dt.timedelta(days=10)).isoformat(),
        "--git-name", "Tester", "--git-email", "t@example.org")
    return d


def test_init_creates_records_and_commits():
    d = fresh()
    for f in ("README.md", "DECISIONS.md", ".gitignore", ".records.json", "scripts", "logs"):
        check("init creates " + f, os.path.exists(os.path.join(d, f)))
    tracked = git(d, "ls-files").split()
    check("init commits README", "README.md" in tracked, tracked)
    check("init commits DECISIONS", "DECISIONS.md" in tracked, tracked)
    check("local identity", git(d, "config", "--local", "user.name").strip() == "Tester")
    check("expiry in README", "Storage expires" in open(os.path.join(d, "README.md")).read())
    shutil.rmtree(d)


def test_init_never_overwrites():
    d = fresh()
    with open(os.path.join(d, "README.md"), "w") as fh:
        fh.write("hand-written\n")
    run(d, "init", "--title", "Other")
    check("README kept", open(os.path.join(d, "README.md")).read() == "hand-written\n")
    check("title kept", json.load(open(os.path.join(d, ".records.json")))["title"] == "Test project")
    shutil.rmtree(d)


def test_whitelist_nested_and_data_ignored():
    d = fresh()
    os.makedirs(os.path.join(d, "refs", "sub"))
    os.makedirs(os.path.join(d, "align"))
    for f in ("refs/sub/q.faa", "refs/big.fna", "align/x.bam", "samples.tsv"):
        open(os.path.join(d, f), "w").write("x\n")
    run(d, "track", os.path.join(d, "refs/sub/q.faa"), os.path.join(d, "samples.tsv"))
    run(d, "checkpoint", "-m", "track", "--no-provenance")
    tracked = set(git(d, "ls-files").split())
    check("nested file tracked", "refs/sub/q.faa" in tracked, tracked)
    check("sibling data ignored", "refs/big.fna" not in tracked, tracked)
    check("data dir ignored", "align/x.bam" not in tracked, tracked)
    check("sample table tracked", "samples.tsv" in tracked, tracked)
    r = run(d, "track", os.path.join(d, "samples.tsv"))
    check("track idempotent", "already tracked" in r.stdout, r.stdout)
    shutil.rmtree(d)


def test_track_warns_large():
    d = fresh()
    with open(os.path.join(d, "big.tsv"), "wb") as fh:
        fh.write(b"0" * 2_000_000)
    r = run(d, "track", os.path.join(d, "big.tsv"), "--max-mb", "1")
    check("large-file warning", "WARNING" in r.stdout, r.stdout)
    shutil.rmtree(d)


def test_decide_ids_supersede_and_status():
    d = fresh()
    a = run(d, "decide", "--what", "Use HISAT2", "--why", "splice-aware", "--by", "claude").stdout.strip()
    b = run(d, "decide", "--what", "Drop L1", "--why", "truncated", "--by", "user").stdout.strip()
    check("sequential ids", (a, b) == ("D001", "D002"), (a, b))
    s = run(d, "status").stdout
    check("unconfirmed listed", "1 awaiting user confirmation: D001" in s, s)
    c = run(d, "decide", "--what", "Use HISAT2", "--why", "user agreed", "--by", "user-confirmed",
            "--supersedes", "D001").stdout.strip()
    text = open(os.path.join(d, "DECISIONS.md")).read()
    check("old entry marked", "## D001 " in text and "(superseded by D003)" in text, text)
    check("old reasoning kept", "splice-aware" in text)
    check("supersedes line", "**Supersedes:** D001" in text)
    s = run(d, "status").stdout
    check("superseded no longer unconfirmed", "0 awaiting" in s, s)
    r = run(d, "decide", "--what", "x", "--why", "y", "--by", "user", "--supersedes", "D099", ok=False)
    check("unknown supersedes rejected", r.returncode != 0)
    shutil.rmtree(d)


def test_status_expiry_and_open():
    d = fresh()
    with open(os.path.join(d, "README.md"), "a") as fh:
        fh.write("- Strandedness unknown\n- Species of L80959 unknown\n")
    s = run(d, "status").stdout
    check("archive warning inside 14 days", "ARCHIVE NOW" in s, s)
    check("open items counted", "OPEN items in README: 2" in s, s)
    check("uncommitted shown", "uncommitted: 1" in s, s)
    shutil.rmtree(d)


def test_checkpoint_records_provenance():
    if not os.path.exists(PROV):
        print("skip provenance integration: %s not found" % PROV)
        return
    d = fresh()
    pdir = os.path.join(d, "provenance")
    subprocess.run([sys.executable, PROV, "--dir", pdir, "init", "--title", "t"],
                   capture_output=True, cwd=d, env=ENV, check=True)
    run(d, "track", pdir)
    run(d, "decide", "--what", "x", "--why", "y", "--by", "user")
    env = dict(ENV, PROVENANCE_PY=PROV)
    r = subprocess.run([sys.executable, CLI, "--root", d, "checkpoint", "-m", "Step 1"],
                       capture_output=True, text=True, env=env)
    check("checkpoint ok", r.returncode == 0, r.stderr)
    check("provenance step for decisions", "provenance step: DECISIONS.md" in r.stdout, r.stdout)
    m = json.load(open(os.path.join(pdir, "manifest.json")))
    check("step in manifest", any("records: Step 1" in s.get("cmd", "") for s in m["steps"]),
          m["steps"])
    check("rendered", os.path.exists(os.path.join(pdir, "PROVENANCE.md")))
    tracked = git(d, "ls-files")
    check("provenance committed", "provenance/manifest.json" in tracked, tracked)
    check("lock not committed", ".manifest.lock" not in tracked, tracked)
    check("commit message", "Step 1" in git(d, "log", "-1", "--format=%s"))
    r = subprocess.run([sys.executable, CLI, "--root", d, "checkpoint", "-m", "again"],
                       capture_output=True, text=True, env=env)
    check("no-op checkpoint: no extra provenance step",
          "provenance step" not in r.stdout, r.stdout)
    # An edit the hook (or a manual step) already recorded must not get a second step.
    with open(os.path.join(d, "README.md"), "a") as fh:
        fh.write("- new open item\n")
    subprocess.run([sys.executable, PROV, "--dir", pdir, "step", "--cmd", "hook-like edit",
                    "--out", os.path.join(d, "README.md")], capture_output=True, cwd=d, env=ENV,
                   check=True)
    n = len(json.load(open(os.path.join(pdir, "manifest.json")))["steps"])
    r = subprocess.run([sys.executable, CLI, "--root", d, "checkpoint", "-m", "Step 2"],
                       capture_output=True, text=True, env=env)
    m = json.load(open(os.path.join(pdir, "manifest.json")))
    check("duplicate skipped", "already in provenance: README.md" in r.stdout, r.stdout)
    check("no second step", len(m["steps"]) == n, (n, len(m["steps"])))
    check("still committed", "Step 2" in git(d, "log", "-1", "--format=%s"))
    shutil.rmtree(d)


def test_archive_copies_verifies_and_resumes():
    d = fresh()
    dest = tempfile.mkdtemp(prefix="records-archive-")
    os.makedirs(os.path.join(d, "results"))
    open(os.path.join(d, "results", "tpm.tsv"), "w").write("gene\ttpm\n")
    open(os.path.join(d, "untracked.bam"), "w").write("x")
    run(d, "archive", "--to", dest, "--include", "results", "--dry-run")
    check("dry run copies nothing", not os.path.exists(os.path.join(dest, "README.md")))
    r = run(d, "archive", "--to", dest, "--include", "results")
    check("tracked copied", os.path.exists(os.path.join(dest, "README.md")))
    check("include copied", os.path.exists(os.path.join(dest, "results", "tpm.tsv")))
    check("untracked not copied", not os.path.exists(os.path.join(dest, "untracked.bam")))
    man = open(os.path.join(dest, "ARCHIVE_MANIFEST.tsv")).read()
    check("manifest has sha256", "results/tpm.tsv\t9\t" in man, man)
    cfg = json.load(open(os.path.join(d, ".records.json")))
    check("archive date stored", cfg.get("archived", {}).get("to") == os.path.abspath(dest), cfg)
    check("status shows archive", "archived: " + dt.date.today().isoformat() in run(d, "status").stdout)
    r = run(d, "archive", "--to", os.path.join(d, "inside"), ok=False)
    check("refuses destination inside project", r.returncode != 0)
    shutil.rmtree(d)
    shutil.rmtree(dest)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
            except AssertionError as e:
                FAILED.append(name)
                print("FAIL %s: %s" % (name, e))
    print("%d failed" % len(FAILED) if FAILED else "all tests passed")
    sys.exit(1 if FAILED else 0)
