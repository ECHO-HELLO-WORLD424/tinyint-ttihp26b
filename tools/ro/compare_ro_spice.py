#!/usr/bin/env python3
"""Compare extracted RO transient (SPICE) results against the broken-loop STA
prediction and emit the analysis dataset + plots.

Inputs:
  data/safe10/ro_predict.csv   broken-loop extracted STA prediction (24 rows)
  <spice_dir>/spice_ro.csv     ngspice transient results (24 rows)

Outputs (written to data/safe10/spice/):
  ro_spice_vs_sta.csv          per-case comparison
  ro_spice_vs_sta.json         same, with provenance and summary statistics
  ro_spice_frequency.png       predicted vs simulated f_osc, per canary
  ro_spice_ratio.png           SPICE/STA ratio per case, per canary

Method note (must stay in the report): the extracted SPICE netlist used here is
a *cell-level* extraction.  Magic's spiceextraction produces transistor-level
cell instances with cell-internal parasitics but no wire RC, while the STA
prediction includes the SPEF wire parasitics.  The two numbers are therefore
not expected to agree exactly, and the wire share of the predicted loop delay
is reported per case to make that explicit.
"""

import argparse
import csv
import json
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def read_csv(path):
    with open(path) as fh:
        return list(csv.DictReader(fh))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sta", default="data/safe10/ro_predict.csv")
    ap.add_argument("--spice", required=True, help="sweep spice_ro.csv")
    ap.add_argument("--outdir", default="data/safe10/spice")
    a = ap.parse_args()

    sta = read_csv(a.sta)
    spice = read_csv(a.spice)
    skey = {(r["corner"], r["canary"], int(r["can_sel"])): r for r in spice}

    rows = []
    for r in sta:
        key = (r["corner"], r["canary"], int(r["can_sel"]))
        s = skey.get(key)
        f_sta = float(r["f_osc_mhz"])
        loop_ns = float(r["loop_delay_ns"])
        line_ns = float(r["line_seg_ns"])
        gate_ns = float(r["gate_seg_ns"])
        rec = dict(corner=r["corner"], v_volt=r["v_volt"],
                   t_celsius=r["t_celsius"], canary=r["canary"],
                   can_sel=key[2], f_sta_mhz=f_sta,
                   loop_delay_ns=loop_ns, line_seg_ns=line_ns,
                   gate_seg_ns=gate_ns,
                   wire_share_pct=100.0 * line_ns / loop_ns,
                   sta_startpoint=r["startpoint"], sta_endpoint=r["endpoint"])
        if s and s.get("status") == "ok" and s.get("f_osc_mhz"):
            f_spice = float(s["f_osc_mhz"])
            rec.update(
                status="ok",
                f_spice_mhz=f_spice,
                ratio_spice_over_sta=f_spice / f_sta,
                period_spice_ns=float(s["period_ns"]),
                period_std_ps=float(s["period_std_ps"]),
                n_periods=int(s["n_periods"]),
                tstop_ns=float(s["tstop_ns"]),
                tstep_ps=float(s["tstep_ps"]),
                solver=s["solver"],
                spice_node=s["node"],
                vmin=float(s["vmin"]), vmax=float(s["vmax"]),
            )
        else:
            rec.update(status=(s or {}).get("status", "missing"),
                       f_spice_mhz="", ratio_spice_over_sta="")
        rows.append(rec)

    ok = [r for r in rows if r["status"] == "ok"]
    ratios = [r["ratio_spice_over_sta"] for r in ok]
    summary = {}
    if ratios:
        mean = sum(ratios) / len(ratios)
        summary = dict(
            n_cases=len(rows), n_ok=len(ok), n_failed=len(rows) - len(ok),
            ratio_mean=mean,
            ratio_min=min(ratios), ratio_max=max(ratios),
            ratio_std=(sum((x - mean) ** 2 for x in ratios) / len(ratios)) ** 0.5,
            bias_pct=100.0 * (mean - 1.0),
        )
        for canary in ("ro_gen", "ro_mat"):
            rs = [r["ratio_spice_over_sta"] for r in ok if r["canary"] == canary]
            if rs:
                summary[f"ratio_mean_{canary}"] = sum(rs) / len(rs)
                summary[f"ratio_min_{canary}"] = min(rs)
                summary[f"ratio_max_{canary}"] = max(rs)
        # wire-share correlation with the ratio: the gap should track how much
        # of the STA loop delay is wire, which SPICE does not include.
        ws = [r["wire_share_pct"] for r in ok]
        if len(ws) > 2:
            mw, mr = sum(ws) / len(ws), mean
            cov = sum((w - mw) * (r_ - mr) for w, r_ in zip(ws, ratios))
            sw = (sum((w - mw) ** 2 for w in ws)) ** 0.5
            sr = (sum((r_ - mr) ** 2 for r_ in ratios)) ** 0.5
            summary["corr_ratio_vs_wire_share"] = cov / (sw * sr) if sw and sr else None

    os.makedirs(a.outdir, exist_ok=True)
    cols = ["corner", "v_volt", "t_celsius", "canary", "can_sel", "status",
            "f_sta_mhz", "f_spice_mhz", "ratio_spice_over_sta",
            "period_spice_ns", "period_std_ps", "n_periods",
            "loop_delay_ns", "line_seg_ns", "gate_seg_ns", "wire_share_pct",
            "tstop_ns", "tstep_ps", "solver", "spice_node", "vmin", "vmax",
            "sta_startpoint", "sta_endpoint"]
    with open(os.path.join(a.outdir, "ro_spice_vs_sta.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    with open(os.path.join(a.outdir, "ro_spice_vs_sta.json"), "w") as fh:
        json.dump({
            "method": {
                "sta": "broken-loop extracted STA (tools/ro/ro_predict.tcl); "
                       "loop = line segment + gate segment, wire RC included",
                "spice": "ngspice transient on the ring subtree of the "
                         "post-route extracted SPICE netlist; cell-internal "
                         "parasitics only, no wire RC",
                "expected_difference": "SPICE omits wire RC, so f_spice is "
                                       "expected to exceed f_sta; the "
                                       "wire_share_pct column bounds the gap",
            },
            "summary": summary,
            "rows": rows,
        }, fh, indent=1)

    if not ok:
        print("no successful cases; wrote table only")
        return

    # ---- plots -----------------------------------------------------------
    corners = ["nom_fast_1p32V_m40C", "nom_typ_1p20V_25C",
               "nom_slow_1p08V_125C"]
    corner_label = {"nom_fast_1p32V_m40C": "fast 1.32 V / -40 C",
                    "nom_typ_1p20V_25C": "typ 1.20 V / 25 C",
                    "nom_slow_1p08V_125C": "slow 1.08 V / 125 C"}
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.6), sharey=False)
    for ax, canary in zip(axes, ("ro_gen", "ro_mat")):
        for corner in corners:
            rs = [r for r in ok if r["canary"] == canary
                  and r["corner"] == corner]
            rs.sort(key=lambda r: r["can_sel"])
            if not rs:
                continue
            x = [r["can_sel"] for r in rs]
            ax.plot(x, [r["f_sta_mhz"] for r in rs], "--o", alpha=0.7,
                    label=f"STA {corner_label[corner]}")
            ax.plot(x, [r["f_spice_mhz"] for r in rs], "-s",
                    label=f"SPICE {corner_label[corner]}")
        ax.set_xlabel("can_sel")
        ax.set_ylabel("f_osc (MHz)")
        ax.set_title(canary)
        ax.grid(True, alpha=0.3)
        ax.set_xticks([0, 1, 2, 3])
        ax.legend(fontsize=7)
    fig.suptitle("RO canary frequency: broken-loop STA vs extracted transient "
                 "SPICE (cell-level netlist, no wire RC)")
    fig.tight_layout()
    fig.savefig(os.path.join(a.outdir, "ro_spice_frequency.png"), dpi=150)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(9, 4.2))
    width = 0.35
    idx = 0
    labels, gen_ratio, mat_ratio = [], [], []
    for corner in corners:
        for sel in (0, 1, 2, 3):
            g = next((r for r in ok if r["canary"] == "ro_gen"
                      and r["corner"] == corner and r["can_sel"] == sel), None)
            m = next((r for r in ok if r["canary"] == "ro_mat"
                      and r["corner"] == corner and r["can_sel"] == sel), None)
            labels.append(f"{corner.split('_')[1][:4]}/{sel}")
            gen_ratio.append(g["ratio_spice_over_sta"] if g else 0)
            mat_ratio.append(m["ratio_spice_over_sta"] if m else 0)
            idx += 1
    x = list(range(len(labels)))
    ax.bar([i - width / 2 for i in x], gen_ratio, width, label="ro_gen")
    ax.bar([i + width / 2 for i in x], mat_ratio, width, label="ro_mat")
    ax.axhline(1.0, color="k", lw=1, ls=":")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=8)
    ax.set_ylabel("f_SPICE / f_STA")
    ax.set_title("SPICE/STA frequency ratio (>1 expected: SPICE omits wire RC)")
    ax.legend()
    ax.grid(True, axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(os.path.join(a.outdir, "ro_spice_ratio.png"), dpi=150)
    plt.close(fig)

    print(json.dumps(summary, indent=1))
    print(f"wrote {a.outdir}/ro_spice_vs_sta.csv")
    print(f"wrote {a.outdir}/ro_spice_vs_sta.json")
    print(f"wrote {a.outdir}/ro_spice_frequency.png")
    print(f"wrote {a.outdir}/ro_spice_ratio.png")


if __name__ == "__main__":
    sys.exit(main())
