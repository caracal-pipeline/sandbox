#!/usr/bin/env python3
"""Capture one engine environment without importing a second engine's Python stack."""

import argparse
import datetime
import hashlib
import importlib.metadata as metadata
import importlib.util
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


def command(argv):
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=30)
        return {"argv": argv, "returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"argv": argv, "error": str(exc)}


def module_info(name):
    try:
        spec = importlib.util.find_spec(name)
        return {"available": spec is not None, "origin": spec.origin if spec else None}
    except (ImportError, ValueError) as exc:
        return {"available": False, "error": str(exc)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", choices=["simms", "meqtrees"], required=True)
    parser.add_argument("--repo", action="append", default=[], metavar="NAME=PATH")
    parser.add_argument("--file", action="append", default=[], metavar="PATH")
    parser.add_argument("--lock", type=Path, help="Source lock used to validate named checkouts")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    lock = json.loads(args.lock.read_text()) if args.lock else {"sources": {}}
    report = {
        "schema_version": 1,
        "captured_at_utc": datetime.datetime.now(datetime.UTC).isoformat(),
        "engine": args.engine,
        "python": {"executable": sys.executable, "version": sys.version},
        "host": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "cpu_count": os.cpu_count(),
            "affinity": sorted(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None,
        },
        "thread_environment": {
            key: os.environ.get(key)
            for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMBA_NUM_THREADS")
        },
        "packages": sorted(
            [{"name": dist.metadata["Name"], "version": dist.version} for dist in metadata.distributions()],
            key=lambda item: item["name"].lower(),
        ),
        "modules": {name: module_info(name) for name in ("simms", "shinobi", "Timba", "Cattery", "casacore")},
        "executables": {
            name: shutil.which(name)
            for name in ("simms", "shinobi", "meqtree-pipeliner.py", "meqserver", "apptainer", "singularity", "docker")
        },
        "repositories": {},
        "files": [],
        "errors": [],
    }
    for item in args.repo:
        name, separator, value = item.partition("=")
        if not separator or not name or not value:
            parser.error("--repo must be NAME=PATH")
        path = str(Path(value).resolve())
        head = command(["git", "-C", path, "rev-parse", "HEAD"])
        status = command(["git", "-C", path, "status", "--porcelain"])
        expected = lock["sources"].get(name, {}).get("commit")
        actual = head.get("stdout", "").strip()
        clean = status.get("returncode") == 0 and not status.get("stdout")
        report["repositories"][name] = {
            "path": path,
            "head": actual,
            "expected": expected,
            "clean": clean,
            "status": status,
            "head_command": head,
        }
        if head.get("returncode") != 0 or not clean or (expected and actual != expected):
            report["errors"].append(f"{name}: checkout missing, dirty, or mismatched")
        if name == "simms" and args.engine == "simms":
            origin = report["modules"]["simms"].get("origin")
            if not origin or not Path(origin).resolve().is_relative_to(Path(path) / "src" / "simms"):
                report["errors"].append("installed simms does not come from the supplied checkout")
    if args.lock:
        required = ("simms",) if args.engine == "simms" else ("cattery", "timba")
        for name in required:
            if name not in report["repositories"]:
                report["errors"].append(f"--lock requires --repo {name}=PATH")
    for value in args.file:
        path = Path(value)
        digest = hashlib.sha256()
        try:
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
            report["files"].append({"path": str(path.resolve()), "sha256": digest.hexdigest()})
        except OSError as exc:
            report["errors"].append(str(exc))
    modules = ("simms", "shinobi", "casacore") if args.engine == "simms" else ("Timba", "Cattery", "casacore")
    executable = "simms" if args.engine == "simms" else "meqtree-pipeliner.py"
    for name in modules:
        if not report["modules"][name]["available"]:
            report["errors"].append(f"module {name} unavailable")
    if not report["executables"][executable]:
        report["errors"].append(f"executable {executable} unavailable")
    imports = (
        "import simms, shinobi, casacore.tables"
        if args.engine == "simms"
        else "import Timba.mequtils, Cattery, casacore.tables"
    )
    report["import_probe"] = command([sys.executable, "-c", imports])
    if report["import_probe"].get("returncode") != 0:
        report["errors"].append("native import probe failed")
    if report["executables"][executable]:
        argv = [report["executables"][executable]]
        if args.engine == "simms":
            argv += ["skysim"]
        report["help_probe"] = command([*argv, "--help"])
        if report["help_probe"].get("returncode") != 0:
            report["errors"].append("CLI help probe failed")
    # A successful import/help check does not establish graph compilation or prediction.
    report["readiness"] = "imports_and_help_passed_prediction_unverified" if not report["errors"] else "blocked"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(f"{report['readiness']}: {args.output}")
    return 2 if report["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
