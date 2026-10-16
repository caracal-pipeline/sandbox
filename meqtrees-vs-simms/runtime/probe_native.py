#!/usr/bin/env python3
"""Compile the direct profile with a real Timba kernel and optionally predict.

Run inside the selected MeqTrees environment, on a disposable MS copy. Exceptions
are failures, unlike pipeliner versions which catch job exceptions internally.
"""

import argparse
import configparser
import datetime
import hashlib
import importlib.metadata
import json
from pathlib import Path
import sys
import traceback


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument(
        "--script", type=Path, help="Defaults to installed Cattery/Siamese/turbo-sim.py"
    )
    parser.add_argument("--set", action="append", default=[], metavar="OPTION=VALUE")
    parser.add_argument("--threads", type=int, default=1)
    parser.add_argument(
        "--define-only",
        action="store_true",
        help="Resolve Python forest without starting a kernel; does not validate native graph loading",
    )
    parser.add_argument(
        "--predict",
        action="store_true",
        help="Write visibilities into the supplied disposable MS",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.define_only and args.predict:
        parser.error("--define-only cannot predict")
    if args.threads < 1:
        parser.error("--threads must be positive")
    if args.output.exists():
        parser.error(
            "--output must be a fresh directory; existing evidence will not be overwritten"
        )
    args.output.mkdir(parents=True, exist_ok=False)
    report = dict(
        schema_version=1,
        status="blocked",
        compiled=False,
        predicted=False,
        captured_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        python=sys.version,
        executable=sys.executable,
        threads=args.threads,
        profile_sha256=hashlib.sha256(args.profile.read_bytes()).hexdigest(),
        errors=[],
    )
    server = None
    try:
        import Timba.mequtils
        import Cattery

        # turbo-sim imports the top-level historical Meow/Siamese packages.
        cattery_root = Path(Cattery.__file__).resolve().parent
        sys.path.insert(0, str(cattery_root))
        from Timba.Apps import meqserver
        from Timba.TDL import Compile, TDLOptions

        script = args.script or cattery_root / "Siamese" / "turbo-sim.py"
        report["modules"] = {
            "Timba.mequtils": Timba.mequtils.__file__,
            "Cattery": Cattery.__file__,
        }
        report["script"] = {
            "path": str(script),
            "sha256": hashlib.sha256(script.read_bytes()).hexdigest(),
        }
        report["packages"] = sorted(
            [
                {"name": d.metadata["Name"], "version": d.version}
                for d in importlib.metadata.distributions()
            ],
            key=lambda d: d["name"].lower(),
        )
        requested = configparser.ConfigParser(interpolation=None)
        requested.read(args.profile)
        overrides = {}
        for item in args.set:
            name, sep, value = item.partition("=")
            if not name or not sep:
                raise ValueError("--set requires OPTION=VALUE")
            overrides[name] = value
        TDLOptions.enable_save_config(False)
        TDLOptions.config.read(str(args.profile))
        TDLOptions.config.set_save_filename(None)
        TDLOptions.init_options("sim", save=False)
        for name, value in overrides.items():
            TDLOptions.set_option(name, value, save=False, from_str=True)
        if args.define_only:
            # Fresh process has no existing forest; bypass only the unconditional
            # Clear.Forest RPC in Timba's otherwise kernel-optional compiler.
            from Timba.Meq import meqds

            meqds.clear_forest = lambda: None
            report["definition_only_clear_rpc_skipped"] = True
        if not args.define_only:
            server = meqserver.default_mqs(
                wait_init=10, extra=["-mt", str(args.threads)]
            )
        module, ns, message = Compile.compile_file(server, str(script), config=None)
        report["compiled"] = not args.define_only
        report["forest_resolved"] = True
        report["compile_message"] = str(message)
        with (args.output / "effective.tdl").open("w") as stream:
            TDLOptions.dump_options(stream)
        values = []
        for option in TDLOptions.compile_options + TDLOptions.runtime_options:
            option.collect_values(values)
        actual = {name: str(value) for name, value in values}
        report["effective_options"] = actual
        wanted = dict(requested.items("sim"))
        wanted.update(overrides)
        # Capture discrepancies for review: Timba may represent 0/1 as False/True.
        report["requested_options"] = wanted
        registered = {}
        for name, option in TDLOptions._all_options.items():
            try:
                value = option.get_str()
            except AttributeError:
                value = None  # untoggled submenu has no scalar value
            registered[name] = {
                "value": value,
                "visible": option.visible,
                "enabled": option.enabled,
            }
        report["registered_options"] = registered
        report["unregistered_options"] = sorted(set(wanted) - set(registered))
        report["not_serialized_options"] = sorted(set(wanted) - set(actual))
        report["text_differences"] = {
            key: {"requested": value, "effective": actual[key]}
            for key, value in wanted.items()
            if key in actual and value != actual[key]
        }
        if args.predict:
            module._simulate_MS(server, None, wait=True)
            report["predicted"] = True
        report["status"] = (
            "forest_resolved_native_loading_unverified"
            if args.define_only
            else "prediction_returned_requires_output_validation"
            if args.predict
            else "compiled_requires_option_review"
        )
    except Exception:
        report["errors"].append(traceback.format_exc())
        report["status"] = "failed" if server else "blocked"
    finally:
        if server is not None:
            try:
                meqserver.stop_default_mqs()
            except Exception:
                report["errors"].append("kernel cleanup: " + traceback.format_exc())
                report["status"] = "failed"
        (args.output / "probe.json").write_text(json.dumps(report, indent=2) + "\n")
    print(report["status"])
    return 2 if report["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
