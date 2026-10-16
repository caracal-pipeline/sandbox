#!/usr/bin/env python3
"""Build shared diagnostic inputs; refuse to overwrite an existing bundle."""

import argparse
import hashlib
import importlib.metadata
import itertools
import json
from pathlib import Path
import subprocess

import numpy as np
import yaml
from astropy.io import fits
from astropy.time import Time
from casacore.measures import measures
from casacore.quanta import quantity
from casacore.tables import (
    default_ms,
    makearrcoldesc,
    makescacoldesc,
    maketabdesc,
    table,
)
from simms import SCHEMADIR

from fixture_integrity import snapshot_ms


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def json_write(path, data):
    Path(path).write_text(json.dumps(data, indent=2) + "\n")


def uvw_from_measures(positions, ant1, ant2, times, direction):
    """J2000 UVW from actual UTC epochs, using ECEF vector POSITION[q]-POSITION[p]."""
    dm = measures()
    centre = positions.mean(axis=0)
    dm.doframe(dm.position("itrf", *[quantity(float(x), "m") for x in centre]))
    dm.doframe(dm.direction("J2000", *[quantity(float(x), "rad") for x in direction]))
    result = np.empty((len(times), 3))
    for timestamp in np.unique(times):
        dm.doframe(dm.epoch("utc", quantity(float(timestamp / 86400), "d")))
        for row in np.flatnonzero(times == timestamp):
            delta = positions[ant2[row]] - positions[ant1[row]]
            baseline = dm.baseline("itrf", *[quantity(float(x), "m") for x in delta])
            result[row] = dm.to_uvw(baseline)["xyz"].get_value("m")
    return result


def write_rows(ms, name, values):
    print(f"Writing {name}", flush=True)
    with table(str(ms / name), readonly=False, ack=False) as tab:
        size = len(next(iter(values.values())))
        tab.addrows(size)
        for key, value in values.items():
            value = np.asarray(value)
            if value.dtype.kind in "US":
                if value.ndim == 1:
                    tab.putcol(key, value.tolist())
                else:
                    for row, cell in enumerate(value):
                        tab.putcell(key, row, cell.tolist())
            else:
                tab.putcol(key, value)


