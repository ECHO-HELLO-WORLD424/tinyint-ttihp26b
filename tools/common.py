# SPDX-FileCopyrightText: (c) 2026 ECHO-HELLO-WORLD424
# SPDX-License-Identifier: Apache-2.0
"""Shared definitions for the pre-silicon prediction tooling.

Everything here mirrors RTL in src/ and must stay synchronized:
  - tpv_pattern_gen.v (LFSR + operand decodes)
  - tpv_um_echoworld424_tpv.v (config word layout, frame/window sizes)
All units are ns / MHz / cycles unless stated otherwise.
"""

import os
import re

# --- Build/artifact identity -------------------------------------------------

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(REPO, "data")
ARTIFACTS = os.path.join(REPO, "artifacts")

# The final hardening run (commit 1e31757..., CI run 33839023290).
RUN_DIR = os.path.join(ARTIFACTS, "run-33839023290")
RUN_ID = "33839023290"
GIT_COMMIT = "1e31757e50080b19fa7642b8b9cd6822f64b1d11"

LL_IMAGE = "ghcr.io/librelane/librelane:3.0.5"  # tool-identical to CI gds job
CIEL_PDK_REV = "c4b8b4e5e7a05f375cca3815d51b3a37721fbf5c"

# The devcontainer's docker (docker-in-docker) daemon is reached directly
# from inside the container; from the host we go through docker exec into
# the devcontainer (auto-discovered by its image name, which starts with
# "vsc-<repo>-").
_DOCKER_ENV = None


def _devcontainer_name():
    import subprocess
    out = subprocess.run(
        ["docker", "ps", "--format", "{{.Names}} {{.Image}}"],
        capture_output=True, text=True).stdout
    for line in out.splitlines():
        name, image = (line.split(None, 1) + [""])[:2]
        if image.startswith("vsc-tinyint-ttihp26b-"):
            return name
    return None


def docker_prefix():
    global _DOCKER_ENV
    if _DOCKER_ENV is None:
        dc = None if os.path.exists("/.dockerenv") else _devcontainer_name()
        _DOCKER_ENV = ["docker", "exec", dc] if dc else []
    return _DOCKER_ENV


def docker_mount_args():
    """Bind-mount args for the LibreLane tool image. The inner daemon
    resolves sources in the devcontainer filesystem in both launch
    contexts, so the paths are the same from the host and inside."""
    return ["-v", "/workspaces/tinyint-ttihp26b:/work",
            "-v", "/home/vscode/ttsetup/pdk:/pdk:ro"]

# PDK Liberty files per corner, exactly the files the CI signoff STA reads
# (see artifacts/run-*/54-openroad-stapostpnr/*/sta.log for provenance).
# Container-absolute paths (the tools mount the ciel store at /pdk).
PDK_INNER = "/pdk/ciel/ihp-sg13g2/versions/" + CIEL_PDK_REV + "/ihp-sg13g2"
PDK_HOST = "/home/vscode/ttsetup/pdk"  # inside the devcontainer

CORNER_LIBS = {
    "nom_fast_1p32V_m40C": [
        "libs.ref/sg13g2_stdcell/lib/sg13g2_stdcell_fast_1p32V_m40C.lib",
        "libs.ref/sg13g2_io/lib/sg13g2_io_fast_1p32V_3p6V_m40C.lib",
    ],
    "nom_typ_1p20V_25C": [
        "libs.ref/sg13g2_stdcell/lib/sg13g2_stdcell_typ_1p20V_25C.lib",
        "libs.ref/sg13g2_io/lib/sg13g2_io_typ_1p2V_3p3V_25C.lib",
    ],
    "nom_slow_1p08V_125C": [
        "libs.ref/sg13g2_stdcell/lib/sg13g2_stdcell_slow_1p08V_125C.lib",
        "libs.ref/sg13g2_io/lib/sg13g2_io_slow_1p08V_3p0V_125C.lib",
    ],
}

# --- PVT corners (from the IHP LibreLane corner set) --------------------------

# name -> (voltage V, temperature C)
CORNERS = [
    ("nom_fast_1p32V_m40C", 1.32, -40),
    ("nom_typ_1p20V_25C", 1.20, 25),
    ("nom_slow_1p08V_125C", 1.08, 125),
]
CORNER_NAMES = [c[0] for c in CORNERS]

def lib_path(corner):
    return os.path.join(
        RUN_DIR, "lib", corner, f"tt_um_echoworld424_tpv__{corner}.lib"
    )

def spef_path():
    return os.path.join(RUN_DIR, "spef", "nom", "tt_um_echoworld424_tpv.nom.spef")

def netlist_path():
    return os.path.join(RUN_DIR, "nl", "tt_um_echoworld424_tpv.nl.v")

def sdc_path():
    return os.path.join(REPO, "src", "pnr.sdc")

# --- Protocol constants (mirror RTL) -----------------------------------------

