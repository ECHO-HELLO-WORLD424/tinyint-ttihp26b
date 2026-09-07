# CI timing-closure attempts

## 2026-09-08: diagnosis and alternatives

Baseline: `8770804556f84b637ae8625a754877cd0f3a568a`, branch
`proposal-canary-dev`. [CI run 34156759472](https://github.com/ECHO-HELLO-WORLD424/tinyint-ttihp26b/actions/runs/34156759472)
completed hardening but exited 1 at the deferred typical-corner setup checker.
RTL and docs passed; precheck, functional GL and viewer were skipped. This is
separate from the preceding run's HTTPS timeout.

The DUT launches on a rising edge and captures on the next falling edge. At
50 MHz/50% duty it has 10 ns, while nominal extracted evidence requires about
16 ns. Its intended failure near 31 MHz and an error-free 50 MHz specification
are incompatible for the same mode and waveform.

### Sources consulted

- [LibreLane timing closure](https://librelane.readthedocs.io/en/stable/usage/timing_closure/index.html):
  constraints represent operating intent; when operating frequency is flexible,
  a longer period can resolve setup, while hold still requires checking.
- [Tiny Tapeout clock specification](https://tinytapeout.com/specs/clock/):
  clock frequency is externally configurable. Its pad and frequency statements
  reference SKY130 and do not certify the IHP26b board's limits.
- [Published delay-chain experiment](https://www.tinytapeout.com/chips/ttsky25a/tt_um_delaychain):
  search metadata describes setup-violation experiments with a 1 MHz declared
  clock. This is precedent only, not evidence of IHP26b acceptance policy.

### Candidate decisions

1. Retry unchanged CI: already attempted; confirms deterministic setup failure.
2. Disable setup checking or false-path the DUT: rejected. This hides a real,
   sensitizable path and provides no valid operating specification.
3. Add multicycle constraints without changing capture: rejected. Actual capture
   is still the immediate falling edge, regardless of the 19-cycle frame.
4. Declare a conservative normal operating clock (candidate 10 MHz), retain
   10–50 MHz as intentional experimental overclocking: under consideration.
   Metadata, signoff and documentation must agree. All synchronous paths remain
   checked at the declared clock, and control must separately remain valid at
   the experimental ceiling. User preference requested before changing the
   existing 50 MHz submitted specification. Fresh hardening is required.
5. Retain guaranteed 50 MHz using a separately defined safe measurement mode or
   an independently controlled sampling interface: architectural alternative;
   requires new protocol, RTL, timing and physical verification. Not attempted.

No candidate has yet been declared verified or submission-ready.

## Authorized candidate: 10 MHz normal operation

User approved verification of the lower declared clock. Physical source revision:
`7b20196bb74195649679fae6313a891712e87458`. Changed `info.yaml` to
10,000,000 Hz, `CLOCK_PERIOD` to 100 ns and the SDC waveform to {0,50} ns.
RTL, IO delay/load, uncertainty and all DUT setup/hold checks remain intact.
No DUT false path, multicycle path or setup-checker suppression was added.

Fresh devcontainer build `src/runs/dev-safe10` used LibreLane 3.0.5 and the
same PDK revision as the earlier build. It **completed with exit 0**.
Setup slack fast/typical/slow: +38.8156/+33.7141/+24.6024 ns.
Hold slack: +0.1315/+0.2189/+0.3769 ns. Routing DRC, Magic DRC, LVS and
antenna: zero violations. Utilization remains 72.5284%.

The first verification launcher referenced a temporary script that was not
visible inside the devcontainer and exited 127. No design tool ran in that
attempt. Retried from the shared workspace using `tools/verify_safe10.sh`.
Experimental analysis explicitly uses 20 ns/50% duty independently of the
100 ns submission constraint. Outputs are isolated in `data/safe10/` so the
previous half-cycle and original full-cycle datasets remain unchanged.

### Verification result

- RTL: 13 pass, zero failures.
- Functional GL from the new routed netlist: 9 pass, 4 intentional skips.
- Tiny Tapeout precheck: 10 pass, including KLayout DRC.
- Structure: all 384 DUT bank inverters/taps, both RO loops and 17 falling-edge
  capture flops preserved.
- Fresh case-analyzed STA: 96 rows, minimum other-control slack +6.26 ns at
  50 MHz. Longest-path nominal boundary 30.998 MHz.
- Fresh IOPATH SDF sweep: 23 main points; nominal last fail 32 ns and first pass
  34 ns. Equal-aperture/different-duty validation passes.
- RO model: 24 regenerated rows; prediction package: 288 regenerated rows.
- Manifest: `data/safe10/verification/local-build-manifest.json`; physical input
  contents verified against `7b20196`. Every final view is hashed. Physical
  artifacts remain in ignored `src/runs/dev-safe10/final/`.

The candidate **passes local hardening and verification** and retains the intended
ambient failure experiment. This is not yet a statement of portal acceptance.
RO transient validation and actual board operating limits remain open research
items. Intentional overclocking results are not guaranteed error-free operation.

Reproduce inside the devcontainer: generate the TT merged configuration, then
run LibreLane 3.0.5 with `--run-tag dev-safe10` and the pinned PDK as in
`docs/halfcycle-development-validation.md` (use a fresh tag for another build).
Run `bash tools/verify_safe10.sh` for the post-build suite. That script explicitly
selects the new build and dataset using `TPV_*` environment variables; default
analysis commands still select the archived half-cycle dataset. It expects the
build's RTL regression XML in the verification directory.

Canonical GitHub CI: pending push of this verification/documentation revision.

### Submission-tree correction

After the verification commit, a tree check detected stale staged copies of
four files (`info.yaml`, `src/config.json`, `src/pnr.sdc`, `tools/common.py`).
The working files and tested build were correct, but intermediate commit
`b08b46c` had restored their older values. Commit `e64c842` corrects the tree;
`git diff 7b20196 HEAD -- src info.yaml tools/common.py` is empty. The local
verification remains applicable. Any CI on `b08b46c` is superseded and must not
be used as evidence for the 10 MHz candidate.

## Canonical CI result: all green

Commit **`b9f03f798978840c8bdc2bb574877408e0f33f4c`**:
[GDS workflow 34158224984](https://github.com/ECHO-HELLO-WORLD424/tinyint-ttihp26b/actions/runs/34158224984)
passed all four jobs: GDS, precheck, functional GL and viewer. Separate
[RTL tests](https://github.com/ECHO-HELLO-WORLD424/tinyint-ttihp26b/actions/runs/34158224983)
and [docs](https://github.com/ECHO-HELLO-WORLD424/tinyint-ttihp26b/actions/runs/34158225032)
also passed. The `tt_submission` artifact is ID `10031816458` (910,283 bytes
reported by GitHub). This resolves the CI setup failure for the honestly declared
10 MHz normal-operation specification. Portal acceptance remains to be checked
by the user; experimental operation above 10 MHz remains intentionally outside
the error-free timing specification.

## Merged into proposal-canary (2026-09-08)

The verified 10 MHz candidate was fast-forward merged from
`proposal-canary-dev` into `proposal-canary` (tip
`a35f5018614fdcce1a52b0c7a0f717eb89175949`). Branch references in the log
entries above refer to the development period before the merge. Fresh CI on
the merged branch supersedes nothing here; portal acceptance remains to be
checked by the user.
