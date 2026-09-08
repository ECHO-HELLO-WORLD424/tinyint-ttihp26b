#!/usr/bin/env python3
"""Generate every figure used by docs/pre-silicon-v2-blog.md.

Replots the archived ``data/safe10`` evidence only; it runs no HDL, no timing
analysis and no simulation. Run it with the devcontainer Python, which pins
matplotlib 3.10.6:

    docker run --rm -v "$PWD":/work -w /work <devcontainer-image> \
      bash -lc 'source /ttsetup/venv/bin/activate && python tools/plot_v2_blog.py'

Outputs land in ``docs/figures/v2/`` next to ``provenance.json``, which records
the input hashes and tool versions.
"""
import csv
import hashlib
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LogNorm
from matplotlib.patches import Rectangle

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/safe10"
OUT = ROOT / "docs/figures/v2"
OUT.mkdir(parents=True, exist_ok=True)

RUN_ID = "local-dev-safe10"
BUILD_COMMIT = "7b20196bb74195649679fae6313a891712e87458"

# Keep SVG labels as real text so figures stay searchable and accessible.
plt.rcParams["svg.fonttype"] = "none"

# ----------------------------------------------------------------------------
# Shared style
# ----------------------------------------------------------------------------
C_FAST = "#167d9a"
C_TYP = "#c16720"
C_SLOW = "#7452a3"
C_ACCENT = "#b03060"
SWEEP_LO, SWEEP_HI = 10.0, 50.0
FILL = "#eef2f6"
GRID = dict(axis="y", alpha=0.18)
CORNERS = [
    ("nom_fast_1p32V_m40C", "Fast corner\n1.32 V · −40 °C", C_FAST),
    ("nom_typ_1p20V_25C", "Typical corner\n1.20 V · 25 °C", C_TYP),
    ("nom_slow_1p08V_125C", "Slow corner\n1.08 V · 125 °C", C_SLOW),
]
LADDER = ["0000", "1111", "2222", "3333"]


def tidy(ax):
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(**GRID)


def read(name):
    with (DATA / name).open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert {r["run_id"] for r in rows} == {RUN_ID}, name
    assert {r["git_commit"] for r in rows} == {BUILD_COMMIT}, name
    return rows


sta = read("experiment_sta.csv")
sdf = read("sdfsim.csv")
ro = read("ro_predict.csv")
aperture = json.loads((DATA / "verification/aperture-check.json").read_text())
saved = []


def save(fig, stem):
    fig.savefig(OUT / f"{stem}.png", dpi=180)
    fig.savefig(OUT / f"{stem}.svg")
    plt.close(fig)
    saved.append(f"{stem}.png")
    saved.append(f"{stem}.svg")
    print("wrote", stem)


def fmax(corner, pattern, seg):
    row, = [r for r in sta if r["corner"] == corner and r["pat_name"] == pattern
            and all(r[f"seg{i}"] == str(seg) for i in range(4))]
    return float(row["predicted_fmax_mhz"])


def fmax_cfg(corner, pattern, segs):
    row, = [r for r in sta if r["corner"] == corner and r["pat_name"] == pattern
            and all(r[f"seg{i}"] == str(s) for i, s in enumerate(segs))]
    return float(row["predicted_fmax_mhz"])