FRAME_CYCLES = 19          # FRAME_LAST = 18 -> cycles 0..18 per operation
CAPTURE_CYCLE = 0          # result_reg captures on the chk_start edge
CLK_PERIOD_NS = 20.0       # 50 MHz board ceiling (pnr.sdc create_clock)

# Measurement matrix (predeclared before silicon): segment delay-bank taps
# {seg0,seg1,seg2,seg3} and pattern classes to be swept on silicon.
SEG_CONFIGS = [
    (0, 0, 0, 0),  # all banks at tap 0 (pure ripple + mux delay)
    (1, 1, 1, 1),  # 16 inverter pairs per bank
    (2, 2, 2, 2),  # 32 pairs per bank
    (3, 3, 3, 3),  # 48 pairs per bank (longest)
    (3, 0, 0, 0),  # leading bank long
    (0, 0, 0, 3),  # trailing bank long (includes final carry-out bank)
    (2, 1, 3, 0),  # mixed (as used in the cocotb functional sweep)
    (1, 2, 0, 3),  # mixed, opposite phase
]
PATTERNS = [0, 1, 2, 3]  # 0=PRBS 1=WORST 2=ALT 3=HOLD
PATTERN_NAMES = ["prbs", "worst", "alt", "hold"]

# Canary window sizes (win_sel -> number of clk cycles in the window).
# win_cnt counts 0..thresh and freezes win_done at the thresh+1-th enabled edge,
# so the effective window is thresh+1 cycles.
WINDOW_CYCLES = {0: 256, 1: 1024, 2: 4096, 3: 16384}

# --- Pattern generator model (mirrors tpv_pattern_gen.v) ----------------------

def lfsr_step(s):
    fb = ((s >> 15) ^ (s >> 13) ^ (s >> 12) ^ (s >> 10)) & 1
    return ((s << 1) | fb) & 0xFFFF

def lfsr_next(s):
    """Combinational next state, exactly the RTL lfsr_nxt wire."""
    return lfsr_step(s)

def decode_operands(sel, lfsr_reg, idx):
    """Operand triple presented to the DUT for a given register state.

    Returns (a, b, cin) as the RTL decode computes them combinationally.
    For sel=0 the decode reflects lfsr_nxt (the value the register will take
    at the next load edge), matching tpv_pattern_gen.v.
    """
    if sel == 0:
        n = lfsr_next(lfsr_reg)
        a = n
        b = ((n & 0x7F) << 9) | (n >> 7)
        cin = ((n >> 15) ^ (n >> 7) ^ (n >> 3)) & 1
        return a, b, cin
    if sel == 1:
        pairs = [(0xFFFF, 0x0001, 0), (0xFFFF, 0xFFFF, 1),
                 (0x0FFF, 0x0001, 0), (0x8000, 0x8000, 1)]
        return pairs[idx & 3]
    if sel == 2:
        if idx & 1:
            return 0xAAAA, 0x5555, 0
        return 0x2222, 0x4444, 0
    return 0, 0, 0

def pattern_vectors(sel, n_ops=8):
    """The first n_ops operand triples applied at capture, in order.

    The first compared op (P_0) is captured in the cycle after the first load:
    for sel=0 the decode state is one LFSR advance past the seed (decoding to
    two advances from ACE1), and for sel=1/2 idx has already advanced to 1
    (first WORST op is 0xFFFF+0xFFFF+1, as asserted in test/test.py).
    """
    lfsr = lfsr_next(0xACE1)  # register state after the first load
    idx = 1 if sel in (1, 2) else 0
    ops = []
    for _ in range(n_ops):
        ops.append(decode_operands(sel, lfsr, idx))
        lfsr = lfsr_next(lfsr)
        if sel in (1, 2):
            idx = (idx + 1) & 3
    return ops

# --- Carry-chain sensitization ------------------------------------------------

def carry_source_bit(a, b, cin, k):
    """Dependency boundary for sum bit k under vector (a,b,cin): the largest
    j < k such that sum[k] depends on a_j/b_j, or -1 if it depends on cin.
    (Walking down from k-1: a generate bit or a non-propagating bit ends the
    transitive carry dependence.)"""
    j = k - 1 if k < 16 else 15
    while j >= 0:
        p = ((a >> j) ^ (b >> j)) & 1
        g = ((a >> j) & (b >> j)) & 1
        if g or not p:
            return j
        j -= 1
    return -1  # depends on cin only

def carry_chain_length(a, b, cin, k):
    """Number of ripple stages whose delay must settle sum bit k for this
    vector: bits from the dependency boundary (or cin) up to bit k."""
    k = min(k, 16)
    src = carry_source_bit(a, b, cin, k)
    return (k + 1) if src < 0 else (k - src + 1)

def sensitizing_vector(sel, endpoint_bit, n_ops=64):
    """Pick, among the pattern's operand vectors (first n_ops of a run), the
    one whose carry chain to `endpoint_bit` (bit index 0..16, 16=cout) is
    longest -> the vector that maximizes exercised delay to this capture bit.
    64 ops bound the search to what a multi-thousand-op silicon run is
    statistically certain to exceed (LFSR ops are deterministic and repeat
    with period 2^16-1 for sel=0; idx classes cycle with period 4 for 1/2)."""
    best, best_len = None, -1
    for a, b, cin in pattern_vectors(sel, n_ops):
        L = carry_chain_length(a, b, cin, endpoint_bit)
        if L > best_len:
            best, best_len = (a, b, cin), L
    return best, best_len

