#!/usr/bin/env python3
"""Exercise pinned simms and original Cattery readers, without a Timba kernel.

This is a reader-level compatibility probe, not visibility equivalence.
Run with the simms interpreter plus astro-kittens installed.
"""

import argparse
import contextlib
import importlib.util
import io
import json
import tempfile
from pathlib import Path

import numpy as np
from astropy.io import fits

from simms.skymodel.beams import FitsBeamProvider, load_cattery_beam_json


def load_file(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    with contextlib.redirect_stdout(io.StringIO()):
        spec.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cattery", type=Path, required=True)
    parser.add_argument("--mkpsim", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    oms = args.cattery / "Cattery/Siamese/OMS"
    original = load_file(oms / "InterpolatedBeams.py", "original_interpolated_beams")
    utils = load_file(oms / "Utils.py", "original_beam_utils")
    result = {"scope": "reader-level only; no Timba kernel or MS prediction", "checks": {}}
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        header = fits.Header()
        for axis, (ctype, crval, delta, unit, refpix) in enumerate(
            [
                ("px", 0, 1, "deg", 3),
                ("py", 0, 1, "deg", 3),
                ("FREQ", 1.3e9, 1e8, "Hz", 1),
            ],
            1,
        ):
            for key, value in {"CTYPE": ctype, "CRVAL": crval, "CDELT": delta, "CUNIT": unit, "CRPIX": refpix}.items():
                header[f"{key}{axis}"] = value
        # Asymmetric affine complex data: linear interpolation has an exact reference.
        ff, mm, ll = np.meshgrid(np.arange(2), np.arange(-2, 3), np.arange(-2, 3), indexing="ij")
        base = 2 + 0.1 * ll + 0.2 * mm + 0.3 * ff + 1j * (0.4 + 0.03 * ll - 0.02 * mm)
        for index, corr in enumerate(("xx", "xy", "yx", "yy")):
            values = (index + 1) * base
            for part, data in (("re", values.real), ("im", values.imag)):
                fits.writeto(root / f"beam_{corr}_{part}.fits", data, header)
        provider = FitsBeamProvider.from_cattery(str(root / "beam"), l_axis="X", m_axis="Y")
        vb = original.LMVoltageBeam(spline_order=1, l_axis="px", m_axis="py")
        vb.read(str(root / "beam_xx_re.fits"), str(root / "beam_xx_im.fits"))
        ell, m = np.radians([0.25, -0.7]), np.radians([0.4, 0.3])
        frequency = np.array([1.32e9])
        expected = 2 + 0.1 * np.degrees(ell) + 0.2 * np.degrees(m) + 0.3 * 0.2
        expected = expected + 1j * (0.4 + 0.03 * np.degrees(ell) - 0.02 * np.degrees(m))
        simms = provider.jones(ell, m, frequency, [0])[0, :, 0, 0, 0]
        cattery = vb.interpolate(ell, m, freq=frequency)
        np.testing.assert_allclose(simms, expected, atol=1e-12, rtol=0)
        np.testing.assert_allclose(cattery, expected, atol=1e-12, rtol=0)
        result["checks"]["in_support_order1"] = {
            "passed": True,
            "max_abs_difference": float(np.max(abs(simms - cattery))),
        }
        # Distinct XY/YX amplitudes check the loader's matrix element ordering.
        matrix = provider.jones(ell[:1], m[:1], frequency, [0])[0, 0, 0]
        np.testing.assert_allclose(matrix, expected[0] * np.array([[1, 2], [3, 4]]), atol=1e-12, rtol=0)
        result["checks"]["jones_order_and_unnormalized_amplitude"] = {"passed": True}
        outside = np.radians([3.0])
        sim_oob = provider.jones(outside, [0], frequency, [0])[0, 0, 0, 0, 0]
        cat_oob = vb.interpolate(outside, [0], freq=frequency)[0]
        assert sim_oob == 0 and abs(cat_oob) > 0
        result["checks"]["spatial_boundary_differs"] = {
            "passed": True,
            "simms_abs": float(abs(sim_oob)),
            "cattery_abs": float(abs(cat_oob)),
        }
        sim_freq = provider.jones(ell[:1], m[:1], [1.5e9], [0])[0, 0, 0, 0, 0]
        cat_freq = vb.interpolate(ell[:1], m[:1], freq=[1.5e9])[0]
        assert sim_freq == 0 and abs(cat_freq) > 0
        result["checks"]["frequency_boundary_differs"] = {
            "passed": True,
            "simms_abs": float(abs(sim_freq)),
            "cattery_abs": float(abs(cat_freq)),
        }
        native = args.mkpsim / "src/mkpsim/configs/stationspec_hetero.json"
        station_names = ["m000", "e017"]
        with contextlib.redirect_stdout(io.StringIO()):
            mapping = utils.json_beamconfig_reader(str(native), station_names)
        assert mapping.get_stationtype("e017") == "mkp"
        assert mapping.get_beamsets("m000") != mapping.get_beamsets("e017")
        try:
            load_cattery_beam_json(native)
        except ValueError as exc:
            result["checks"]["native_json_incompatible"] = {
                "passed": True,
                "simms_error": str(exc),
                "cattery_patterns": {name: mapping.get_beamsets(name) for name in station_names},
            }
        else:
            raise AssertionError("Pinned simms unexpectedly accepted native mkpsim JSON; update audit")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(f"{len(result['checks'])} reader checks passed: {args.output}")


if __name__ == "__main__":
    main()
