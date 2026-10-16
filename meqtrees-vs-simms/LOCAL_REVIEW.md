# Local review: shared fixtures and native runtime follow-up

These changes were reviewed in conversation against merged PR #8 and approved
for a direct commit to main. No additional PR was created.

## Shared fixtures (#4 diagnostic stage)

- Reproducible four-antenna, three-time, three-channel, full-correlation MS.
- Canonical three-source sky and shared Tigger ASCII with an explicit simms schema.
- Synthetic MKAT/EXT full-Jones beams, unity control, and separate reference-normalized copies.
- Explicit station mappings for heterogeneous, homogeneous and unity cases.
- SHA256 input inventory, source provenance and semantic MS fingerprint.
- Protection against overwrites, changed scientific contents, redirected subtable links and validation reports written into inputs.

Thirteen independent fixture tests passed. The tests use real dask-ms/simms
readers, independent UVW checks, normalization identities and deliberate data
corruption. A real simms smoke prediction passed for beam-off, unity,
homogeneous and heterogeneous cases. Unity and beam-off outputs agree exactly
on this diagnostic. Heterogeneous and homogeneous outputs differ as expected,
and the original common MS is unchanged.

See [fixtures/README.md](fixtures/README.md),
[validation evidence](fixtures/results/tiny-validation.json) and
[simms smoke evidence](fixtures/results/simms-smoke.json).

## MeqTrees runtime (#3)

The reference tag resolves to registry digest
`sha256:400db2aabb22b13ff15dcd80528daadf1471a04dc8f670e16f5171adec325e86`.
Image Python 3.10.12 and Cattery 1.8.0 are identified, and the image's Timba
source commit matches the audit. Relevant installed Python source files are
byte-identical to the audited checkouts. Native Timba imports work.

The actual installed Timba Python compiler resolves the heterogeneous fixture
into a 102-node forest. All requested profile keys are registered; omitted
serialized values are hidden/inactive options, not unsupported keys. Effective
full-Jones, normalization, beam rotation, identity P and disabled L/smearing
choices are recorded.

**Native execution remains blocked.** This host denies creation of AF_UNIX
sockets, which the standard MeqTrees driver uses to communicate with its kernel.
The definition-only probe explicitly skips its Clear.Forest RPC in a fresh
process. It does not load the forest into the kernel or predict visibilities.
Relocated image imports are not a substitute performance environment.

See [runtime/README.md](runtime/README.md),
[host constraint and source hashes](runtime/results/host-constraints.json), and
[resolved options](runtime/results/definition-hetero/probe.json).

## Review findings addressed

1. Corrected FLAG_CATEGORY dimensions; real dask-ms loading now has a regression test.
2. Added scientific MS hashes rather than relying on volatile table-file bytes.
3. Reject report destinations inside the common bundle and reject existing output paths.
4. Validate MS_VERSION and local subtable links, so redirected metadata cannot pass integrity checks.
5. Distinguish native import/Python forest resolution from loaded-kernel execution in both tooling and reports.

Ruff and whitespace checks pass. Runtime probe code also compiles with the
reference image's Python 3.10 interpreter. Registry and probe tools preserve
existing report directories rather than replacing evidence.

## Remaining work

- Run the native probe on a host permitting standard MeqTrees IPC, then validate
  its output on a disposable common-MS copy to finish #3.
- Acquire and validate the actual holography/eidos scientific beam inputs for
  the full 77-antenna case in #4.
- Implement the single Shinobi workflow (#5), then inter-engine equivalence
  (#6) and matched-accuracy performance measurements (#7).

No inter-engine equivalence or performance result is established by this change.
