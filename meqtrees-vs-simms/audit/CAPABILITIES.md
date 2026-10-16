# Issue #3: environment and beam capability audit

Follow-up: [reference-image/runtime checks](../runtime/README.md) now identify
the image digest, confirm matching installed source hashes, and resolve a real
Timba Python forest with the [shared diagnostic fixture](../fixtures/README.md).
Native kernel loading/prediction remains blocked by this host's AF_UNIX policy.
The initial audit evidence below is retained as the historical baseline.

## Evidence and status

This audit pins the source versions in `source-lock.json`. simms at
`5a45f0ccb2a18f569e7f127a769cf136f8e8a261` was installed from its clean
`origin/main` checkout using its tracked `uv.lock`. Its package version still
reports **3.0.2**; that number alone does not identify the tested code.
Python 3.12.14, stimela-ninja 0.1.0b7, NumPy 2.4.6, SciPy 1.18.0,
Astropy 8.0.1 and python-casacore 3.8.1 were observed. See the complete
environment manifest and requirements snapshot in this directory.

simms native imports and `simms skysim --help` passed. The original Cattery
FITS reader and JSON reader were executed in standalone mode against synthetic
inputs. **Neither a Timba graph nor a MeqTrees MS prediction was executed.**
The local environment lacks Timba, Cattery as an installed package,
`meqtree-pipeliner.py`, `meqserver`, Docker, Singularity and Apptainer. The
negative environment capture exits 2 and records this explicitly.

The pinned Cattery source declares version 1.8.0 and Timba's CMake file declares
2.0.0. These are **source declarations**, not installed runtime versions.
Current pinned cult-cargo implies `quay.io/stimela2/meqtrees:cc0.2.1`, but the
digest is unresolved. Its Dockerfile installs Cattery with a lower bound and
clones unpinned Timba, so it cannot establish the image's actual source commits.
The mkpsim project itself leaves these dependencies unpinned.

Issue #3 remains open until the selected native environment can compile the
direct profile and expose its effective options. Do not substitute source
declarations or a container tag for that evidence.

## Capability comparison

| Property | Pinned Cattery/Timba source | Pinned simms main | Evidence/action |
| --- | --- | --- | --- |
| Full voltage Jones | `pybeams_fits.beam_type=2x2`; eight files | `--beam-jones full`; eight-file Cattery reader | Reader probe checks distinct XY/YX positions; simms CLI passes |
| Heterogeneous types | Station-name JSON; type-specific patterns | YAML per-type provider or restricted JSON | Original mkpsim JSON accepted by Cattery reader and rejected by simms reader |
| Spatial axes | Selects FITS axes by CTYPE (`px`, `py` in mkpsim) | Assumes FITS axes 1/2/3 are spatial/spatial/frequency; X/Y options select signs | Positive `px`/`py` maps to simms X/Y only after header-order validation; do not use default -X blindly |
| Cube interpolation | Spline order 1–5, default value 3; real/imag separately by default | Linear complex interpolation in spatial/frequency coordinates | Order-1 affine probe agrees to 5.6e-17 absolute |
| Normalization | mkpsim requests normalization | Preserves supplied voltages | Normalize a separate simms copy by the reference scalar; retain raw cubes and hashes |
| Spatial boundary | `map_coordinates(..., mode='nearest')` | Fill with zero | Boundary discrepancy reproduced; restrict common support |
| Frequency boundary | Edge plane plus frequency-scaled direction coordinates | Multi-plane cube fills with zero | Discrepancy reproduced; use interior frequency coverage initially |
| Rotation | Source coordinates rotated per station in `pybeams_fits` | Beam grid uses array-reference location and time interpolation | Not the same numerical algorithm; quantify station/time-grid error in #6 |
| Beam centre | `src.direction.lm()` relative to phase centre, plus optional offsets | Reads pointing centre independently | Initially require equal pointing and phase centres |
| Polarization rotation | Separate L sky term and P feed term | Beam code rotates direction coordinates; no separate PA rotation of source coherency in this path | Keep L disabled and P identity for initial common model; polarized tests need explicit chain verification |
| Smearing | Tensor predictor can smear when UVW derivatives are supplied | Analytic smearing by default | Explicitly disable for the initial beam-only comparison |
| Precision | Standalone reader uses complex128 | FITS provider uses complex128; sampled beam grid stored as complex64 | No promise of double-precision visibility agreement |

