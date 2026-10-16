#!/usr/bin/env python3
"""Independent bundle contract checks: python test_fixture.py BUNDLE [unittest flags]."""

import hashlib
import itertools
import json
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import shutil
import sys
import tempfile
import unittest

import numpy as np
from astropy.io import fits
from casacore.measures import measures
from casacore.quanta import quantity
from casacore.tables import table
from daskms import xds_from_ms
from simms.skymodel.ascii_skies import ASCIISkymodel
from simms.skymodel.beams import (
    load_beam_config,
    resolve_antenna_beams,
    read_pointing_centre,
)

from validate_fixture import validate


ROOT = Path(sys.argv.pop(1)).resolve() if len(sys.argv) > 1 else None


class FixtureContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if ROOT is None or not (ROOT / "manifest.json").is_file():
            raise RuntimeError("Pass a complete generated fixture directory")
        cls.manifest = json.loads((ROOT / "manifest.json").read_text())
        cls.ms = ROOT / "empty.ms"

    def columns(self, subtable, *names):
        path = self.ms / subtable if subtable else self.ms
        with table(str(path), ack=False) as tab:
            return [tab.getcol(name) for name in names]

    def test_uvws_close_and_preserve_baseline_lengths(self):
        (positions,) = self.columns("ANTENNA", "POSITION")
        times, ant1, ant2, uvw = self.columns("", "TIME", "ANTENNA1", "ANTENNA2", "UVW")
        self.assertTrue(np.isfinite(uvw).all())
        np.testing.assert_allclose(
            np.linalg.norm(uvw, axis=1),
            np.linalg.norm(positions[ant2] - positions[ant1], axis=1),
            atol=1e-6,
            rtol=1e-10,
        )
        expected_pairs = set(itertools.combinations(range(len(positions)), 2))
        for epoch in np.unique(times):
            selected = times == epoch
            baseline = dict(zip(zip(ant1[selected], ant2[selected]), uvw[selected]))
            self.assertEqual(set(baseline), expected_pairs)
            for p, q, r in itertools.combinations(range(len(positions)), 3):
                np.testing.assert_allclose(
                    baseline[p, q] + baseline[q, r], baseline[p, r], atol=1e-6, rtol=0
                )
        self.assertGreater(np.max(abs(uvw[:6] - uvw[-6:])), 0.01)

    def test_ms_metadata_and_manifest_agree(self):
        times, ant1, ant2, data, flags, intervals = self.columns(
            "", "TIME", "ANTENNA1", "ANTENNA2", "DATA", "FLAG", "INTERVAL"
        )
        self.assertEqual(len(times), self.manifest["rows"])
        self.assertEqual(data.shape, flags.shape)
        self.assertFalse(data.any())
        self.assertFalse(flags.any())
        self.assertTrue((ant1 < ant2).all())
        np.testing.assert_allclose(
            np.unique(times), self.manifest["times_mjd_seconds"], rtol=0, atol=1e-6
        )
        frequencies, widths = self.columns("SPECTRAL_WINDOW", "CHAN_FREQ", "CHAN_WIDTH")
        np.testing.assert_array_equal(frequencies[0], self.manifest["frequencies_hz"])
        self.assertEqual(data.shape[1:], (frequencies.size, 4))
        self.assertTrue((widths > 0).all())
        corr, products = self.columns("POLARIZATION", "CORR_TYPE", "CORR_PRODUCT")
        np.testing.assert_array_equal(corr[0], [9, 10, 11, 12])
        np.testing.assert_array_equal(products[0], [[0, 0], [0, 1], [1, 0], [1, 1]])
        (limits,) = self.columns("OBSERVATION", "TIME_RANGE")
        self.assertLessEqual(limits[0, 0], min(times - intervals / 2))
        self.assertGreaterEqual(limits[0, 1], max(times + intervals / 2))
        np.testing.assert_allclose(
            read_pointing_centre(str(self.ms), 1, 1),
            self.manifest["phase_pointing_rad"],
            rtol=0,
            atol=1e-12,
        )
        with table(str(self.ms), ack=False) as tab:
            self.assertEqual(tab.getcolkeywords("TIME")["MEASINFO"]["Ref"], "UTC")

    def test_epoch_and_uvw_w_sign_independently(self):
        times, ant1, ant2, uvw = self.columns("", "TIME", "ANTENNA1", "ANTENNA2", "UVW")
        # Unix-to-MJD conversion is independent of the generator's astropy Time path.
        start = (
            datetime(2026, 1, 15, 20, tzinfo=timezone.utc).timestamp() + 40587 * 86400
        )
        np.testing.assert_allclose(
            np.unique(times), start + np.array([0, 300, 600]), atol=1e-6, rtol=0
        )
        (positions,) = self.columns("ANTENNA", "POSITION")
        (phase,) = self.columns("FIELD", "PHASE_DIR")
        dm = measures()
        dm.doframe(
            dm.position(
                "itrf", *[quantity(float(x), "m") for x in positions.mean(axis=0)]
            )
        )
        ra, dec = phase[0, 0]
        for epoch in np.unique(times):
            dm.doframe(dm.epoch("UTC", quantity(float(epoch / 86400), "d")))
            direction = dm.measure(
                dm.direction(
                    "J2000", quantity(float(ra), "rad"), quantity(float(dec), "rad")
                ),
                "ITRF",
            )
            lon, lat = direction["m0"]["value"], direction["m1"]["value"]
            unit = [np.cos(lat) * np.cos(lon), np.cos(lat) * np.sin(lon), np.sin(lat)]
            selected = times == epoch
            # Does not call to_uvw: W is the ECEF baseline projected on the source.
            expected_w = (positions[ant2[selected]] - positions[ant1[selected]]) @ unit
            np.testing.assert_allclose(uvw[selected, 2], expected_w, atol=1e-4, rtol=0)

    def test_source_lock_provenance(self):
        lock = json.loads(
            (Path(__file__).parents[1] / "audit/source-lock.json").read_text()
        )
        for source in ("simms", "mkpsim"):
            self.assertEqual(
                self.manifest[f"{source}_commit"], lock["sources"][source]["commit"]
            )
        names, positions, diameters = self.columns(
            "ANTENNA", "NAME", "POSITION", "DISH_DIAMETER"
        )
        for index, row in enumerate(self.manifest["antennas"]):
            self.assertEqual(names[index], row["name"])
            np.testing.assert_array_equal(positions[index], row["position_m"])
            self.assertEqual(diameters[index], row["diameter_m"])

    def test_complete_ms_reads_with_daskms_dimension_contract(self):
        # The public MS reader checks dimension consistency across all columns.
        # In particular FLAG_CATEGORY is (row, flagcat, chan, corr), rather than
        # (row, chan, corr, flagcat), even though casacore accepts either shape.
        datasets = xds_from_ms(str(self.ms), group_cols=["DATA_DESC_ID"])
        self.assertEqual(len(datasets), 1)
        dataset = datasets[0]
        self.assertEqual(dataset.sizes["row"], self.manifest["rows"])
        self.assertEqual(dataset.sizes["chan"], len(self.manifest["frequencies_hz"]))
        self.assertEqual(dataset.sizes["corr"], 4)
        self.assertEqual(
            dataset["FLAG_CATEGORY"].dims, ("row", "flagcat", "chan", "corr")
        )
        np.testing.assert_array_equal(
            dataset["FLAG_CATEGORY"].data.compute(), np.zeros((18, 1, 3, 4), dtype=bool)
        )

    def test_baseline_type_coverage_and_real_beam_reader(self):
        names, types, mounts = self.columns(
            "ANTENNA", "NAME", "TELESCOPE_NAME", "MOUNT"
        )
        self.assertEqual(list(names), ["m000", "m001", "e017", "e026"])
        ant1, ant2 = self.columns("", "ANTENNA1", "ANTENNA2")
        self.assertEqual(
            {tuple(sorted((types[p], types[q]))) for p, q in zip(ant1, ant2)},
            {("MKAT", "MKAT"), ("EXT", "MKAT"), ("EXT", "EXT")},
        )
        sample = np.radians([0.3])
        for mode in ("hetero", "homo", "unity"):
            config = load_beam_config(ROOT / f"simms-{mode}.yaml")
            assignments, providers, rotating = resolve_antenna_beams(
                types, mounts, config
            )
            self.assertTrue(rotating.all())
            by_ant = [
                providers[index].jones(sample, sample, [1.302e9], [0])[0, 0, 0]
                for index in assignments
            ]
            np.testing.assert_array_equal(by_ant[0], by_ant[1])
            np.testing.assert_array_equal(by_ant[2], by_ant[3])
            if mode == "hetero":
                self.assertGreater(np.max(abs(by_ant[0] - by_ant[2])), 0.01)
            else:
                np.testing.assert_allclose(by_ant[0], by_ant[2], atol=0, rtol=0)
            if mode == "unity":
                np.testing.assert_allclose(
                    by_ant, np.broadcast_to(np.eye(2), (4, 2, 2)), atol=1e-14
                )

    def test_canonical_sky_parses_with_simms(self):
        canonical = json.loads((ROOT / "sky.json").read_text())
        sky = ASCIISkymodel(
            str(ROOT / "sky.txt"), source_schema_file=str(ROOT / "simms-schema.yaml")
        )
        self.assertEqual(len(sky.sources), len(canonical))
        for source, row in zip(sky.sources, canonical):
            self.assertEqual(source.name, row["name"])
            for attribute, key in [
                ("ra", "ra_rad"),
                ("dec", "dec_rad"),
                ("stokes_i", "i"),
                ("stokes_q", "q"),
                ("stokes_u", "u"),
                ("stokes_v", "v"),
            ]:
                self.assertAlmostEqual(getattr(source, attribute), row[key], places=12)

    def test_fits_voltage_normalization_and_axis_metadata(self):
        for kind in ("MKAT", "EXT", "UNITY"):
            raw, normed = [], []
            for corr in ("xx", "xy", "yx", "yy"):
                entries = []
                for directory in ("raw", "normalized"):
                    real = fits.getdata(
                        ROOT / f"beams/{directory}/{kind}_{corr}_re.fits"
                    )
                    imag = fits.getdata(
                        ROOT / f"beams/{directory}/{kind}_{corr}_im.fits"
                    )
                    entries.append(real + 1j * imag)
                raw.append(entries[0])
                normed.append(entries[1])
            # Independent physical identity: max unpolarized power is unity.
            power = sum(np.abs(entry) ** 2 for entry in normed) / 2
            self.assertAlmostEqual(float(power.max()), 1.0, places=12)
            factor = np.sqrt((sum(np.abs(entry) ** 2 for entry in raw) / 2).max())
            for before, after in zip(raw, normed):
                np.testing.assert_allclose(
                    after * factor, before, rtol=1e-12, atol=1e-14
                )
            header = fits.getheader(ROOT / f"beams/raw/{kind}_xx_re.fits")
            self.assertEqual(
                [header[f"CTYPE{i}"] for i in (1, 2, 3)], ["px", "py", "FREQ"]
            )
            freqs = (
                header["CRVAL3"]
                + (np.arange(header["NAXIS3"]) + 1 - header["CRPIX3"])
                * header["CDELT3"]
            )
            self.assertLessEqual(freqs.min(), min(self.manifest["frequencies_hz"]))
            self.assertGreaterEqual(freqs.max(), max(self.manifest["frequencies_hz"]))

    def test_checksums_and_nonoverwrite(self):
        before = (ROOT / "manifest.json").read_bytes()
        for relative, expected in self.manifest["files_sha256"].items():
            self.assertEqual(
                hashlib.sha256((ROOT / relative).read_bytes()).hexdigest(),
                expected,
                relative,
            )
        # Must reject before attempting to inspect even a nonexistent source checkout.
        process = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).with_name("build_fixture.py")),
                "--output",
                str(ROOT),
                "--mkpsim-source",
                "/nonexistent-fixture-test-source",
            ],
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(process.returncode, 0)
        self.assertIn("output already exists", process.stderr)
        self.assertEqual((ROOT / "manifest.json").read_bytes(), before)

    def test_validator_rejects_changed_ms(self):
        with tempfile.TemporaryDirectory(prefix="fixture-corruption-") as temporary:
            copy = Path(temporary) / "bundle"
            shutil.copytree(ROOT, copy)
            with table(str(copy / "empty.ms"), readonly=False, ack=False) as tab:
                values = tab.getcell("DATA", 0)
                values[0, 0] = 1 + 2j
                tab.putcell("DATA", 0, values)
            with self.assertRaisesRegex(ValueError, "common MS has changed"):
                validate(copy)

    def test_validator_rejects_changed_fits(self):
        with tempfile.TemporaryDirectory(prefix="fixture-corruption-") as temporary:
            copy = Path(temporary) / "bundle"
            shutil.copytree(ROOT, copy)
            beam = copy / "beams/raw/MKAT_xx_re.fits"
            # Change a data byte without involving the FITS parser or its checksums.
            with beam.open("r+b") as stream:
                stream.seek(-1, 2)
                byte = stream.read(1)
                stream.seek(-1, 2)
                stream.write(bytes([byte[0] ^ 1]))
            with self.assertRaisesRegex(ValueError, "file checksum mismatch"):
                validate(copy)

    def test_validator_rejects_redirected_subtable(self):
        with tempfile.TemporaryDirectory(prefix="fixture-link-") as temporary:
            copy = Path(temporary) / "bundle"
            shutil.copytree(ROOT, copy)
            with table(str(copy / "empty.ms"), readonly=False, ack=False) as tab:
                tab.putkeyword("POINTING", "Table: " + str(ROOT / "empty.ms/POINTING"))
            with self.assertRaisesRegex(ValueError, "subtable link leaves common MS"):
                validate(copy)

    def test_validation_report_cannot_overwrite_inputs(self):
        before = (ROOT / "manifest.json").read_bytes()
        process = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).with_name("validate_fixture.py")),
                str(ROOT),
                "--output",
                str(ROOT / "manifest.json"),
            ],
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(process.returncode, 0)
        self.assertIn("outside the immutable fixture", process.stderr)
        self.assertEqual((ROOT / "manifest.json").read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
