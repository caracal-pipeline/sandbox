# Direct MeqTrees runtime probe

This supplements issue #3's source audit. It does not run Stimela and does not
benchmark performance. Keep the MeqTrees and simms Python environments separate.

## Resolve reference provenance

```sh
python runtime/resolve_reference.py --output /absolute/new-reference-capture
```

Both tools require a fresh output directory and refuse to overwrite evidence.

The captured public image tag resolves to the registry-reported schema-1 digest
in `results/reference-image.json`. The raw manifest is retained separately.
This identifies the current reference image, not an earlier user's installation.
Its build history uses unpinned Cattery packages and a Timba Git clone; package
versions and the source commit must be captured from the running environment.

## Compile and execute

Run `probe_native.py` with the Python interpreter from the selected MeqTrees
environment. The native `meqserver` executable must be on PATH. Use absolute
paths for the inputs. The script adds installed Cattery to the historical module
search path, starts a real kernel, compiles `turbo-sim.py`, and records the
registered/effective options alongside requested options. Unknown or differently
serialized options require explicit review; successful compilation is not proof
that every requested setting was honored.

```sh
python runtime/probe_native.py \
  --profile audit/meqtrees-direct.tdl \
  --set ms_sel.msname=/absolute/disposable-case.ms \
  --set tiggerlsm.filename=/absolute/sky.lsm.html \
  --set 'pybeams_fits.filename_pattern=/absolute/stations.json' \
  --output /absolute/probe-output
```

The installed reference Tigger option name is `tiggerlsm.filename`; Python
forest resolution verifies that it is registered. Native graph loading remains
unverified. Add `--predict` only for a disposable MS copy; this
writes `CORRECTED_DATA`. Prediction returning successfully still requires
checking output shape, finite values, selected rows/channels, and meaningful
nonzero values against fixture expectations. Exceptions fail this probe rather
than being swallowed by the standard pipeliner's job handler.

A process supervisor should impose a timeout and terminate the complete process
group if the kernel hangs. Do not time this diagnostic script as a benchmark.

## Results on this host

`results/host-constraints.json` records successful imports of extracted reference
image Timba/Cattery/casacore, the image's exact Timba Git commit, SHA256 hashes of
installed source files and native extension, and a direct AF_UNIX socket check.
Creating an AF_UNIX socket raises `PermissionError: [Errno 1] Operation not
permitted`. The standard Timba driver requires that IPC transport; startup
attempts time out. No alternative transport was attempted.

The Python packages were extracted privately from digest-verified image layers.
The image Python 3.10 interpreter and dependencies were relocated for imports and
Python graph inspection. This is not a complete container execution and must not
be used as the performance environment. No packages were installed globally.

`--define-only` permits bounded progress without claiming native graph loading.
It skips the compiler's unconditional Clear.Forest RPC in a fresh process, then
uses the real installed Timba Python compiler and node resolver with no server.
`results/definition-hetero/` records 102 resolved nodes for the final diagnostic
fixture. All requested profile/input keys are registered. Nine are omitted by
Timba's config serializer because they are hidden or behind disabled menus:
advanced same-station selection, fixed-smearing controls, channel-subset values,
singleton DDID/field selectors and metadata-driven polarization selection. The
probe records the entire option registry separately to avoid misidentifying
these as unsupported options.

The installed Cattery beam modules, MSUtils, TensorMeqMaker, turbo-sim, and Timba
TDLOptions/Compile files are byte-identical to the source-lock checkouts. The
image contains Cattery 1.8.0, Python 3.10.12, and Timba source commit
`853ab56814da3d7a4e903b55b54dcc4e3d6ded28`. This strengthens the source audit;
it does not establish loaded-kernel behavior or visibility equivalence.

Remaining issue #3 gate: run without `--define-only` on a host supporting the
standard MeqTrees IPC, review effective options, execute on a disposable fixture
MS, and validate selected rows/channels and finite/nonzero output.
