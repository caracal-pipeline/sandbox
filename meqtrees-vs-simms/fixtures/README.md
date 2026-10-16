# Shared diagnostic fixtures

These inputs exercise the common simulation contract before the full scientific
case. The builder produces a **synthetic diagnostic** bundle, not an eidos or
MeerKAT+ holography result. Large generated FITS files and MSs stay outside git.

## Build and validate

Use the pinned clean simms and mkpsim checkouts listed in `../audit/source-lock.json`.
The builder checks their actual commits and dirty state, including the installed
simms source origin, rather than trusting its unchanged package version.

```bash
cd "$SIMMS_SRC"
uv sync --locked --no-dev
uv run --no-sync python "$PROJECT/fixtures/build_fixture.py" \
  --mkpsim-source "$MKPSIM_SRC" --output "$RUN_ROOT/tiny"
uv run --no-sync python "$PROJECT/fixtures/validate_fixture.py" "$RUN_ROOT/tiny" \
  --output "$RUN_ROOT/tiny-validation.json"
uv run --no-sync python "$PROJECT/fixtures/test_fixture.py" "$RUN_ROOT/tiny" -v
```

`PROJECT` is the absolute `meqtrees-vs-simms/` directory. Output must not exist;
the builder never deletes or overwrites a previous bundle. Failed construction
may leave an incomplete output directory, which must not be used. Only a bundle
with a complete manifest that passes validation is ready for a simulator.

## Contents and physical meaning

| Input | Definition |
| --- | --- |
| Array | m000, m001, e017, e026, with exact ITRF positions and dish metadata from pinned mkpsim layout |
| Baselines | Six cross-correlations, including MeerKAT–MeerKAT, mixed and extension–extension |
| Time | 2026-01-15T20:00:00 UTC, plus 300 and 600 seconds; 4-second exposures |
| Frequency | 1300, 1302, 1304 MHz; 2 MHz channel widths; TOPO reference |
| Correlations | XX, XY, YX, YY; explicit CORR_TYPE and CORR_PRODUCT |
| Sky | Three unpolarized flat-spectrum point sources, one on-axis and two asymmetric off-axis; canonical JSON and one Tigger-format ASCII catalogue |
| Beams | Two asymmetric chromatic complex 2×2 voltage patterns with distinct leakage; plus identity Jones |
| Beam support | 65×65 spatial samples across ±2.5 degrees; nine 1 MHz planes from 1298 to 1306 MHz |
| Pointing | Fixed J2000 RA 0, Dec −30 degrees; equals phase centre for all antennas |

The sparse timestamps deliberately span 604 seconds of observation bounds while
containing only 12 seconds of integrated exposure. This is a geometry/rotation
diagnostic, not a continuous performance workload. All data columns start at
zero, all samples are unflagged, weights are unity and no noise is generated.

The common MS is created using python-casacore's default MS schema. At each actual
UTC timestamp, casacore converts the ITRF baseline `POSITION[ANTENNA2] -
POSITION[ANTENNA1]` into J2000 UVW. This avoids copying the currently audited
simms generator's timestamp/UVW mismatch. The fixture tests independently check
baseline lengths, closure and W against the ITRF-transformed field direction.
No simulator's predictions are used to generate the inputs.

`sky.json` holds the exact physical catalogue. `sky.txt` is consumed by Tigger;
`simms-schema.yaml` explicitly maps its radians and Stokes aliases to simms.
Actual simms parsing is tested; actual Tigger loading is a native-runtime gate.
Polarized sources, displaced pointing, smearing and beam boundaries are later
equivalence cases, not silently included here.

## Beam assignment and normalization

Each mode has a MeqTrees station JSON and a simms YAML:

- `hetero`: m antennas use MKAT, e antennas use EXT.
- `homo`: all four antennas use MKAT.
- `unity`: all four antennas use identity Jones.

The ANTENNA table has explicit `TELESCOPE_NAME` labels MKAT/EXT. The simms YAML
maps both labels even in homogeneous/unity modes; no dish-size inference is used.
MeqTrees maps by exact antenna name. Both use spatial signs X/Y, matching the
positive `px`/`py` FITS axes and their verified axis order.

MeqTrees reads `beams/raw` with its normalization enabled. simms reads a separate
`beams/normalized` copy, divided by the same full-cube scalar used by Cattery:

`sqrt(max(|Exx|² + |Exy|² + |Eyx|² + |Eyy|²) / 2)`.

The raw synthetic voltages are quantized to float32 precision, then written as
float64 FITS arrays. Normalized files are float64 so the normalization itself
does not add another float32 rounding. Actual sampled simms beam grids still
use complex64; convergence and precision limits belong to #6.

## Integrity and copies

The manifest records input-file SHA256 values, source commits, layout checksum,
builder/source-lock checksums, dependency versions and a semantic MS snapshot.
The snapshot hashes each scientific column's shape, dtype, values and column
keywords; volatile casacore lock/storage bytes are excluded. It includes every
column in the required populated tables, so edits to UVW, flags, metadata or
initial data are detected. Geometry can depend on the installed casacore measures
data; use the recorded numerical fingerprint to identify regenerated inputs.

Generated configuration files contain absolute paths, so **regenerate at the
destination rather than relocating a bundle**. For each engine, make an
independent deep MS copy using casacore, for example:

```python
from casacore.tables import table
with table(str(bundle / "empty.ms"), ack=False) as source:
    source.copy(str(engine_output), deep=True, valuecopy=True).close()
```

Do not predict into `empty.ms`. Validate the common bundle again after engine
runs. Keep validation reports outside the bundle so input inventories remain
unambiguous.

For a simms smoke test, use `sky.txt`, `simms-schema.yaml`, the selected
`simms-MODE.yaml`, `--beam-jones full --smearing none --column CORRECTED_DATA`,
and an independent MS copy. This is an integration check, not the benchmark
workflow or a performance measurement. Shinobi orchestration remains #5.

## Scientific reference still required

The 77-antenna layout and original 10×10 reference sky are available from pinned
mkpsim. The intended scientific runs additionally require the actual extension
holography cube and matching eidos output. Their acquisition, source checksums,
splitter ordering and frequency coverage must be validated before replacing
these synthetic beams. This diagnostic bundle does not close that part of #4.