# ----------------------------------------------------------------------------
# 1. boundary-ruler: the one-number hook
# ----------------------------------------------------------------------------
def boundary_ruler():
    nominal = fmax("nom_typ_1p20V_25C", "worst", 3)          # 30.998 MHz
    sdf_rows = [r for r in sdf if r["corner"] == "nom_typ_1p20V_25C"
                and r["pattern"] == "worst" and r["segs"] == "3333"
                and float(r["capture_duty"]) == 0.5]
    # Lowest frequency that still fails, and highest that still passes.
    fails = min(float(r["freq_mhz"]) for r in sdf_rows if int(r["err_cnt"]) > 0)
    passes = max(float(r["freq_mhz"]) for r in sdf_rows if int(r["err_cnt"]) == 0)

    fig, ax = plt.subplots(figsize=(11, 3.4), layout="constrained")
    ax.add_patch(Rectangle((0, 0.42), 60, 0.16, color="#e8f2e8"))
    ax.add_patch(Rectangle((nominal, 0.42), 60 - nominal, 0.16, color="#f7e4e4"))
    ax.axvspan(SWEEP_LO, SWEEP_HI, color=FILL, zorder=-2)
    ax.text((SWEEP_LO + SWEEP_HI) / 2, 0.66, "planned measurement sweep: 10–50 MHz",
            ha="center", fontsize=9, color="#4a5560")
    ax.plot([nominal, nominal], [0.30, 0.70], color=C_TYP, lw=2.4)
    ax.annotate(f"static timing analysis predicts\nfirst failures at {nominal:.1f} MHz",
                (nominal, 0.70), xytext=(nominal - 4, 0.88), ha="right", fontsize=9.5,
                color=C_TYP, arrowprops=dict(arrowstyle="-", color=C_TYP, lw=1))
    ax.plot([passes, fails], [0.50, 0.50], color=C_FAST, lw=6, solid_capstyle="butt",
            alpha=.85)
    ax.annotate(f"timed gate-level simulation\npasses at {passes:.1f}, fails at {fails:.1f} MHz",
                (fails, 0.50), xytext=(fails + 1.2, 0.26), ha="left", fontsize=9.5,
                color=C_FAST, arrowprops=dict(arrowstyle="-", color=C_FAST, lw=1))
    ax.text(58, 0.50, "silicon\nunknown →", ha="right", va="center", fontsize=10,
            color="#3a4248", style="italic")
    ax.text(2, 0.50, "chip works", fontsize=10, color="#2f6b3f", va="center")
    ax.set(xlim=(0, 60), ylim=(0, 1.0), xlabel="clock frequency (MHz)")
    ax.set_yticks([])
    ax.set_title("Two pre-silicon predictions, one open question", fontsize=13,
                 fontweight="bold")
    tidy(ax)
    save(fig, "boundary-ruler")


# ----------------------------------------------------------------------------
# 2. frame-timing: how the chip samples a late answer
# ----------------------------------------------------------------------------
def frame_timing():
    fig, (top, bottom) = plt.subplots(
        2, 1, figsize=(11, 4.4), layout="constrained",
        gridspec_kw=dict(height_ratios=[1.05, 1.0]))

    # -- top: one clock period, HIGH time is the aperture
    t, y = [0, 0, 0.5, 0.5, 1, 1, 1.5, 1.5, 2], [0, 1, 1, 0, 0, 1, 1, 0, 0]
    top.plot(t, y, color="#2f3a42", lw=2)
    top.fill_between([0, 0.5], 0, 1, color=C_TYP, alpha=.14)
    top.annotate("", (0.5, 1.12), (0, 1.12),
                 arrowprops=dict(arrowstyle="<->", color=C_TYP, lw=1.2))
    top.text(0.25, 1.17, "aperture = clock HIGH time", ha="center", fontsize=9.5,
             color=C_TYP)
    top.annotate("↑ new operands\n   launched", (0, 1), xytext=(-0.04, 1.35),
                 ha="left", fontsize=9, color="#2f6b3f",
                 arrowprops=dict(arrowstyle="->", color="#2f6b3f", lw=1))
    top.annotate("↓ answer captured\n   exactly once", (0.5, 0), xytext=(0.62, -0.62),
                 ha="left", fontsize=9, color=C_ACCENT,
                 arrowprops=dict(arrowstyle="->", color=C_ACCENT, lw=1))
    top.annotate("↓ late answer is\n   ignored, sample held", (1.5, 0), xytext=(1.62, -0.62),
                 ha="left", fontsize=9, color="#5a6670",
                 arrowprops=dict(arrowstyle="->", color="#5a6670", lw=1))
    top.set(xlim=(-0.08, 2.1), ylim=(-0.85, 1.5), yticks=[0, 1],
            yticklabels=["0", "1"])
    top.set_title("A late answer cannot hide: the sample is frozen at the falling edge",
                  fontsize=12.5, fontweight="bold")
    top.set_xlabel("time (clock periods)")
    tidy(top)
    top.grid(False)

    # -- bottom: one 19-cycle frame
    bottom.hlines(0, 0, 19, color="#c8d2da", lw=2)
    for c in range(20):
        bottom.plot([c, c], [-0.09, 0.09], color="#8b98a3", lw=1)
    bottom.text(19.35, 0, "next\nframe", fontsize=8.5, va="center", color="#6b7780")
    events = [
        (0, "operands launch", "#2f6b3f", 0.55),
        (0.5, "capture", C_ACCENT, 0.30),
        (18, "compare frozen sample\nwith reference adder", C_FAST, -0.55),
    ]
    for x, label, color, dy in events:
        bottom.plot([x], [0], "o", color=color, ms=8, zorder=3)
        bottom.annotate(label, (x, 0), xytext=(x, dy), ha="center",
                        va="center" if dy < 0 else "center", fontsize=9, color=color,
                        arrowprops=dict(arrowstyle="-", color=color, lw=1))
    bottom.text(9.5, -0.16, "one frame = 19 clock cycles", ha="center", fontsize=9.5,
                color="#4a5560")
    bottom.set(xlim=(-0.8, 20.6), ylim=(-0.85, 0.85), yticks=[])
    bottom.set_xlabel("clock cycle within the measurement frame")
    tidy(bottom)
    bottom.grid(False)
    save(fig, "frame-timing")


