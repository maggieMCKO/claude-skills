#!/usr/bin/env python3
"""Mechanical provenance capture: steps, software versions, scripts, checksums.

Stdlib only, Python 3.8+. Runs in an agent kernel, a bare shell, or a job script.

    provenance.py init     --title "Variant calling, cohort A"
    provenance.py env      --probe bwa --probe samtools --probe bcftools
    provenance.py step     --cmd "bwa mem ref.fa reads.fq.gz > aligned.sam" \
                           --in reads.fq.gz --out aligned.sam \
                           --script scripts/align.sh \
                           --deviation "aligner B used instead of A (see README)"
    provenance.py finalize                 # writes PROVENANCE.md
    provenance.py verify                   # exit 1 if a tracked file drifted

Writes provenance/manifest.json (machine-readable) and PROVENANCE.md (human).

Privacy: command strings are recorded verbatim apart from best-effort redaction
of named secrets and known token shapes. Review a manifest before committing it.
"""
import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import time

SCHEMA = "provenance-log/1"
DEFAULT_DIR = "provenance"


def utcnow():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def manifest_path(root=None):
    return os.path.join(root or DEFAULT_DIR, "manifest.json")


def load(root=None):
    p = manifest_path(root)
    if not os.path.exists(p):
        sys.exit("no manifest at %s — run `provenance.py init` first" % p)
    with open(p) as fh:
        return json.load(fh)


def save(m, root=None):
    p = manifest_path(root)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    # PID-unique temp name: two concurrent writers must not share a temp path,
    # or one os.replace() wins and the other raises FileNotFoundError.
    tmp = "%s.tmp.%d" % (p, os.getpid())
    with open(tmp, "w") as fh:
        json.dump(m, fh, indent=2, sort_keys=False)
    os.replace(tmp, p)


