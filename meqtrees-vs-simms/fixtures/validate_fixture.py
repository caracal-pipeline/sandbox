#!/usr/bin/env python3
"""Verify a complete shared fixture before either simulator receives an MS copy."""

import argparse
import hashlib
import itertools
import json
from pathlib import Path

import numpy as np
import yaml
from astropy.io import fits
from casacore.tables import table
from simms.skymodel.ascii_skies import ASCIISkymodel
from simms.skymodel.beams import resolve_antenna_beams

from fixture_integrity import TABLES, snapshot_ms


def validate(root):
    root = Path(root).resolve()
    manifest = json.loads((root / "manifest.json").read_text())
    if manifest["status"] != "complete":
        raise ValueError("fixture is incomplete")
    for relative, digest in manifest["files_sha256"].items():
        path = (root / relative).resolve()
        if (
            not path.is_relative_to(root)
            or hashlib.sha256(path.read_bytes()).hexdigest() != digest
        ):
            raise ValueError(f"file checksum mismatch: {relative}")
    snapshot = snapshot_ms(root / "empty.ms")
    if snapshot != manifest["empty_ms"]:
        raise ValueError("common MS has changed")
    with table(str(root / "empty.ms"), ack=False) as main:
        if main.getkeyword("MS_VERSION") != 2.0:
            raise ValueError("MS_VERSION must be 2.0")
        for name in TABLES[1:]:
            link = main.getkeyword(name)
            if not isinstance(link, str) or not link.startswith("Table: "):
                raise ValueError(f"invalid subtable link: {name}")
            if Path(link.removeprefix("Table: ")).resolve() != root / "empty.ms" / name:
                raise ValueError(f"subtable link leaves common MS: {name}")
        times, a1, a2, uvw = [
            main.getcol(key) for key in ("TIME", "ANTENNA1", "ANTENNA2", "UVW")
        ]
        expected_pairs = set(itertools.combinations(range(4), 2))
        for timestamp in np.unique(times):
            selected = times == timestamp
            if (
                set(zip(a1[selected].tolist(), a2[selected].tolist(), strict=True))
                != expected_pairs
                or sum(selected) != 6
            ):
                raise ValueError("baseline coverage is incomplete or duplicated")
            lookup = {
                (p, q): value
                for p, q, value in zip(
                    a1[selected], a2[selected], uvw[selected], strict=True
                )
            }
            np.testing.assert_allclose(
                lookup[(0, 1)] + lookup[(1, 2)], lookup[(0, 2)], atol=1e-8
            )
        np.testing.assert_array_equal(
            times, np.repeat(manifest["times_mjd_seconds"], 6)
        )
        for key in ("DATA", "MODEL_DATA", "CORRECTED_DATA"):
            if np.any(main.getcol(key)):
                raise ValueError(f"common {key} must be zero before prediction")
        if np.any(main.getcol("FLAG")) or np.any(main.getcol("FLAG_ROW")):
            raise ValueError("diagnostic fixture unexpectedly flagged")
    with table(str(root / "empty.ms/POLARIZATION"), ack=False) as pol:
        np.testing.assert_array_equal(pol.getcell("CORR_TYPE", 0), [9, 10, 11, 12])
    with table(str(root / "empty.ms/ANTENNA"), ack=False) as ant:
        labels, mounts = ant.getcol("TELESCOPE_NAME"), ant.getcol("MOUNT")
        np.testing.assert_array_equal(
            ant.getcol("NAME"), [a["name"] for a in manifest["antennas"]]
        )
    # Assert each YAML mode resolves both type labels and all four matrix entries.
    for mode in ("hetero", "homo", "unity"):
        config = yaml.safe_load((root / f"simms-{mode}.yaml").read_text())
        assigned, providers, rotating = resolve_antenna_beams(labels, mounts, config)
        if not np.all(rotating) or not all(p.has_leakage for p in providers):
            raise ValueError("full-Jones alt-az beams required")
        if mode == "homo":
            np.testing.assert_array_equal(
                providers[0].jones([0.001], [0.002], [1.3e9], [0]),
                providers[1].jones([0.001], [0.002], [1.3e9], [0]),
            )
        if mode == "unity":
            for provider in providers:
                np.testing.assert_allclose(
                    provider.jones([0.001], [0.002], [1.3e9], [0])[0, 0, 0], np.eye(2)
                )
        mapping = json.loads((root / f"meqtrees-{mode}.json").read_text())[
            "diagnostic"
        ]["define-stationtypes"]
        for antenna in manifest["antennas"]:
            expected = (
                antenna["beam_type"]
                if mode == "hetero"
                else "MKAT"
                if mode == "homo"
                else "UNITY"
            )
            if mapping[antenna["name"]] != expected:
                raise ValueError("station assignment changed")
    # Validate the exact FITS normalization against raw, on-disk voltages.
    for kind, expected_norm in manifest["normalization"].items():
        raw = [
            fits.getdata(root / f"beams/raw/{kind}_{corr}_re.fits")
            + 1j * fits.getdata(root / f"beams/raw/{kind}_{corr}_im.fits")
            for corr in ("xx", "xy", "yx", "yy")
        ]
        norm = float(np.sqrt(np.max(sum(abs(v) ** 2 for v in raw)) / 2))
        np.testing.assert_allclose(norm, expected_norm, atol=1e-14)
        for corr, voltage in zip(("xx", "xy", "yx", "yy"), raw, strict=True):
            normalized = fits.getdata(
                root / f"beams/normalized/{kind}_{corr}_re.fits"
            ) + 1j * fits.getdata(root / f"beams/normalized/{kind}_{corr}_im.fits")
            np.testing.assert_allclose(
                normalized, voltage / norm, rtol=1e-14, atol=1e-14
            )
    model = ASCIISkymodel(
        str(root / "sky.txt"), source_schema_file=str(root / "simms-schema.yaml")
    )
    sky = json.loads((root / "sky.json").read_text())
    for parsed, canonical in zip(model.sources, sky, strict=True):
        for key, native in (("ra_rad", "ra"), ("dec_rad", "dec"), ("i", "stokes_i")):
            np.testing.assert_allclose(
                parsed.value_or_default(native), canonical[key], rtol=0, atol=1e-14
            )
    return {
        "status": "passed",
        "rows": len(times),
        "channels": 3,
        "correlations": 4,
        "sources": len(sky),
        "empty_ms_sha256": snapshot["sha256"],
        "checks": [
            "file hashes",
            "MS contents",
            "cross-baseline coverage/closure",
            "unflagged zero inputs",
            "correlation order",
            "beam mappings",
            "voltage normalization",
            "catalogue parsing",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.resolve().is_relative_to(args.fixture.resolve()):
        parser.error("validation report must be outside the immutable fixture")
    if args.output.exists() or args.output.is_symlink():
        parser.error("validation report already exists; choose a new output path")
    result = validate(args.fixture)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