# ----------------------------------------------------------------------------
# 3. timing-boundary: STA ladder + timed-simulation staircase
# ----------------------------------------------------------------------------
def timing_boundary():
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.7), layout="constrained")

    ax = axes[0]
    xs = [0, 16, 32, 48]
    for corner, label, color in CORNERS:
        ys = [fmax(corner, "worst", seg) for seg in range(4)]
        ax.plot(xs, ys, "o-", color=color, label=label)
        ax.annotate(f"{ys[-1]:.1f}", (xs[-1], ys[-1]), xytext=(5, -3),
                    textcoords="offset points", fontsize=8.5, color=color)
    ax.axhspan(SWEEP_LO, SWEEP_HI, color=FILL, zorder=-1)
    ax.axhline(SWEEP_HI, color="#65737e", linestyle="--", linewidth=1)
    ax.text(47, SWEEP_HI * 1.06, "50 MHz board ceiling", ha="right", fontsize=8.5,
            color="#4a5560")
    ax.text(1, 17, "10–50 MHz planned sweep", fontsize=8.5, color="#4a5560")
    ax.set(xticks=xs, xticklabels=["0", "16", "32", "48"], yscale="log",
           xlabel="extra inverter pairs per adder segment",
           ylabel="predicted first-failure frequency (MHz)",
           title="More deliberate delay\nbrings failure into reach",
           ylim=(14, 160))
    ax.legend(frameon=False, fontsize=8, loc="upper right")
    tidy(ax)

    ax = axes[1]
    for corner, label, color in CORNERS:
        rows = sorted([r for r in sdf if r["corner"] == corner
                       and r["pattern"] == "worst" and r["segs"] == "3333"
                       and float(r["capture_duty"]) == 0.5],
                      key=lambda r: float(r["period_ns"]))
        xs = [float(r["period_ns"]) for r in rows]
        ys = [100 * int(r["err_cnt"]) / int(r["n_compared"]) for r in rows]
        ax.plot(xs, ys, "o-", color=color, label=label.split("\n")[0], ms=5)
        ax.axvline(1000 / fmax(corner, "worst", 3), color=color, linestyle=":",
                   linewidth=1.2)
    ax.set(xlabel="clock period at 50% duty (ns)",
           ylabel="errors / completed comparisons (%)",
           title="Timed simulation fails\nnear the predicted period",
           ylim=(-2, 30))
    ax.legend(frameon=False, fontsize=8, loc="center right")
    tidy(ax)
    fig.suptitle("First-failure boundary · build local-dev-safe10", fontsize=13.5,
                 fontweight="bold")
    save(fig, "timing-boundary")