def create_ms(path, antennas, timestamps, frequencies, direction):
    count = len(antennas)
    positions = np.array([ant["position_m"] for ant in antennas])
    pairs = np.array(list(itertools.combinations(range(count), 2)))
    ant1, ant2 = np.tile(pairs, (len(timestamps), 1)).T
    times = np.repeat(timestamps, len(pairs))
    rows, channels = len(times), len(frequencies)
    desc = maketabdesc(
        [
            makearrcoldesc(key, 0j, ndim=2, shape=[channels, 4], valuetype="complex")
            for key in ("DATA", "MODEL_DATA", "CORRECTED_DATA")
        ]
    )
    with default_ms(str(path), desc) as main:
        main.addrows(rows)
        zero_ids = [
            "ARRAY_ID",
            "DATA_DESC_ID",
            "FEED1",
            "FEED2",
            "FIELD_ID",
            "OBSERVATION_ID",
            "PROCESSOR_ID",
        ]
        for key in zero_ids:
            main.putcol(key, np.zeros(rows, dtype=np.int32))
        main.putcol("STATE_ID", np.full(rows, -1, dtype=np.int32))
        main.putcol("SCAN_NUMBER", np.ones(rows, dtype=np.int32))
        for key in ("TIME", "TIME_CENTROID"):
            main.putcol(key, times)
        for key in ("INTERVAL", "EXPOSURE"):
            main.putcol(key, np.full(rows, 4.0))
        main.putcol("ANTENNA1", ant1)
        main.putcol("ANTENNA2", ant2)
        main.putcol("UVW", uvw_from_measures(positions, ant1, ant2, times, direction))
        main.putcol("FLAG", np.zeros((rows, channels, 4), bool))
        main.putcol("FLAG_ROW", np.zeros(rows, bool))
        # python-casacore/dask-ms expose this column as (row, flagcat, chan, corr).
        main.putcol("FLAG_CATEGORY", np.zeros((rows, 1, channels, 4), bool))
        main.putcolkeyword("FLAG_CATEGORY", "CATEGORY", ["DIAGNOSTIC"])
        for key in ("WEIGHT", "SIGMA"):
            main.putcol(key, np.ones((rows, 4), np.float32))
        for key in ("DATA", "MODEL_DATA", "CORRECTED_DATA"):
            main.putcol(key, np.zeros((rows, channels, 4), np.complex64))
    write_rows(
        path,
        "ANTENNA",
        {
            "NAME": [a["name"] for a in antennas],
            "STATION": [a["name"] for a in antennas],
            "POSITION": positions,
            "OFFSET": np.zeros((count, 3)),
            "MOUNT": ["ALT-AZ"] * count,
            "TYPE": ["GROUND-BASED"] * count,
            "DISH_DIAMETER": [a["diameter_m"] for a in antennas],
            "FLAG_ROW": np.zeros(count, bool),
        },
    )
    with table(str(path / "ANTENNA"), readonly=False, ack=False) as tab:
        tab.addcols(maketabdesc(makescacoldesc("TELESCOPE_NAME", "")))
        tab.putcol("TELESCOPE_NAME", [a["beam_type"] for a in antennas])
    write_rows(
        path,
        "FEED",
        {
            "ANTENNA_ID": np.arange(count),
            "BEAM_ID": [-1] * count,
            "FEED_ID": [0] * count,
            "SPECTRAL_WINDOW_ID": [-1] * count,
            "NUM_RECEPTORS": [2] * count,
            "TIME": [float(timestamps[0])] * count,
            "INTERVAL": [1e30] * count,
            "POSITION": np.zeros((count, 3)),
            "BEAM_OFFSET": np.zeros((count, 2, 2)),
            "POLARIZATION_TYPE": [["X", "Y"]] * count,
            "POL_RESPONSE": np.tile(np.eye(2, dtype=complex), (count, 1, 1)),
            "RECEPTOR_ANGLE": [[0.0, np.pi / 2]] * count,
        },
    )
    directions = np.array(direction).reshape(1, 1, 2)
    write_rows(
        path,
        "FIELD",
        {
            "NAME": ["DIAGNOSTIC"],
            "CODE": [""],
            "TIME": [timestamps[0]],
            "NUM_POLY": [0],
            "SOURCE_ID": [-1],
            "FLAG_ROW": [False],
            **{key: directions for key in ("DELAY_DIR", "PHASE_DIR", "REFERENCE_DIR")},
        },
    )
    npoint = count * len(timestamps)
    write_rows(
        path,
        "POINTING",
        {
            "ANTENNA_ID": np.tile(np.arange(count), len(timestamps)),
            "TIME": np.repeat(timestamps, count),
            "TIME_ORIGIN": [timestamps[0]] * npoint,
            "INTERVAL": [4.0] * npoint,
            "NAME": ["DIAGNOSTIC"] * npoint,
            "NUM_POLY": [0] * npoint,
            "TRACKING": [True] * npoint,
            "DIRECTION": np.tile(directions, (npoint, 1, 1)),
            "TARGET": np.tile(directions, (npoint, 1, 1)),
        },
    )
    write_rows(
        path,
        "POLARIZATION",
        {
            "NUM_CORR": [4],
            "CORR_TYPE": [[9, 10, 11, 12]],
            "CORR_PRODUCT": [[[0, 0], [0, 1], [1, 0], [1, 1]]],
            "FLAG_ROW": [False],
        },
    )
    write_rows(
        path,
        "SPECTRAL_WINDOW",
        {
            "NUM_CHAN": [channels],
            "CHAN_FREQ": [frequencies],
            "REF_FREQUENCY": [frequencies[0]],
            **{
                key: [np.full(channels, 2e6)]
                for key in ("CHAN_WIDTH", "EFFECTIVE_BW", "RESOLUTION")
            },
            "MEAS_FREQ_REF": [5],
            "TOTAL_BANDWIDTH": [channels * 2e6],
            "NET_SIDEBAND": [1],
            "FLAG_ROW": [False],
            "FREQ_GROUP": [0],
            "FREQ_GROUP_NAME": ["DIAGNOSTIC"],
            "IF_CONV_CHAIN": [0],
            "NAME": ["DIAGNOSTIC"],
        },
    )
    write_rows(
        path,
        "DATA_DESCRIPTION",
        {"SPECTRAL_WINDOW_ID": [0], "POLARIZATION_ID": [0], "FLAG_ROW": [False]},
    )
    write_rows(
        path,
        "OBSERVATION",
        {
            "TELESCOPE_NAME": ["MeerKAT"],
            "OBSERVER": ["benchmark fixture"],
            "PROJECT": ["meqtrees-vs-simms"],
            "TIME_RANGE": [[timestamps[0] - 2, timestamps[-1] + 2]],
            "RELEASE_DATE": [timestamps[-1]],
            "FLAG_ROW": [False],
            "LOG": [["synthetic diagnostic"]],
            "SCHEDULE": [[""]],
            "SCHEDULE_TYPE": [""],
        },
    )
    write_rows(
        path,
        "PROCESSOR",
        {
            "TYPE": ["CORRELATOR"],
            "SUB_TYPE": ["DIAGNOSTIC"],
            "TYPE_ID": [0],
            "MODE_ID": [0],
            "FLAG_ROW": [False],
        },
    )


