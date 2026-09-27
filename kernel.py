"""Kernel helpers for provenance-log. Shells out to scripts/provenance.py."""
import os
import subprocess
import sys


def prov_script_path():
    """Absolute path to the bundled CLI, resolved from this file's location."""
    here = os.path.dirname(sys._getframe().f_code.co_filename)
    if not here:
        raise RuntimeError("skill dir unavailable in this runtime; call the CLI by path")
    return os.path.join(here, "scripts", "provenance.py")


def prov_call(args, root=None):
    """Run a provenance.py subcommand; print its output, return its exit code."""
    cmd = [sys.executable, prov_script_path()]
    if root:
        cmd += ["--dir", root]
    cmd += [str(a) for a in args]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.stdout.strip():
        print(r.stdout.strip())
    if r.returncode not in (0, 1):
        raise RuntimeError(r.stderr.strip() or "provenance.py failed")
    return r.returncode


def prov_agent_tag(model=None, surface=None):
    """Stamp which agent/model produced this run into the manifest environment."""
    if model:
        os.environ["PROVENANCE_AGENT_MODEL"] = str(model)
    if surface:
        os.environ["PROVENANCE_AGENT_SURFACE"] = str(surface)
    return {"model": os.environ.get("PROVENANCE_AGENT_MODEL"),
            "surface": os.environ.get("PROVENANCE_AGENT_SURFACE")}


def prov_init(title, run_id=None, root=None):
    args = ["init", "--title", title]
    if run_id:
        args += ["--run-id", run_id]
    return prov_call(args, root)


def prov_env(probes=None, root=None):
    args = ["env"]
    for p in (probes or []):
        args += ["--probe", p]
    return prov_call(args, root)


def prov_step(cmd, inputs=None, outputs=None, scripts=None, note=None,
              deviation=None, exit_code=None, root=None):
    args = ["step", "--cmd", cmd]
    for f in (inputs or []):
        args += ["--in", f]
    for f in (outputs or []):
        args += ["--out", f]
    for f in (scripts or []):
        args += ["--script", f]
    if note:
        args += ["--note", note]
    if deviation:
        args += ["--deviation", deviation]
    if exit_code is not None:
        args += ["--exit-code", exit_code]
    return prov_call(args, root)


def prov_finalize(root=None):
    return prov_call(["finalize"], root)


def prov_verify(root=None):
    """Re-checksum tracked files. Returns 1 if anything drifted."""
    return prov_call(["verify"], root)