# ----------------------------------------------------------------------------
# 4. aperture: HIGH time, not period, sets the boundary
# ----------------------------------------------------------------------------
def aperture_plot():
    fig, ax = plt.subplots(figsize=(9.5, 4.3), layout="constrained")
    nominal = [r for r in sdf if r["corner"] == "nom_typ_1p20V_25C"
               and r["pattern"] == "worst" and r["segs"] == "3333"
               and float(r["capture_duty"]) == 0.5]
    xs = [float(r["high_time_ns"]) for r in nominal]
    ys = [int(r["err_cnt"]) for r in nominal]
    ax.plot(xs, ys, "o-", color=C_TYP, ms=7, label="50% duty sweep")

    duty_x = [s["high_time_ns"] for s in aperture["sdf"]]
    duty_y = [s["err_cnt"] for s in aperture["sdf"]]
    ax.plot([x + 0.12 for x in duty_x], duty_y, "s", mfc="none", mec=C_FAST,
            ms=11, mew=1.6, label="same HIGH time at 40% / 50% / 60% duty")

    req = aperture["sta"][0]["required_high_ns"]
    ax.axvline(req, color=C_ACCENT, linestyle="--", lw=1.4)
    ax.annotate(f"STA: {req:.2f} ns of HIGH time required",
                (req, 44), xytext=(req + 0.35, 46), fontsize=9, color=C_ACCENT,
                arrowprops=dict(arrowstyle="-", color=C_ACCENT, lw=1))
    ax.annotate("all six duty-cycle cases land\non the same HIGH-time boundary",
                (14.1, 49), xytext=(15.4, 30), fontsize=9, color="#4a5560",
                arrowprops=dict(arrowstyle="->", color="#8b98a3", lw=1))
    ax.set(xlabel="clock HIGH time at the capture edge (ns)",
           ylabel="errors per 199 completed comparisons", ylim=(-4, 56),
           xlim=(8.5, 22))
    ax.legend(frameon=False, fontsize=9, loc="center right")
    ax.set_title("The chip measures the clock's HIGH time, not just its frequency",
                 fontsize=12.5, fontweight="bold")
    tidy(ax)
    save(fig, "aperture")


# ----------------------------------------------------------------------------
# 5. canary: modeled speed and the counter wrap limit
# ----------------------------------------------------------------------------
def canary():
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.6), layout="constrained")
    styles = {"ro_gen": ("generic canary", "-"), "ro_mat": ("matched canary", "--")}

    ax = axes[0]
    for corner, label, color in CORNERS:
        for can, (cname, ls) in styles.items():
            rows = sorted([r for r in ro if r["corner"] == corner and r["canary"] == can],
                          key=lambda r: int(r["can_sel"]))
            ax.plot([int(r["can_sel"]) for r in rows],
                    [float(r["f_osc_mhz"]) for r in rows], ls, marker="o", ms=4,
                    color=color, label=f"{label.split(chr(10))[0]} · {cname}")
    ax.set(xticks=[0, 1, 2, 3], yscale="log",
           xlabel="canary delay selection",
           ylabel="modeled oscillation frequency (MHz)",
           title="Canaries slow down with\ntheir own delay setting")
    ax.legend(frameon=False, fontsize=7.4, ncol=2, loc="lower left")
    tidy(ax)

    ax = axes[1]
    windows = [256, 1024, 4096, 16384]
    for corner, label, color in CORNERS:
        for can, (cname, ls) in styles.items():
            row, = [r for r in ro if r["corner"] == corner and r["canary"] == can
                    and r["can_sel"] == "3"]
            ys = [int(row[f"count_win{i}"]) for i in range(4)]
            ax.plot(windows, ys, ls, marker="o", ms=4, color=color,
                    label=f"{label.split(chr(10))[0]} · {cname}")
            over = [w for w, v in zip(windows, ys) if v > 65536]
            if over:
                ax.plot(over, [v for v in ys if v > 65536], "x", color=color, ms=7,
                        mew=1.8)
    ax.axhline(65536, color="#5a6670", linestyle="--", lw=1.2)
    ax.text(280, 42000, "16-bit counter limit — counts above this wrap silently",
            fontsize=8.5, color="#5a6670")
    ax.set(xscale="log", yscale="log", xticks=windows,
           xticklabels=["256", "1,024", "4,096", "16,384"],
           xlabel="canary window (clock cycles)",
           ylabel="predicted edges per window",
           title="Longer windows overflow\nthe counters")
    ax.legend(frameon=False, fontsize=7.4, ncol=2, loc="upper left")
    tidy(ax)
    fig.suptitle("Two on-chip speed sensors at delay selection 3", fontsize=13.5,
                 fontweight="bold")
    save(fig, "canary")


