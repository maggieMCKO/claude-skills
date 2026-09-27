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
        check("still two hooks", len(hook_cmds(p)) == 2, hook_cmds(p))
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