def with_lock(root, mutate):
    """Serialise read-modify-write on the manifest.

    Without this, two agent shell calls landing together each read the manifest,
    append one step and write back — and the later write silently drops the
    earlier step. Measured: 12 concurrent writers produced 8 recorded steps.
    """
    d = root or DEFAULT_DIR
    os.makedirs(d, exist_ok=True)
    lock = os.path.join(d, ".manifest.lock")
    try:
        import fcntl
    except ImportError:              # non-POSIX: proceed unlocked
        m = load(root)
        out = mutate(m)
        save(m, root)
        return out
    with open(lock, "w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            m = load(root)
            out = mutate(m)
            save(m, root)
        finally:
            fcntl.flock(lf, fcntl.LOCK_UN)
    return out


def find_manifest_dir(start):
    """Walk up from `start` to find an existing manifest directory.

    The agent may have cd'd into a subdirectory; without this the hook looks in
    the wrong place, finds nothing and stops logging silently.
    """
    cur = os.path.abspath(start or ".")
    while True:
        if os.path.exists(os.path.join(cur, DEFAULT_DIR, "manifest.json")):
            return os.path.join(cur, DEFAULT_DIR)
        parent = os.path.dirname(cur)
        if parent == cur:
            return None
        cur = parent


def redact(text):
    """Mask obvious credentials before a command string is written to disk.

    The hook records whole command lines, so an exported key or a curl auth
    header would otherwise be committed to the manifest. Conservative by
    design: named secret assignments and known token shapes only, so it never
    mangles a checksum, a path or an ordinary flag. NOT a guarantee — treat a
    manifest from a session that handled credentials as sensitive.
    """
    import re
    out = text
    out = re.sub(r"(?i)\b(api[-_ ]?key|apikey|token|secret|password|passwd|"
                 r"access[-_ ]?key|secret[-_ ]?key|auth)(\s*[=:]\s*)(\S+)",
                 r"\1\2<redacted>", out)
    out = re.sub(r"(?i)(authorization:\s*(?:bearer|basic)\s+)(\S+)",
                 r"\1<redacted>", out)
    out = re.sub(r"(?i)(--(?:password|token|api-key|apikey|secret)[=\s]+)(\S+)",
                 r"\1<redacted>", out)
    # Unambiguous provider token shapes.
    out = re.sub(r"\b(gh[pousr]_[A-Za-z0-9]{16,})", "<redacted-github-token>", out)
    out = re.sub(r"\bsk-[A-Za-z0-9\-_]{20,}", "<redacted-api-key>", out)
    out = re.sub(r"\bAKIA[0-9A-Z]{16}\b", "<redacted-aws-key>", out)
    return out


TRIVIAL = ("ls", "pwd", "cd", "echo", "which", "whoami", "clear", "date",
           "head", "tail", "wc", "file", "stat", "du", "df", "env")

# Seconds within which an identical command is treated as a duplicate hook
# firing rather than a genuine re-run. Override with PROVENANCE_DEDUPE_SECONDS.
DEDUPE_SECONDS = 2.0


def parse_utc(stamp):
    """Parse a manifest timestamp to epoch seconds; None if unparseable.

    calendar.timegm, not time.mktime: the stamps are UTC, and mktime would read
    them as local time and skew every comparison by the timezone offset.
    """
    import calendar
    try:
        return calendar.timegm(time.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ"))
    except Exception:
        return None


def is_duplicate_hook(m, cmd):
    """True if `cmd` matches the last recorded step within the dedupe window.

    An agent may have this hook installed both globally and per project. Those
    are two different command strings, so both fire for a single tool call and
    each appends the same step -- a per-file duplicate check cannot see it.
    Comparing against the last recorded step catches it wherever it comes from.

    The cost is that a deliberate re-run of an identical command inside the
    window is dropped. The window is therefore short: the paired hook calls for
    one tool invocation land milliseconds apart.
    """
    steps = m.get("steps") or []
    if not steps:
        return False
    last = steps[-1]
    if (last.get("cmd") or "") != cmd:
        return False
    try:
        window = float(os.environ.get("PROVENANCE_DEDUPE_SECONDS", DEDUPE_SECONDS))
    except ValueError:
        window = DEDUPE_SECONDS
    then = parse_utc(last.get("utc") or "")
    if then is None:
        return True          # same command, unknown time: prefer not to double-count
    return (time.time() - then) <= window


def is_trivial(cmd):
    """True for a bare navigation/inspection command with no side effects.

    Only when the command is a single simple word-led invocation: anything with
    a pipe, redirect or chain may well produce a file, so it is kept.
    """
    s = (cmd or "").strip()
    if not s or any(ch in s for ch in ("|", ">", "<", "&", ";", "$(", "`")):
        return False
    return s.split()[0] in TRIVIAL


def sha256(path, cap_bytes=None):
    """Checksum a file. cap_bytes truncates for very large files (recorded as partial)."""
    h = hashlib.sha256()
    n = 0
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
            n += len(chunk)
            if cap_bytes and n >= cap_bytes:
                return h.hexdigest(), n, True
    return h.hexdigest(), n, False


def record_file(m, path, role, cap_bytes=None):
    """Register a file with its checksum; flags drift if already seen with a different hash."""
    if not os.path.exists(path):
        m["files"][path] = {"role": role, "missing": True, "seen": utcnow()}
        return "MISSING"
    digest, nbytes, partial = sha256(path, cap_bytes)
    prev = m["files"].get(path)
    entry = {"role": role, "sha256": digest, "bytes": nbytes,
             "partial_hash": partial, "seen": utcnow()}
    # Persist the cap the hash was computed under, so `verify` can reproduce it
    # exactly. Without this, verifying a capped file without repeating the same
    # --cap-bytes re-hashes it in full and reports a false CHANGED.
    if partial:
        entry["hashed_bytes"] = nbytes
    if prev and prev.get("sha256") and prev["sha256"] != digest:
        entry["changed_from"] = prev["sha256"]
        m["files"][path] = entry
        return "CHANGED"
    m["files"][path] = entry
    return "ok"


def run(cmd, timeout=20):
    """Best-effort capture of a probe. Never raises. Returns stripped output."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        out = (r.stdout or "") + (r.stderr or "")
        return out.strip()
    except Exception as exc:
        return "<probe failed: %s>" % exc


def run_ok(cmd, timeout=20):
    """Like run(), but returns (output, ok) so a failing probe is never mistaken
    for a version string. A tool that errors out has an UNKNOWN version, not a
    version equal to its error message."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        out = ((r.stdout or "") + (r.stderr or "")).strip()
        return out, r.returncode == 0
    except Exception as exc:
        return "<probe failed: %s>" % exc, False


def probe_tool(name):
    """Try the usual version flags; return the first informative line."""
    path = shutil.which(name)
    if not path:
        return {"found": False}
    attempts = []
    # No --help fallback: a tool whose --help exits 0 would have its usage line
    # ("Usage: mytool [options] <input>") recorded as its version. An unknown
    # version is information; a fabricated one is a defect.
    for flag in ("--version", "-version", "version", "-V"):
        out, ok = run_ok([name, flag])
        if ok and out:
            line = [l for l in out.splitlines() if l.strip()]
            if line:
                return {"found": True, "path": path,
                        "version": line[0][:200], "flag": flag}
        elif out:
            attempts.append("%s: %s" % (flag, out.splitlines()[0][:120]))
    # Binary present but no flag exited 0 — version genuinely unknown. Say so
    # rather than promoting an error message to a version.
    return {"found": True, "path": path, "version": None,
            "version_unknown": True, "failed_probes": attempts[:3]}


def fmt_version(info):
    """Render a probe result for display, distinguishing the three real states:
    absent, present-but-unversionable, and versioned."""
    if not info.get("found"):
        return "NOT FOUND"
    if info.get("version_unknown") or not info.get("version"):
        return "UNKNOWN (present, version probe failed)"
    return info["version"]


def capture_env(probes):
    env = {
        "captured_utc": utcnow(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": sys.version.split()[0],
        "python_executable": sys.executable,
        "cpu_count": os.cpu_count(),
        "cwd": os.getcwd(),
        "conda_env": os.environ.get("CONDA_DEFAULT_ENV"),
    }
    # importlib.metadata, not `pip freeze`: conda-installed packages render as
    # "name @ file:///..." in pip freeze, which loses the version entirely.
    try:
        from importlib import metadata as ilm
        pkgs = set()
        for dist in ilm.distributions():
            name = (dist.metadata or {}).get("Name") or ""
            if name:
                pkgs.add("%s==%s" % (name, dist.version))
        env["packages"] = sorted(pkgs, key=str.lower)
    except Exception as exc:
        env["packages"] = []
        env["packages_error"] = str(exc)
    if shutil.which("conda") and env["conda_env"]:
        ce = run(["conda", "list", "--export"], timeout=180)
        if ce and not ce.startswith("<probe failed"):
            env["conda_export"] = [l for l in ce.splitlines() if l and not l.startswith("#")]
    if shutil.which("R"):
        env["R"] = run(["R", "--version"]).splitlines()[:1]
    env["tools"] = {name: probe_tool(name) for name in (probes or [])}
    return env


def capture_git():
    if not shutil.which("git"):
        return {"available": False}
    head = run(["git", "rev-parse", "HEAD"])
    if head.startswith("<probe failed") or "not a git repository" in head.lower():
        return {"available": False}
    status = run(["git", "status", "--porcelain"])
    return {
        "available": True,
        "commit": head.split()[0] if head else None,
        "branch": run(["git", "rev-parse", "--abbrev-ref", "HEAD"]),
        "dirty": bool(status and not status.startswith("<probe failed")),
        "dirty_files": [l[3:] for l in status.splitlines()][:50] if status else [],
        "remote": run(["git", "config", "--get", "remote.origin.url"]) or None,
    }


def cmd_init(a):
    run_id = a.run_id or time.strftime("run_%Y%m%dT%H%M%SZ", time.gmtime())
    m = {"schema": SCHEMA, "run_id": run_id, "title": a.title,
         "created_utc": utcnow(), "finalized_utc": None,
         "agent": {"model": os.environ.get("PROVENANCE_AGENT_MODEL"),
                   "surface": os.environ.get("PROVENANCE_AGENT_SURFACE")},
         "environment": None, "git": capture_git(), "steps": [], "files": {}}
    save(m, a.dir)
    print("initialised %s (run_id=%s)" % (manifest_path(a.dir), run_id))


def cmd_env(a):
    m = load(a.dir)
    m["environment"] = capture_env(a.probe)
    save(m, a.dir)
    tools = m["environment"]["tools"]
    print("environment captured: python %s, %d packages, %d tools probed"
          % (m["environment"]["python"],
             len(m["environment"].get("packages", [])), len(tools)))
    for name, info in tools.items():
        print("  %-12s %s" % (name, fmt_version(info)))


def cmd_step(a):
    flags = []

    def mutate(m):
        for f in (a.inp or []):
            flags.append((f, record_file(m, f, "input", a.cap_bytes)))
        for f in (a.out or []):
            flags.append((f, record_file(m, f, "output", a.cap_bytes)))
        for f in (a.script or []):
            flags.append((f, record_file(m, f, "script", a.cap_bytes)))
        step = {"n": len(m["steps"]) + 1, "utc": utcnow(), "cmd": redact(a.cmd),
                "inputs": a.inp or [], "outputs": a.out or [],
                "scripts": a.script or [], "note": a.note,
                "deviation": a.deviation, "exit_code": a.exit_code}
        m["steps"].append(step)
        return step

    step = with_lock(a.dir, mutate)
    warn = [f for f, s in flags if s != "ok"]
    print("step %d recorded%s" % (step["n"], ("  [attention: %s]" % ", ".join(
        "%s=%s" % (f, s) for f, s in flags if s != "ok")) if warn else ""))


def cmd_hook(a):
    """Read an agent hook JSON payload on stdin and log the command.

    Exits 0 unconditionally, whatever happens. A hook that raises, blocks or
    writes to stderr disturbs the agent it is supposed to be observing
    invisibly, so every failure here is swallowed on purpose.
    """
    # Installed as a plugin, the hook is on for every session. Let a user keep
    # the skill but turn automatic capture off without uninstalling anything.
    if os.environ.get("PROVENANCE_HOOK", "").strip().lower() in ("0", "off", "false", "no"):
        sys.exit(0)
    try:
        payload = json.load(sys.stdin)
        cmd = (payload.get("tool_input") or {}).get("command")
        if not cmd:
            sys.exit(0)
        # Do not record our own bookkeeping as analysis steps.
        if "provenance.py" in cmd:
            sys.exit(0)
        if is_trivial(cmd) and not os.environ.get("PROVENANCE_LOG_ALL"):
            sys.exit(0)
        # Resolve against the agent's working directory, not this process's,
        # then walk up: the agent may have cd'd below the manifest.
        root = a.dir if a.dir != DEFAULT_DIR else None
        if root is None:
            root = find_manifest_dir(payload.get("cwd") or os.getcwd())
        if not root or not os.path.exists(manifest_path(root)):
            sys.exit(0)          # no active run; stay silent

        safe = redact(cmd)

        def mutate(m):
            # Checked inside the lock so two hooks firing together cannot both
            # pass the check and then both append.
            if is_duplicate_hook(m, safe):
                return
            m["steps"].append(
                {"n": len(m["steps"]) + 1, "utc": utcnow(), "cmd": safe,
                 "inputs": [], "outputs": [], "scripts": [],
                 "note": "auto-captured via agent PostToolUse hook",
                 "deviation": None, "exit_code": None})

        with_lock(root, mutate)
    except SystemExit:
        raise
    except Exception:
        pass
    sys.exit(0)


def cmd_verify(a):
    m = load(a.dir)
    bad = []
    for path, info in sorted(m["files"].items()):
        if not info.get("sha256"):
            bad.append((path, "was missing at record time"))
            continue
        if not os.path.exists(path):
            bad.append((path, "GONE"))
            continue
        # Reuse the cap recorded at capture time, not whatever is on this
        # command line, so a capped hash is compared like with like.
        cap = info.get("hashed_bytes") if info.get("partial_hash") else None
        digest, _, _ = sha256(path, cap)
        if digest != info["sha256"]:
            bad.append((path, "CHANGED since recorded"))
    print("%d files tracked, %d discrepancies" % (len(m["files"]), len(bad)))
    for path, why in bad:
        print("  %-60s %s" % (path, why))
    return 1 if bad else 0


def cmd_finalize(a):
    m = load(a.dir)
    m["finalized_utc"] = utcnow()
    save(m, a.dir)
    env = m.get("environment") or {}
    lines = ["# Provenance: %s" % (m.get("title") or m["run_id"]), ""]
    lines += ["- run_id: `%s`" % m["run_id"],
              "- created: %s" % m["created_utc"],
              "- finalized: %s" % m["finalized_utc"],
              "- platform: %s (%s), %s cores" % (env.get("platform", "?"),
                                                 env.get("machine", "?"),
                                                 env.get("cpu_count", "?")),
              "- python: %s" % env.get("python", "?"),
              "- conda env: %s" % (env.get("conda_env") or "n/a")]
    g = m.get("git") or {}
    if g.get("available"):
        lines.append("- git: `%s` on %s%s" % (g.get("commit", "?")[:12], g.get("branch"),
                                              " (DIRTY working tree)" if g.get("dirty") else ""))
    ag = m.get("agent") or {}
    if ag.get("model") or ag.get("surface"):
        lines.append("- agent: %s on %s" % (ag.get("model") or "?", ag.get("surface") or "?"))
    tools = (env.get("tools") or {})
    if tools:
        lines += ["", "## Software versions", "", "| tool | version | path |", "|---|---|---|"]
        for name, info in sorted(tools.items()):
            lines.append("| %s | %s | %s |" % (name, fmt_version(info),
                                               info.get("path", "-")))
    if env.get("packages"):
        lines += ["", "<details><summary>installed packages (%d)</summary>" % len(env["packages"]),
                  "", "```"] + env["packages"] + ["```", "</details>"]
    if env.get("conda_export"):
        lines += ["", "<details><summary>conda list --export (%d)</summary>" % len(env["conda_export"]),
                  "", "```"] + env["conda_export"] + ["```", "</details>"]
    devs = [s for s in m["steps"] if s.get("deviation")]
    if devs:
        lines += ["", "## Deviations from the intended method", ""]
        for s in devs:
            lines.append("- step %d: %s" % (s["n"], s["deviation"]))
    lines += ["", "## Steps", ""]
    for s in m["steps"]:
        lines.append("### %d. %s" % (s["n"], s["utc"]))
        lines.append("")
        lines.append("```\n%s\n```" % (s.get("cmd") or "(no command recorded)"))
        for label, key in (("inputs", "inputs"), ("outputs", "outputs"), ("scripts", "scripts")):
            if s.get(key):
                lines.append("- %s: %s" % (label, ", ".join("`%s`" % f for f in s[key])))
        if s.get("note"):
            lines.append("- note: %s" % s["note"])
        lines.append("")
    tracked = m.get("files") or {}
    if tracked:
        lines += ["## Files and checksums", "",
                  "| file | role | bytes | sha256 |", "|---|---|---|---|"]
        for path, info in sorted(tracked.items()):
            lines.append("| `%s` | %s | %s | `%s` |" % (
                path, info.get("role"), info.get("bytes", "-"),
                (info.get("sha256") or "MISSING")[:16]))
    out = os.path.join(a.dir or DEFAULT_DIR, "PROVENANCE.md")
    with open(out, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    print("wrote %s (%d steps, %d files, %d deviations)"
          % (out, len(m["steps"]), len(tracked), len(devs)))


def build_parser():
    p = argparse.ArgumentParser(prog="provenance.py", description=__doc__.splitlines()[0])
    p.add_argument("--dir", default=DEFAULT_DIR, help="manifest directory (default: provenance)")
    p.add_argument("--cap-bytes", type=int, default=None,
                   help="hash only the first N bytes of huge files")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("init", help="start a run manifest")
    s.add_argument("--title", required=True)
    s.add_argument("--run-id")
    s.set_defaults(func=cmd_init)

    s = sub.add_parser("env", help="capture interpreter, packages and tool versions")
    s.add_argument("--probe", action="append", help="external tool to version-probe (repeatable)")
    s.set_defaults(func=cmd_env)

    s = sub.add_parser("step", help="record one analysis step")
    s.add_argument("--cmd", required=True)
    s.add_argument("--in", dest="inp", action="append")
    s.add_argument("--out", action="append")
    s.add_argument("--script", action="append")
    s.add_argument("--note")
    s.add_argument("--deviation", help="how this differs from the intended method")
    s.add_argument("--exit-code", type=int)
    s.set_defaults(func=cmd_step)

    s = sub.add_parser("hook", help="log a Claude Code PostToolUse payload from stdin")
    s.set_defaults(func=cmd_hook)

    s = sub.add_parser("verify", help="re-checksum tracked files and report drift")
    s.set_defaults(func=cmd_verify)

    s = sub.add_parser("finalize", help="write PROVENANCE.md")
    s.set_defaults(func=cmd_finalize)
    return p


def main(argv=None):
    a = build_parser().parse_args(argv)
    return a.func(a) or 0


if __name__ == "__main__":
    sys.exit(main())