# ----------------------------------------------------------------------------
# 6. sta-matrix: every one of the 96 predicted boundaries
# ----------------------------------------------------------------------------
def sta_matrix():
    patterns = [("worst", "carry-heavy"), ("prbs", "PRBS"),
                ("alt", "carry-free"), ("hold", "static hold")]
    configs = ["0000", "1111", "2222", "3333", "3000", "0003", "2130", "1203"]
    rows, labels = [], []
    for corner, label, _ in CORNERS:
        for cfg in configs:
            segs = [int(c) for c in cfg]
            cells = []
            for pat, _ in patterns:
                try:
                    cells.append(fmax_cfg(corner, pat, segs))
                except ValueError:
                    cells.append(float("nan"))
            rows.append(cells)
            labels.append(f"{label.split(chr(10))[0].replace(' corner', '')} · {cfg}")

    fig, ax = plt.subplots(figsize=(11.5, 8.8), layout="constrained")
    im = ax.imshow(rows, cmap="viridis", norm=LogNorm(vmin=19, vmax=440),
                   aspect="auto")
    for i, row in enumerate(rows):
        for j, v in enumerate(row):
            if v != v:
                ax.text(j, i, "n/a", ha="center", va="center", fontsize=8, color="#d9d9d9")
            else:
                ax.text(j, i, f"{v:.0f}", ha="center", va="center", fontsize=8,
                        color="white" if v < 90 else "black")
    ax.set(xticks=range(len(patterns)),
           xticklabels=[n for _, n in patterns],
           yticks=range(len(rows)), yticklabels=labels)
    ax.set_title("All 96 predicted first-failure frequencies (MHz)\n"
                 "STA, 8 delay configurations × 4 workloads × 3 corners",
                 fontsize=11.5, fontweight="bold")
    ax.tick_params(length=0)
    for spine in ax.spines.values():
        spine.set_visible(False)
    fig.colorbar(im, ax=ax, shrink=.6, label="predicted boundary (MHz)")
    save(fig, "sta-matrix")


boundary_ruler()
frame_timing()
timing_boundary()
aperture_plot()
canary()
sta_matrix()

manifest = {
    "run_id": RUN_ID,
    "build_commit": BUILD_COMMIT,
    "python_version": sys.version.split()[0],
    "matplotlib_version": matplotlib.__version__,
    "figures": sorted(saved),
    "inputs_sha256": {
        str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in [DATA / "experiment_sta.csv", DATA / "sdfsim.csv",
                  DATA / "ro_predict.csv",
                  DATA / "verification/aperture-check.json"]
    },
    "note": ("Replots archived data only; no new HDL, timing analysis or simulation. "
             "The boundary ruler and frame-timing panels are schematic. The timed "
             "simulation omits interconnect delays and flip-flop timing checks."),
}
(OUT / "provenance.json").write_text(json.dumps(manifest, indent=2) + "\n")
print("wrote provenance.json")
