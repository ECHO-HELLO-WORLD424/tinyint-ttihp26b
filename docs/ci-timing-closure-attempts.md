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