# --- STA report parsing -------------------------------------------------------

RPT_START = re.compile(r"^Startpoint:\s+(\S+)", re.M)
RPT_END = re.compile(r"^Endpoint:\s+(\S+)", re.M)
RPT_ARRIVAL = re.compile(r"^\s+([\d.]+)\s+data arrival time", re.M)
RPT_REQUIRED = re.compile(r"^\s+([\d.]+)\s+data required time", re.M)
RPT_SLACK = re.compile(r"^\s+([-\d.]+)\s+slack \((MET|VIOLATED)\)", re.M)
RPT_CELLROW = re.compile(
    r"^\s+(?:[\d.]+\s+){2,4}([\d.]+)\s+([\d.]+)\s+(\S)\s+(\S+)\s+\((\S+)\)",
    re.M,
)
FLOAT_RE = re.compile(r"[-\d.]+")

def parse_path_block(block):
    """Parse one report_checks block into a dict (or None)."""
    out = {}
    m = RPT_START.search(block)
    if not m:
        return None
    out["startpoint"] = m.group(1)
    m = RPT_END.search(block)
    out["endpoint"] = m.group(1) if m else None
    m = RPT_ARRIVAL.search(block)
    out["arrival_ns"] = float(m.group(1)) if m else None
    m = RPT_REQUIRED.search(block)
    out["required_ns"] = float(m.group(1)) if m else None
    m = RPT_SLACK.search(block)
    if m:
        out["slack_ns"] = float(m.group(1))
        out["slack_met"] = m.group(2) == "MET"
    else:
        out["slack_ns"] = None
        out["slack_met"] = None
    # data-path delay = data arrival time - time at the startpoint /CLK pin
    # (i.e. launch clock edge to capture D pin, including clk->Q).
    # With propagated clocks the launch arrival includes the clock network;
    # the number before the edge marker on the startpoint /CLK row is that
    # arrival, so the difference is the pure data-path delay.
    lines = block.splitlines()
    sp_idx = next(i for i, ln in enumerate(lines)
                  if ln.startswith("Startpoint:"))
    clk_t = None
    for ln in lines[sp_idx + 1:]:
        toks = ln.split()
        edge_i = next((i for i, t in enumerate(toks) if t in ("^", "v")), None)
        if edge_i is not None and any("/CLK" in t for t in toks[edge_i + 1:]):
            nums = [t for t in toks[:edge_i] if re.fullmatch(r"[-\d.]+", t)]
            if nums:
                clk_t = float(nums[-1])
                break
        if any(t.endswith("/Q") for t in toks):
            break
    out["path_delay_ns"] = (
        out["arrival_ns"] - clk_t
        if out["arrival_ns"] is not None and clk_t is not None else None)
    # cells along the path (in order): instance/pin and cell type
    cells = []
    for line in lines:
        m = RPT_CELLROW.match(line)
        if m:
            cells.append({"pin": m.group(4), "cell": m.group(5),
                          "delay_ns": float(m.group(1)),
                          "arrival_ns": float(m.group(2))})
    out["cells"] = cells
    return out

def parse_case_report(text):
    """Split a per-corner report into {case_key: {r2r:..., global:...}}.

    Blocks are delimited by explicit markers emitted by the Tcl flow:
      ==CASE <key>   starts a case
      ES-R2R         runtime startpoint -> result_reg path report follows
      ES-GLOBAL      worst path to result_reg (any startpoint) follows
      ES-END         closes both reports of the case
    """
    cases = {}
    cur_key, cur, kind = None, None, None
    for line in text.splitlines():
        if line.startswith("==CASE "):
            cur_key = line[len("==CASE "):].strip()
            cases[cur_key] = {}
            cur, kind = None, None
            continue
        if line.startswith("ES-R2R"):
            cur, kind = [], "r2r"
            continue
        if line.startswith("ES-GLOBAL"):
            if cur is not None:
                cases[cur_key][kind] = "\n".join(cur)
            cur, kind = [], "global"
            continue
        if line.startswith("ES-END") and cur is not None:
            cases[cur_key][kind] = "\n".join(cur)
            cur, kind = None, None
            continue
        if cur is not None:
            cur.append(line)
    return {k: {kk: parse_path_block(vv) for kk, vv in v.items()}
            for k, v in cases.items()}

def predicted_fmax_mhz(slack_ns, clk_period_ns=CLK_PERIOD_NS):
    """Clock period at which the case-analyzed capture path first fails setup,
    holding clock-tree delays, setup and uncertainty at the analyzed corner:
    T_fail = T_clk - slack (linear translation of slack to period)."""
    if slack_ns is None:
        return None
    return 1e3 / (clk_period_ns - slack_ns)
