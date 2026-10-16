# Reproduce the issue #3 audit

Read [CAPABILITIES.md](CAPABILITIES.md) for findings and explicit limits.
`source-lock.json` pins five source checkouts. Runtime manifests distinguish
observed installations from source-only version declarations.

## simms environment

Clone each repository from the lock and checkout its recorded commit. Use a
fresh checkout rather than a sibling development tree. Example, with `SIMMS_SRC`
pointing at that checkout and `AUDIT` at this directory:

```bash
cd "$SIMMS_SRC"
uv sync --locked --no-dev
uv pip install --python .venv/bin/python astro-kittens==1.4.6
uv run --no-sync python "$AUDIT/capture_environment.py" \
  --engine simms --repo "simms=$SIMMS_SRC" \
  --lock "$AUDIT/source-lock.json" --file uv.lock \
  --file "$AUDIT/meqtrees-direct.tdl" --output /path/to/simms-environment.json
uv run --no-sync python "$AUDIT/probe_beam_readers.py" \
  --cattery "$CATTERY_SRC" --mkpsim "$MKPSIM_SRC" \
  --output /path/to/reader-probes.json
```

The additional astro-kittens package is for the standalone Cattery reader;
it is not a simms dependency. The source checkout's tracked `uv.lock` controls
simms dependencies. `requirements-simms.txt` records the exact observed audit
installation, including the extra reader dependency and the pinned simms URL.
It is an inventory snapshot, not a claim of portability to every platform.

For stricter source checks, pass `--repo cattery=...`, `--repo timba=...`,
`--repo mkpsim=...` and `--repo cult-cargo=...` to the collector. It checks their
heads/dirty state against the lock. Verify these before running reader probes;
the probe program does not independently enforce the source lock.

## Native MeqTrees environment

Invoke the collector using the **MeqTrees environment's interpreter**, with
that environment's bin directory on PATH:

```bash
"$MEQ_PYTHON" "$AUDIT/capture_environment.py" --engine meqtrees \
  --file "$AUDIT/meqtrees-direct.tdl" --output /path/to/meqtrees-environment.json
```

When using a pinned source installation, additionally supply `--lock` and
both `--repo cattery=PATH` and `--repo timba=PATH`. For an image installation,
record its immutable digest and package/build provenance separately; do not
associate unrelated source checkouts with its installed binaries.

Exit 0 means the requested checks/imports/help passed, **not** that prediction
is validated. Exit 2 means a required module, CLI, clean checkout or matching
source pin is missing. Manifests still write on failure. The checked-in
MeqTrees capture is deliberately a negative result from the available host.

The collector does not export credentials or the complete environment. It
records software, executable/source paths, selected thread settings, CPU
affinity, supplied file checksums and command results. Re-run captures on the
actual benchmark host; the scratch-host paths are evidence of this audit only.

## Checks performed

- simms native imports and CLI help.
- Original Cattery standalone reader versus simms reader on an asymmetric
  synthetic affine complex FITS cube, order-1 interpolation inside support.
- Distinct Jones matrix element ordering and preserved amplitudes in simms.
- Expected spatial/frequency boundary discrepancies.
- Original Cattery JSON mapping accepts mkpsim's station patterns while simms
  rejects that input form.
- Negative native-MeqTrees discovery/import check.

No scientific beam cube, common MS, timing benchmark or Timba graph was run.
