# MeqTrees vs simms

Establish whether simms and MeqTrees produce equivalent primary-beam effects, then compare runtime and peak memory at matched accuracy and CPU allocation.

## Agreed execution model

Use one **Shinobi pipeline** to invoke both simulators directly. Do not execute the Stimela2 mkpsim recipe. MeqTrees may use an explicit isolated environment, but orchestration remains in Shinobi.

Use [shinobi-dosho/simms](https://github.com/shinobi-dosho/simms) **origin/main**, not the PyPI release. Resolve and record an exact commit for each campaign.

Use [mkpsim](https://github.com/ska-sa/mkp-sci-com/tree/main/src/mkpsim) as the scientific reference: 64 MeerKAT plus 13 extension antennas; eidos MeerKAT beams; extension holographic beams; homogeneous and heterogeneous station assignments; full complex Jones and sky rotation. Verify actual MeqTrees/Timba/Cattery versions and effective settings before relying on current upstream defaults.

## Tracking

Umbrella: [#2](https://github.com/caracal-pipeline/sandbox/issues/2).

| Issue | Work package | Prerequisites |
| --- | --- | --- |
| [#3](https://github.com/caracal-pipeline/sandbox/issues/3) | Environment and capability audit | None |
| [#4](https://github.com/caracal-pipeline/sandbox/issues/4) | Shared MS, sky and beam fixtures | #3 |
| [#5](https://github.com/caracal-pipeline/sandbox/issues/5) | One Shinobi pipeline and direct adapters | #3, #4 |
| [#6](https://github.com/caracal-pipeline/sandbox/issues/6) | Equivalence and convergence | #4, #5 |
| [#7](https://github.com/caracal-pipeline/sandbox/issues/7) | Runtime, memory and scaling | #5, passing #6 configurations |

Issues are repository-level and scoped to this folder. Project board membership is managed separately.

## Initial comparison matrix

| Stage | Cases |
| --- | --- |
| Underlying prediction | Beam disabled, then unity beam |
| Scientific beam | Homogeneous full Jones, then heterogeneous full Jones |
| Diagnostics | Isolated directions; asymmetric beam; time/rotation; frequency knots and inter-knot samples; polarization after checking Jones conventions |
| Reference workload | 77 antennas; 1 hour; 4-second integration; requested 1300–1305 MHz at 0.208984 MHz spacing; use actual MS channel metadata |
| Reference sky | Verify the mkpsim 10×10 point-source example's exact footprint and fluxes before adopting it |
| Scaling | Sources, times, channels and physical CPU allocation independently; levels selected after a pilot |
| Accuracy | Original MeqTrees settings; separate order-1 interpolation diagnostic; simms time-grid convergence; held-out samples |

Prepare common inputs once and hash them. Give each simulator an independent copy of the same authoritative empty MS and compare the same output column using row/channel/correlation metadata.

## Compatibility checks to resolve

The following are source-audit findings, not measured results:

- simms defaults to diagonal beams and analytic smearing. Explicitly select full Jones and match averaging/noise settings.
- mkpsim enables Cattery normalization; inspected upstream full-Jones normalization divides by `sqrt(max(|Exx|²+|Exy|²+|Eyx|²+|Eyy|²)/2)` over the loaded cube. simms preserves FITS amplitudes. Match this convention explicitly.
- Cattery offers spline interpolation; simms uses linear FITS interpolation and sampled time grids. Compare reference behaviour and matched interpolation separately.
- mkpsim's station JSON has separate filename patterns supplied as strings, outside the inspected simms JSON subset. Use a faithful per-type YAML/metadata adapter or resolve compatibility explicitly.
- Outside spatial/frequency support the inspected implementations behave differently. Restrict initial equivalence tests to their common valid domain.
- Begin with pointing and phase centres coincident. Verify electric-field polarization rotation separately from spatial beam rotation.
- Resolve the supplied TDL's channel start/end values of zero and polarization-label ordering against effective runtime selection and actual MS metadata.
- Check per-station versus array-reference parallactic-angle calculations and TIME/UVW consistency.

## Measurement and deliverables

Report complex residual RMS, percentile and maximum per correlation, with absolute errors near nulls and an explicit normalization floor. Define acceptance criteria before production measurements.

Measure simulator launch through completed output writes and exit. Report preparation and optional imaging separately. Capture peak concurrent memory for the entire process tree, exact resource limits, errors and repeated-run dispersion. Distinguish first-run/JIT and warmed-cache performance and alternate engine order.

Deliver a runnable Shinobi recipe, engine adapters, fixtures/manifests, machine-readable results and an evidence-based comparison report. Keep large cubes, MSs and generated results outside git, with acquisition paths and checksums.

## Status

Scope and tracking established. Implementation and experiments are pending; no equivalence or performance claim has been established.
