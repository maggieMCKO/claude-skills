#!/usr/bin/env python3
"""Regression tests for provenance.py. Stdlib only; no pytest required.

    python3 test_provenance.py            # run all
    python3 test_provenance.py -v         # show each assertion

Every test here corresponds to a defect that was observed, not imagined.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
# Works whether the tests sit beside provenance.py or in tests/ with the CLI
# under ../scripts/ (the repo layout).
CANDIDATES = [
    os.path.join(HERE, "provenance.py"),
    os.path.join(HERE, "scripts", "provenance.py"),
    os.path.join(HERE, os.pardir, "scripts", "provenance.py"),
    os.path.join(HERE, os.pardir, "provenance.py"),
    os.path.join(HERE, os.pardir, "skills", "provenance-log", "scripts", "provenance.py"),
]
CLI = next((os.path.abspath(c) for c in CANDIDATES if os.path.exists(c)), None)
if CLI is None:
    sys.exit("cannot locate provenance.py relative to %s" % HERE)

FAILED = []
VERBOSE = "-v" in sys.argv


def run(args, cwd, stdin=None, check=True):
    r = subprocess.run([sys.executable, CLI] + args, cwd=cwd, input=stdin,
                       capture_output=True, text=True)
    if check and r.returncode not in (0, 1):
        raise AssertionError("exit %d: %s" % (r.returncode, r.stderr))
    return r


def manifest(cwd, root="provenance"):
    with open(os.path.join(cwd, root, "manifest.json")) as fh:
        return json.load(fh)


def check(name, cond, detail=""):
    if cond:
        if VERBOSE:
            print("  ok   %s" % name)
    else:
        print("  FAIL %s %s" % (name, detail))
        FAILED.append(name)


def test_capped_hash_verify():
    """A capped hash must not report CHANGED when the file is untouched."""
    d = tempfile.mkdtemp()
    try:
        with open(os.path.join(d, "big.bin"), "wb") as fh:
            fh.write(b"A" * 3_000_000)
        run(["init", "--title", "t"], d)
        run(["--cap-bytes", "1048576", "step", "--cmd", "x", "--in", "big.bin"], d)
        e = manifest(d)["files"]["big.bin"]
        check("cap recorded in entry", e.get("hashed_bytes") == 1048576, e)
        r = run(["verify"], d)                      # note: no --cap-bytes
        check("no false CHANGED", "0 discrepancies" in r.stdout, r.stdout.strip())
        check("verify exits 0 when clean", r.returncode == 0, r.returncode)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_verify_detects_real_change():
    """Verify must still catch a genuine modification."""
    d = tempfile.mkdtemp()
    try:
        p = os.path.join(d, "f.txt")
        open(p, "w").write("one")
        run(["init", "--title", "t"], d)
        run(["step", "--cmd", "x", "--out", "f.txt"], d)
        open(p, "w").write("two")
        r = run(["verify"], d)
        check("real change detected", "1 discrepancies" in r.stdout, r.stdout.strip())
        check("verify exits nonzero on drift", r.returncode == 1, r.returncode)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_probe_never_fabricates_version():
    """A tool whose --help exits 0 must not get a usage line as its version."""
    d = tempfile.mkdtemp()
    try:
        bindir = os.path.join(d, "bin")
        os.makedirs(bindir)
        # Mimics the real failure mode: every version flag FAILS, but --help
        # succeeds with a usage line. The old code fell back to --help and
        # stored "Usage: ..." as the version.
        tool = os.path.join(bindir, "faketool")
        open(tool, "w").write(
            '#!/bin/sh\n'
            'case "$1" in\n'
            '  --help) echo "Usage: faketool [options] <input>"; exit 0 ;;\n'
            '  *)      echo "faketool: unrecognized option $1" >&2; exit 2 ;;\n'
            'esac\n')
        os.chmod(tool, 0o755)
        run(["init", "--title", "t"], d)
        env = dict(os.environ, PATH=bindir + os.pathsep + os.environ["PATH"])
        subprocess.run([sys.executable, CLI, "env", "--probe", "faketool"],
                       cwd=d, env=env, capture_output=True, text=True)
        info = manifest(d)["environment"]["tools"]["faketool"]
        check("present but version unknown", info.get("version_unknown") is True, info)
        check("usage line not stored as version",
              "Usage" not in (info.get("version") or ""), info)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_concurrent_hooks_lose_nothing():
    """N concurrent hook writes must produce exactly N steps and never raise."""
    d = tempfile.mkdtemp()
    try:
        run(["init", "--title", "t"], d)
        n = 16
        procs = [subprocess.Popen(
            [sys.executable, CLI, "hook"], cwd=d, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            for _ in range(n)]
        for i, p in enumerate(procs):
            p.communicate(json.dumps({"tool_input": {"command": "real_cmd_%d" % i},
                                      "cwd": d}))
        steps = manifest(d)["steps"]
        check("no steps lost under concurrency", len(steps) == n,
              "expected %d, got %d" % (n, len(steps)))
        check("all hooks exited 0", all(p.returncode == 0 for p in procs),
              [p.returncode for p in procs])
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_hook_ignores_self_and_trivia():
    d = tempfile.mkdtemp()
    try:
        run(["init", "--title", "t"], d)
        for cmd in ("python3 provenance.py finalize", "ls -la", "pwd", "cd /tmp"):
            run(["hook"], d, stdin=json.dumps({"tool_input": {"command": cmd},
                                               "cwd": d}))
        check("self-calls and trivia skipped", len(manifest(d)["steps"]) == 0,
              manifest(d)["steps"])
        run(["hook"], d, stdin=json.dumps(
            {"tool_input": {"command": "ls > listing.txt"}, "cwd": d}))
        check("redirect kept (produces a file)", len(manifest(d)["steps"]) == 1)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_hook_finds_manifest_from_subdir():
    """The agent may cd below the manifest; logging must continue."""
    d = tempfile.mkdtemp()
    try:
        run(["init", "--title", "t"], d)
        sub = os.path.join(d, "a", "b")
        os.makedirs(sub)
        run(["hook"], sub, stdin=json.dumps(
            {"tool_input": {"command": "samtools sort x.bam"}, "cwd": sub}))
        check("logged from subdirectory", len(manifest(d)["steps"]) == 1,
              manifest(d)["steps"])
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_hook_silent_without_manifest():
    d = tempfile.mkdtemp()
    try:
        r = run(["hook"], d, stdin=json.dumps(
            {"tool_input": {"command": "echo hi"}, "cwd": d}))
        check("exits 0 with no manifest", r.returncode == 0)
        check("writes nothing", not os.path.exists(os.path.join(d, "provenance")))
        r = run(["hook"], d, stdin="not json at all")
        check("survives malformed payload", r.returncode == 0)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_hook_opt_out():
    d = tempfile.mkdtemp()
    try:
        run(["init", "--title", "t"], d)
        payload = json.dumps({"tool_input": {"command": "samtools sort x.bam"}, "cwd": d})
        env = dict(os.environ, PROVENANCE_HOOK="0")
        r = subprocess.run([sys.executable, CLI, "hook"], cwd=d, input=payload,
                           capture_output=True, text=True, env=env)
        check("opt-out exits 0", r.returncode == 0)
        check("opt-out records nothing", len(manifest(d)["steps"]) == 0)
        run(["hook"], d, stdin=payload)
        check("default still records", len(manifest(d)["steps"]) == 1)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_secret_redaction():
    d = tempfile.mkdtemp()
    try:
        run(["init", "--title", "t"], d)
        run(["step", "--cmd", "curl -H 'Authorization: Bearer sk-abcd1234efgh5678ijkl' "
                              "https://api.example.com --token ghp_ABCDEFGHIJKLMNOP1234"], d)
        cmd = manifest(d)["steps"][0]["cmd"]
        for leak in ("sk-abcd1234efgh5678ijkl", "ghp_ABCDEFGHIJKLMNOP1234"):
            check("redacted %s" % leak[:8], leak not in cmd, cmd)
        run(["step", "--cmd", "export API_KEY=supersecretvalue123"], d)
        check("env-style secret redacted",
              "supersecretvalue123" not in manifest(d)["steps"][1]["cmd"],
              manifest(d)["steps"][1]["cmd"])
        run(["step", "--cmd", "samtools view -q 30 -o out.bam in.bam"], d)
        check("ordinary command untouched",
              manifest(d)["steps"][2]["cmd"] == "samtools view -q 30 -o out.bam in.bam")
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_finalize_report():
    d = tempfile.mkdtemp()
    try:
        run(["init", "--title", "Example run"], d)
        run(["env", "--probe", "git"], d)
        run(["step", "--cmd", "aligner --in a.fq --out a.bam",
             "--deviation", "tool B substituted for tool A"], d)
        r = run(["finalize"], d)
        text = open(os.path.join(d, "provenance", "PROVENANCE.md")).read()
        check("report written", "wrote" in r.stdout)
        check("title present", "Example run" in text)
        check("deviation section present", "Deviations from the intended method" in text)
        check("deviation body present", "tool B substituted" in text)
        check("software table present", "## Software versions" in text)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_duplicate_hook_suppressed():
    """Global + project hooks fire together; the second must not double-count."""
    d = tempfile.mkdtemp()
    try:
        run(["init", "--title", "t"], d)
        payload = json.dumps({"tool_input": {"command": "bwa mem ref.fa r.fq"},
                              "cwd": d})
        run(["hook"], d, stdin=payload)      # global hook
        run(["hook"], d, stdin=payload)      # project hook, same tool call
        check("duplicate suppressed", len(manifest(d)["steps"]) == 1,
              manifest(d)["steps"])
        # A different command is never suppressed.
        run(["hook"], d, stdin=json.dumps(
            {"tool_input": {"command": "samtools index a.bam"}, "cwd": d}))
        check("distinct command recorded", len(manifest(d)["steps"]) == 2)
        # Outside the window, a genuine re-run is recorded.
        env = dict(os.environ, PROVENANCE_DEDUPE_SECONDS="0")
        subprocess.run([sys.executable, CLI, "hook"], cwd=d, input=payload,
                       capture_output=True, text=True, env=env)
        check("re-run recorded outside window", len(manifest(d)["steps"]) == 3,
              len(manifest(d)["steps"]))
    finally:
        shutil.rmtree(d, ignore_errors=True)


# --- 0.3.0: defects observed in a real multi-day RNA-seq run --------------------

def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)


def test_relative_and_absolute_paths_share_one_key():
    """Recording scripts/a.sh, then /abs/.../scripts/a.sh, made two entries; the
    stale one kept failing verify after the script was re-recorded."""
    d = tempfile.mkdtemp()
    try:
        s = os.path.join(d, "scripts", "a.sh")
        write(s, "echo v1\n")
        run(["init", "--title", "t"], d)
        run(["step", "--cmd", "x", "--script", s], d)              # absolute
        write(s, "echo v2\n")
        run(["step", "--cmd", "y", "--script", "scripts/a.sh"], d)  # relative
        files = manifest(d)["files"]
        check("one key for one file", list(files) == ["scripts/a.sh"], list(files))
        r = run(["verify"], d)
        check("verify clean after re-record", r.returncode == 0, r.stdout)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_project_move_keeps_verify_clean():
    """Moving the project folder flagged every rewritten-path file; project-relative
    keys must survive a move untouched."""
    base = tempfile.mkdtemp()
    try:
        d = os.path.join(base, "old")
        write(os.path.join(d, "data", "in.txt"), "data\n")
        write(os.path.join(d, "run.sh"), "cat data/in.txt\n")
        run(["init", "--title", "t"], d)
        run(["step", "--cmd", "sh run.sh", "--in", os.path.join(d, "data", "in.txt"),
             "--script", os.path.join(d, "run.sh")], d)
        new = os.path.join(base, "new", "project")
        os.makedirs(os.path.dirname(new))
        shutil.move(d, new)
        r = run(["verify"], new)
        check("verify clean after moving the project", r.returncode == 0, r.stdout)
        r = run(["--dir", os.path.join(new, "provenance"), "verify"], base)
        check("verify clean via --dir from elsewhere", r.returncode == 0, r.stdout)
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_each_step_keeps_its_own_checksum_and_snapshot():
    """Only the latest checksum was kept, so an earlier step could not say which
    version of a since-edited script it ran, and the old text was gone."""
    d = tempfile.mkdtemp()
    try:
        s = os.path.join(d, "align.sh")
        write(s, "hisat2 --dta\n")
        run(["init", "--title", "t"], d)
        run(["step", "--cmd", "sbatch align.sh", "--script", "align.sh"], d)
        write(s, "hisat2 --dta --no-temp-splicesite\n")
        run(["step", "--cmd", "sbatch align.sh", "--script", "align.sh"], d)
        st = manifest(d)["steps"]
        h1, h2 = st[0]["hashes"]["align.sh"], st[1]["hashes"]["align.sh"]
        check("steps keep distinct checksums", h1 and h2 and h1 != h2, (h1, h2))
        snaps = sorted(os.listdir(os.path.join(d, "provenance", "scripts")))
        check("one snapshot per version", len(snaps) == 2, snaps)
        old = [f for f in snaps if f.startswith(h1[:12])]
        text = open(os.path.join(d, "provenance", "scripts", old[0])).read() if old else ""
        check("old version readable", text == "hisat2 --dta\n", text)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_supersede_retires_a_wrong_entry():
    """A step recorded a path that never existed; verify failed forever because
    steps are append-only and entries could not be removed."""
    d = tempfile.mkdtemp()
    try:
        write(os.path.join(d, "SRR", "dl.sh"), "curl ...\n")
        run(["init", "--title", "t"], d)
        run(["step", "--cmd", "dl", "--script", "scripts/dl.sh"], d)   # wrong path
        check("wrong path fails verify", run(["verify"], d).returncode == 1)
        r = run(["supersede", "--step", "1", "--reason", "script is under SRR/",
                 "--retire", "scripts/dl.sh"], d)
        run(["step", "--cmd", "dl", "--script", "SRR/dl.sh"], d)
        m = manifest(d)
        check("step 1 marked superseded", m["steps"][0].get("superseded", {}).get("by_step") == 2,
              m["steps"][0])
        check("entry retired with reason", "scripts/dl.sh" in m.get("retired_files", {}))
        r = run(["verify"], d)
        check("verify clean after correction", r.returncode == 0, r.stdout)
        run(["render"], d)
        text = open(os.path.join(d, "provenance", "PROVENANCE.md")).read()
        check("report shows supersession", "superseded by step 2" in text)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_edit_hook_rerecords_tracked_file():
    """A recorded script was edited with the agent's edit tool and re-run, and no
    step was recorded; the edit hook must log it. Untracked edits are ignored."""
    d = tempfile.mkdtemp()
    try:
        s = os.path.join(d, "align.sh")
        write(s, "v1\n")
        run(["init", "--title", "t"], d)
        run(["step", "--cmd", "x", "--script", "align.sh"], d)
        write(s, "v2\n")
        run(["hook"], d, stdin=json.dumps({"tool_name": "Edit", "cwd": d,
                                           "tool_input": {"file_path": s}}))
        m = manifest(d)
        check("edit logged as a step", len(m["steps"]) == 2, m["steps"])
        check("checksum updated", m["files"]["align.sh"].get("changed_from"), m["files"])
        check("verify clean after logged edit", run(["verify"], d).returncode == 0)
        other = os.path.join(d, "notes.txt")
        write(other, "x\n")
        run(["hook"], d, stdin=json.dumps({"tool_name": "Write", "cwd": d,
                                           "tool_input": {"file_path": other}}))
        check("untracked edit ignored", len(manifest(d)["steps"]) == 2)
        run(["hook"], d, stdin=json.dumps({"tool_name": "Edit", "cwd": d,
                                           "tool_input": {"file_path": s}}))
        check("no-op edit not logged", len(manifest(d)["steps"]) == 2)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_render_is_interim_finalize_stamps():
    """finalize was rerun after every stage, stamping an unfinished run as final."""
    d = tempfile.mkdtemp()
    try:
        run(["init", "--title", "t"], d)
        run(["render"], d)
        check("render leaves run unfinished", manifest(d)["finalized_utc"] is None)
        run(["finalize"], d)
        check("finalize stamps", manifest(d)["finalized_utc"] is not None)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_migrate_legacy_manifest_with_moved_prefix():
    """A /1 manifest with absolute keys under an old location, plus a relative
    duplicate, must migrate to one project-relative key and verify clean."""
    d = tempfile.mkdtemp()
    try:
        write(os.path.join(d, "scripts", "a.sh"), "v2\n")
        run(["init", "--title", "t"], d)
        m = manifest(d)
        digest = __import__("hashlib").sha256(b"v2\n").hexdigest()
        m["schema"] = "provenance-log/1"
        m["files"] = {
            "/old/place/scripts/a.sh": {"role": "script", "sha256": "0" * 64, "bytes": 3,
                                        "partial_hash": False, "seen": "2026-01-01T00:00:00Z"},
            "scripts/a.sh": {"role": "script", "sha256": digest, "bytes": 3,
                             "partial_hash": False, "seen": "2026-02-01T00:00:00Z"}}
        m["steps"] = [{"n": 1, "utc": "2026-01-01T00:00:00Z", "cmd": "x", "inputs": [],
                       "outputs": [], "scripts": ["/old/place/scripts/a.sh"], "note": None,
                       "deviation": None, "exit_code": None}]
        with open(os.path.join(d, "provenance", "manifest.json"), "w") as fh:
            json.dump(m, fh)
        r = run(["migrate", "--from", "/old/place", "--to", d], d)
        m = manifest(d)
        check("schema upgraded", m["schema"] == "provenance-log/2", m["schema"])
        check("duplicate keys merged", list(m["files"]) == ["scripts/a.sh"], list(m["files"]))
        check("step path rewritten", m["steps"][0]["scripts"] == ["scripts/a.sh"], m["steps"][0])
        check("newest entry kept; verify clean", run(["verify"], d).returncode == 0)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_step_records_git_commit():
    """The git commit was captured only at init (empty if the repo came later)."""
    d = tempfile.mkdtemp()
    try:
        if not shutil.which("git"):
            return
        run(["init", "--title", "t"], d)
        g = ["git", "-C", d, "-c", "user.name=t", "-c", "user.email=t@t"]
        subprocess.run(g + ["init", "-q"], check=True)
        write(os.path.join(d, "a.sh"), "x\n")
        subprocess.run(g + ["add", "a.sh"], check=True)
        subprocess.run(g + ["commit", "-q", "-m", "c"], check=True)
        run(["step", "--cmd", "x", "--script", "a.sh"], d)
        st = manifest(d)["steps"][0]
        check("step carries git commit", len((st.get("git") or {}).get("commit") or "") == 40, st)
    finally:
        shutil.rmtree(d, ignore_errors=True)


# --- install_hook.py -----------------------------------------------------------

INSTALLER = os.path.join(os.path.dirname(CLI), os.pardir, "install_hook.py")
if not os.path.exists(INSTALLER):
    INSTALLER = os.path.join(os.path.dirname(CLI), "install_hook.py")
INSTALLER = os.path.abspath(INSTALLER)


def run_installer(args, cwd):
    return subprocess.run([sys.executable, INSTALLER] + args, cwd=cwd,
                          capture_output=True, text=True)


def hook_cmds(path):
    with open(path) as fh:
        cfg = json.load(fh)
    return [h["command"] for g in cfg["hooks"]["PostToolUse"] for h in g["hooks"]]


def test_installer_scope_paths():
    """A project install must point at the project's copy, not the personal one."""
    d = tempfile.mkdtemp()
    try:
        run_installer(["--path", "personal.json", "--apply"], d)
        run_installer(["--path", "proj.json", "--project", "--apply"], d)
        p = hook_cmds(os.path.join(d, "personal.json"))[0]
        q = hook_cmds(os.path.join(d, "proj.json"))[0]
        check("personal uses $HOME", "$HOME/.claude/skills" in p, p)
        check("project uses CLAUDE_PROJECT_DIR", "CLAUDE_PROJECT_DIR" in q, q)
        check("project does not use $HOME", "$HOME" not in q, q)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_installer_preserves_and_is_idempotent():
    d = tempfile.mkdtemp()
    try:
        p = os.path.join(d, "s.json")
        with open(p, "w") as fh:
            json.dump({"model": "some-model",
                       "permissions": {"allow": ["Bash(git diff:*)"]},
                       "hooks": {"PostToolUse": [
                           {"matcher": "Bash",
                            "hooks": [{"type": "command", "command": "echo linter"}]}]}}, fh)
        run_installer(["--path", "s.json", "--apply"], d)
        with open(p) as fh:
            cfg = json.load(fh)
        check("unrelated keys preserved",
              cfg.get("model") == "some-model" and "permissions" in cfg, list(cfg))
        cmds = hook_cmds(p)
        check("existing hook kept", "echo linter" in cmds, cmds)
        check("ours appended", any("provenance-log" in c for c in cmds), cmds)
        r = run_installer(["--path", "s.json", "--apply"], d)
        check("idempotent", "already installed" in r.stdout, r.stdout.strip())
        # linter + ours on Bash + ours on the edit tools (0.3.0)
        check("still three hooks", len(hook_cmds(p)) == 3, hook_cmds(p))
        with open(p) as fh:
            groups = json.load(fh)["hooks"]["PostToolUse"]
        bash = [g for g in groups if g["matcher"] == "Bash"][0]
        check("linter's Bash group not widened to edits",
              len(groups) == 2 and len(bash["hooks"]) == 2, groups)
        run_installer(["--path", "s.json", "--remove", "--apply"], d)
        check("removal leaves the other hook", hook_cmds(p) == ["echo linter"],
              hook_cmds(p))
        backups = [f for f in os.listdir(d) if ".bak-" in f]
        check("timestamped backup written", len(backups) >= 1, backups)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_installer_refuses_bad_json():
    d = tempfile.mkdtemp()
    try:
        p = os.path.join(d, "broken.json")
        open(p, "w").write("{not json")
        r = run_installer(["--path", "broken.json", "--apply"], d)
        check("refuses malformed json", r.returncode != 0, r.returncode)
        check("file untouched", open(p).read() == "{not json", open(p).read())
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_installer_dry_run_writes_nothing():
    d = tempfile.mkdtemp()
    try:
        r = run_installer(["--path", "dry.json"], d)
        check("dry run writes no file",
              not os.path.exists(os.path.join(d, "dry.json")))
        check("dry run shows the block", "PostToolUse" in r.stdout, r.stdout[:200])
    finally:
        shutil.rmtree(d, ignore_errors=True)


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    print("provenance.py regression suite — %d tests\n" % len(tests))
    for t in tests:
        print("%s:" % t.__name__)
        try:
            t()
        except Exception as exc:
            print("  ERROR %s: %s" % (t.__name__, exc))
            FAILED.append(t.__name__)
    print()
    if FAILED:
        print("FAILED (%d): %s" % (len(FAILED), ", ".join(FAILED)))
        return 1
    print("all tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