def write_beams(root):
    axis = np.linspace(-2.5, 2.5, 65)
    freqs = np.linspace(1.298e9, 1.306e9, 9)
    ff, yy, xx = np.meshgrid(freqs / 1.3e9, axis, axis, indexing="ij")
    header = fits.Header()
    for idx, (ctype, ref, pix, step, unit) in enumerate(
        [
            ("px", 0, 33, axis[1] - axis[0], "deg"),
            ("py", 0, 33, axis[1] - axis[0], "deg"),
            ("FREQ", freqs[0], 1, freqs[1] - freqs[0], "Hz"),
        ],
        1,
    ):
        for key, value in {
            "CTYPE": ctype,
            "CRVAL": ref,
            "CRPIX": pix,
            "CDELT": step,
            "CUNIT": unit,
        }.items():
            header[f"{key}{idx}"] = value
    norms = {}
    for kind in ("MKAT", "EXT", "UNITY"):
        width = 1.1 if kind == "MKAT" else 0.9
        ex = np.exp(-((xx - 0.03) ** 2 + 1.3 * yy**2) * ff**2 / width**2) * np.exp(
            0.04j * xx
        )
        ey = (
            0.94
            * np.exp(-(0.8 * xx**2 + (yy + 0.02) ** 2) * ff**2 / width**2)
            * np.exp(-0.06j * yy)
        )
        xy = 0.025 * (xx + 1j * yy) * ex
        yx = -0.018 * (yy + 0.7j * xx) * ey
        values = (
            [ex, xy, yx, ey]
            if kind != "UNITY"
            else [
                np.ones_like(ex),
                np.zeros_like(ex),
                np.zeros_like(ex),
                np.ones_like(ex),
            ]
        )
        # Norm calculated on the exact float32 FITS values consumed by Cattery.
        values = [
            v.real.astype("f4").astype("f8") + 1j * v.imag.astype("f4").astype("f8")
            for v in values
        ]
        norm = float(np.sqrt(np.max(sum(abs(v) ** 2 for v in values)) / 2))
        norms[kind] = norm
        for directory, factor in (("raw", 1.0), ("normalized", norm)):
            dest = root / "beams" / directory
            dest.mkdir(parents=True, exist_ok=True)
            for corr, voltage in zip(("xx", "xy", "yx", "yy"), values, strict=True):
                for part, data in (("re", voltage.real), ("im", voltage.imag)):
                    fits.writeto(
                        dest / f"{kind}_{corr}_{part}.fits", data / factor, header
                    )
    return norms


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mkpsim-source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.output.resolve()
    if root.exists() or args.output.is_symlink():
        parser.error("output already exists; choose a new path (no overwrite)")
    lock = json.loads(
        (Path(__file__).parents[1] / "audit/source-lock.json").read_text()
    )
    source = args.mkpsim_source.resolve()
    commit = subprocess.check_output(
        ["git", "-C", str(source), "rev-parse", "HEAD"], text=True
    ).strip()
    dirty = subprocess.check_output(
        ["git", "-C", str(source), "status", "--porcelain"], text=True
    )
    if commit != lock["sources"]["mkpsim"]["commit"] or dirty:
        parser.error("mkpsim source must match the clean pinned checkout")
    simms_source = Path(SCHEMADIR).resolve().parents[2]
    simms_commit = subprocess.check_output(
        ["git", "-C", str(simms_source), "rev-parse", "HEAD"], text=True
    ).strip()
    simms_dirty = subprocess.check_output(
        ["git", "-C", str(simms_source), "status", "--porcelain"], text=True
    )
    if simms_commit != lock["sources"]["simms"]["commit"] or simms_dirty:
        parser.error("installed simms must come from the clean pinned checkout")
    layout = source / "src/mkpsim/configs/meerkat_plus.itrf.txt"
    entries = [
        line.split()
        for line in layout.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]
    names = ["m000", "m001", "e017", "e026"]
    antennas = []
    for name in names:
        row = next(row for row in entries if row[5] == name)
        antennas.append(
            {
                "name": name,
                "position_m": list(map(float, row[:3])),
                "diameter_m": float(row[3]),
                "beam_type": "EXT" if name.startswith("e") else "MKAT",
            }
        )
    direction = [0.0, -np.pi / 6]
    times = Time("2026-01-15T20:00:00", scale="utc").mjd * 86400 + np.arange(3) * 300.0
    frequencies = np.array([1.3e9, 1.302e9, 1.304e9])
    root.mkdir(parents=True)
    create_ms(root / "empty.ms", antennas, times, frequencies, direction)
    norms = write_beams(root)
    # Canonical, unpolarized point sources with flat spectra. Separate polarized tests come later.
    sky = [
        {
            "name": name,
            "ra_rad": float(ra),
            "dec_rad": float(dec),
            "i": intensity,
            "q": 0,
            "u": 0,
            "v": 0,
        }
        for name, ra, dec, intensity in [
            ("centre", 0, direction[1], 1.0),
            ("east", np.radians(0.35), np.radians(-29.8), 0.7),
            ("southwest", np.radians(-0.55) % (2 * np.pi), np.radians(-30.4), 0.3),
        ]
    ]
    json_write(root / "sky.json", sky)
    (root / "sky.txt").write_text(
        "#format: name ra_rad dec_rad i q u v\n"
        + "".join(
            " ".join(
                str(s[key]) for key in ("name", "ra_rad", "dec_rad", "i", "q", "u", "v")
            )
            + "\n"
            for s in sky
        )
    )
    schema = yaml.safe_load((Path(SCHEMADIR) / "source_schema.yaml").read_text())
    for key, alias, units in [("ra", "ra_rad", "rad"), ("dec", "dec_rad", "rad")]:
        schema["parameters"][key].update(alias=alias, units=units)
    for key, alias in [
        ("stokes_i", "i"),
        ("stokes_q", "q"),
        ("stokes_u", "u"),
        ("stokes_v", "v"),
    ]:
        schema["parameters"][key]["alias"] = alias
    (root / "simms-schema.yaml").write_text(yaml.safe_dump(schema, sort_keys=False))
    for mode in ("hetero", "homo", "unity"):
        mapping = {
            a["name"]: (
                a["beam_type"]
                if mode == "hetero"
                else "MKAT"
                if mode == "homo"
                else "UNITY"
            )
            for a in antennas
        }
        patterns = {
            kind: str(root / "beams/raw" / f"{kind}_$(corr)_$(reim).fits")
            for kind in sorted(set(mapping.values()))
        }
        patterns["cmd::default"] = patterns[next(iter(sorted(set(mapping.values()))))]
        json_write(
            root / f"meqtrees-{mode}.json",
            {"diagnostic": {"patterns": patterns, "define-stationtypes": mapping}},
        )
        config = {
            label: {
                "cattery": str(
                    root / "beams/normalized" / f"{mapping[name]}_$(corr)_$(reim).fits"
                ),
                "pol_basis": "linear",
                "l_axis": "X",
                "m_axis": "Y",
            }
            for name, label in [(a["name"], a["beam_type"]) for a in antennas]
        }
        (root / f"simms-{mode}.yaml").write_text(yaml.safe_dump(config, sort_keys=True))
    files = {
        str(p.relative_to(root)): sha256(p)
        for p in sorted(root.rglob("*"))
        if p.is_file() and "empty.ms" not in p.parts
    }
    manifest = {
        "schema_version": 1,
        "status": "complete",
        "kind": "synthetic diagnostic, not scientific holography",
        "mkpsim_commit": commit,
        "simms_commit": simms_commit,
        "builder_sha256": sha256(__file__),
        "source_lock_sha256": sha256(
            Path(__file__).parents[1] / "audit/source-lock.json"
        ),
        "layout_sha256": sha256(layout),
        "antennas": antennas,
        "times_mjd_seconds": times.tolist(),
        "frequencies_hz": frequencies.tolist(),
        "phase_pointing_rad": direction,
        "uvw_method": "casacore J2000 to_uvw(POSITION[ANTENNA2]-POSITION[ANTENNA1]) at each actual TIME",
        "rows": 18,
        "correlations": [9, 10, 11, 12],
        "normalization": norms,
        "files_sha256": files,
        "empty_ms": snapshot_ms(root / "empty.ms"),
        "time_spacing_seconds": 300,
        "exposure_seconds": 4,
        "packages": {
            name: importlib.metadata.version(name)
            for name in ["simms", "numpy", "astropy", "python-casacore"]
        },
    }
    json_write(root / "manifest.json", manifest)
    print(root)


if __name__ == "__main__":
    main()