All reader results use synthetic data, not the unavailable scientific holography
cube. They establish loader behaviour, not measured primary-beam equivalence.
The native-JSON failure includes an additional parser defect: the simms reader
extends a list with each string pattern, treating its characters as patterns
(the probe reports 24 distinct characters). Converting strings to lists alone
still leaves its single-distinct-pattern restriction. Use the per-type YAML
adapter for these two scientific beam sets.

## Resolved configuration ambiguities

**Channel limits.** `MSContentSelector.create_selection_record()` emits channel
start/end/increment only when `select_channels` is true. Its menu toggle starts
false in the pinned TDL implementation. Therefore mkpsim's `0,0` limits alone
do not establish a one-channel run. Set `ms_sel.select_channels=0` explicitly
and check actual output metadata. For a channel subset, enable the toggle and
set the inclusive last index from the common MS.

**Correlations.** `ms_corr_sel` expects the textual value `2x2`, not `4`.
Pinned `MSUtils` defines four correlation indices for `2x2`. For a one-row
POLARIZATION table, `_select_new_ms()` derives correlation labels from
`CORR_TYPE` and invokes `_select_polarization()`; the supplied TDL label order
is not sufficient evidence of output ordering. The direct profile selects
`2x2` and standard linear labels; the runner must still validate actual MS
metadata. The legacy `4` setting is not copied.

**Defaults versus effective settings.** The custom mkpsim config replaces the
cab's fallback `/meqConfs/tdlconf-sim.profiles`; do not merge their settings
implicitly. The fallback explicitly disables smearing, whereas MeqMaker's
constructor passes `default=True` to a TDL menu whose implementation initializes
toggle state from `open`. Consequently the apparent constructor default is
not sufficient evidence that smearing is enabled. An earlier source impression
that MeqTrees defaults to smearing on was too strong. The direct profile disables
it explicitly; Timba compilation remains the gate for effective values.

**Jones chain.** turbo-sim registers Ncorr, Z, L and E sky terms, then P, D, G
and iP UV terms. The mkpsim cab enables E and P but does not itself enable L or
`feed_angle.enable_pa`. E's spatial rotation is independent of rotating the
electric-field polarization basis. The proposed common profile makes only E
nontrivial: L and other corruptions off, P enabled with zero feed angle and PA
addition off. This is an explicit comparison configuration; its identity P and
effective chain must be verified at graph compilation before polarized tests.

**Per-station beams.** The cab sets `me.e_all_stations=1`. In TensorMeqMaker,
this shares the first station's tensor only if E advanced options are enabled.
Do not infer that the cab necessarily homogenizes the array. The direct profile
sets `me.e_advanced=0` and `me.e_all_stations=0`; station typing remains enabled
inside the beam module.

**Normalization.** For a full matrix Cattery computes
`sqrt(max(|Exx|²+|Exy|²+|Eyx|²+|Eyy|²)/2)` over the loaded cube and divides every
interpolated entry by that one scalar. It is not an on-axis or per-frequency
normalization, and the two station types can have different scalars. Preserve
relative Jones elements and frequency dependence.

**Smearing hard-off.** In the tensor path, UVW derivatives gate the smearing
term. The proposed profile sets `me.use_smearing=0` and both fixed intervals to
zero. simms uses `--smearing none`. A later averaging study must compare actual
algorithms rather than just toggling both on.

## Direct invocation contract

`meqtrees-direct.tdl` is a source-reviewed **candidate**, not a compiled profile.
The Shinobi adapter in #5 must pass these as argument-vector elements, preserving
spaces within each value, and derive Cattery's path using the MeqTrees interpreter:

```python
argv = [
    meq_pipeliner, "--config", str(profile), "--mt", str(ncpus),
    "--save-config", str(resolved_profile),
    "@sim", f"ms_sel.msname={ms}",
    "ms_sel.output_column=CORRECTED_DATA",
    f"tiggerlsm.filename={sky}",
    f"pybeams_fits.filename_pattern={stationspec}",
    "sim_mode=sim only", str(cattery_dir / "Siamese/turbo-sim.py"),
    "=_simulate_MS",
]
```

The pinned pipeliner implements `--save-config`; retain that resolved file
alongside stdout/stderr and hash it in the native environment capture. A saved
file must still be checked against MS metadata and the compiled Jones graph.

The equivalent simms command contract is:

```text
simms skysim --ascii-sky SKY --source-schema SCHEMA
  --primary-beam BEAMS_YAML --beam-jones full --smearing none
  --pol-basis linear --column CORRECTED_DATA --mode sim
  --nworkers N --beam-pa-step STEP MS_COPY
```

`SCHEMA` must map the common catalogue explicitly. `BEAMS_YAML` uses independently
normalized FITS copies and explicit X/Y axis signs; the station-type metadata
must be assigned from the station specification, not inferred from dish sizes.
Drop `--source-schema` only when a native validated simms catalogue is used.
Disable E for the beam-off control, retaining the other explicit choices.
The interpolation diagnostic changes only `pybeams_fits.spline_order=1`; retain
the order-3 profile as the scientific-reference case.

## Evidence sources

Links are pinned to the audited commits; file names identify the relevant methods.

- [mkpsim recipe and config](https://github.com/ska-sa/mkp-sci-com/tree/743a92724cb0dfd3b98de6e80786aa2a94bcf7d2/src/mkpsim)
- [cult-cargo direct command construction](https://github.com/caracal-pipeline/cult-cargo/blob/4258478fa5f592200b50b5822ff6034960aa46ff/cultcargo/meqtree-pipeliner.yml)
- [image build recipe](https://github.com/caracal-pipeline/cult-cargo/blob/4258478fa5f592200b50b5822ff6034960aa46ff/cultcargo/images/meqtrees/Dockerfile.kern9)
- [Cattery pybeams_fits](https://github.com/ratt-ru/meqtrees-cattery/blob/710d20b9b2f16b0a1499fca4ed4c3607ed5059fe/Cattery/Siamese/OMS/pybeams_fits.py)
- [Cattery interpolator](https://github.com/ratt-ru/meqtrees-cattery/blob/710d20b9b2f16b0a1499fca4ed4c3607ed5059fe/Cattery/Siamese/OMS/InterpolatedBeams.py)
- [MS selection](https://github.com/ratt-ru/meqtrees-cattery/blob/710d20b9b2f16b0a1499fca4ed4c3607ed5059fe/Cattery/Meow/MSUtils.py)
- [tensor predictor](https://github.com/ratt-ru/meqtrees-cattery/blob/710d20b9b2f16b0a1499fca4ed4c3607ed5059fe/Cattery/Meow/TensorMeqMaker.py)
- [TDL defaults and parsing](https://github.com/ratt-ru/meqtrees-timba/blob/853ab56814da3d7a4e903b55b54dcc4e3d6ded28/PyApps/src/TDL/TDLOptions.py)
- [native smearing](https://github.com/ratt-ru/meqtrees-timba/blob/853ab56814da3d7a4e903b55b54dcc4e3d6ded28/MeqNodes/src/PSVTensor.cc)
- [simms beams](https://github.com/shinobi-dosho/simms/blob/5a45f0ccb2a18f569e7f127a769cf136f8e8a261/src/simms/skymodel/beams.py)
- [simms command configuration](https://github.com/shinobi-dosho/simms/blob/5a45f0ccb2a18f569e7f127a769cf136f8e8a261/src/simms/apps/skysim.py)

## Outstanding native-runtime gate

1. Resolve the actual reference image digest and inspect its packages/source
   provenance, or build the pinned source candidate and explicitly document any
   difference from the mkpsim runtime. No final native selection has been made.
2. Run `capture_environment.py` with that environment's interpreter, providing
   source checkouts only when they identify the installed code. Source checkout
   cleanliness and matching hashes alone do not prove an installed binary's origin.
3. Compile the direct profile on a tiny validated MS. Capture the TDL-resolved
   options and verify selected channels, correlation layout, E type, station
   assignments, P/L chain, disabled smearing and output column.
4. Verify the profile against the installed version before declaring #3 complete.
   The MS/beam fixture implementation belongs to #4 and prediction comparisons
   belong to #6; this audit does not claim those results.
