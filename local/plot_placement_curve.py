"""
Plot the accessibility-versus-station-count curve produced by the multi-seed
placement study.

Reads the two result files written by run_multiseed_placement.py and
run_saturate_prune.py and renders the Saturate-and-Prune curve with the
Clustering operating point and the reference case on top of it.

Usage:
    python plot_placement_curve.py [out.pdf]
"""
import json
import os
import sys
import statistics as st

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

SCEN = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                    "..", "data", "scenarios")


def agg(rows, key):
    vals = [r[key] for r in rows]
    return st.mean(vals), (st.stdev(vals) if len(vals) > 1 else 0.0)


def main(out_path):
    ms = json.load(open(os.path.join(SCEN, "multiseed_results.json")))
    sp = json.load(open(os.path.join(SCEN, "saturate_prune_results.json")))
    seeds = sorted(ms)

    n_iter = max(len(sp[s]["iterations"]) for s in seeds)
    curve = []
    for i in range(n_iter):
        rows = [sp[s]["iterations"][i] for s in seeds if len(sp[s]["iterations"]) > i]
        curve.append((agg(rows, "cs_in_net"), agg(rows, "soc_end_mean"),
                      agg(rows, "below20")))
    curve.sort(key=lambda c: c[0][0])

    clus = [ms[s]["clustering"] for s in seeds]
    base = [ms[s]["baseline"] for s in seeds]

    ca_path = os.path.join(SCEN, "control_arms_results.json")
    controls = {}
    if os.path.exists(ca_path):
        ca = json.load(open(ca_path))
        for arm, label, colour, marker in (
                ("rand", "Random placement", "#7a7a2e", "^"),
                ("worst", "Anti-clustering", "#6b3b8c", "v")):
            rows = [ca["%s_%s" % (s, arm)] for s in seeds if "%s_%s" % (s, arm) in ca]
            if rows:
                controls[arm] = (label, colour, marker, rows)

    fig, axes = plt.subplots(1, 2, figsize=(9.0, 3.4), sharex=True)

    for ax, idx, ylabel in ((axes[0], 1, "Mean end SoC (%)"),
                            (axes[1], 2, "Agents below 20 % SoC (%)")):
        x = [c[0][0] for c in curve]
        y = [c[idx][0] for c in curve]
        yerr = [c[idx][1] for c in curve]
        ax.errorbar(x, y, yerr=yerr, marker="o", markersize=4, capsize=3,
                    linewidth=1.4, color="#31527d", label="Saturate-and-Prune", zorder=2)

        cx, cxe = agg(clus, "cs_in_net")
        cy, cye = agg(clus, "soc_end_mean" if idx == 1 else "below20")
        ax.errorbar([cx], [cy], yerr=[cye], xerr=[cxe], marker="D", markersize=6,
                    capsize=3, linewidth=1.4, color="#c1512c", label="Clustering", zorder=3)

        # The three arms below all sit at the same station count. Their markers are
        # nudged apart on the x axis so they stay readable, see the caption.
        for arm, dx in (("worst", -7.0), ("rand", -3.5)):
            if arm not in controls:
                continue
            label, colour, marker, rows = controls[arm]
            ax_, _ = agg(rows, "cs_in_net")
            ay, aye = agg(rows, "soc_end_mean" if idx == 1 else "below20")
            ax.errorbar([ax_ + dx], [ay], yerr=[aye], marker=marker, markersize=6,
                        capsize=3, linewidth=1.4, color=colour, label=label, zorder=3)

        bx, _ = agg(base, "cs_in_net")
        by, bye = agg(base, "soc_end_mean" if idx == 1 else "below20")
        ax.errorbar([bx], [by], yerr=[bye], marker="s", markersize=5, capsize=3,
                    linewidth=1.4, color="#4a4a4a", label="Existing infrastructure", zorder=3)

        ax.set_xlabel("Charging stations in network")
        ax.set_ylabel(ylabel)
        ax.grid(True, linewidth=0.4, alpha=0.5)
        ax.set_xlim(0, 240)
        ax.set_xticks([0, 50, 100, 150, 200])
        ax.margins(y=0.15)

    axes[0].legend(frameon=False, fontsize=7, loc="lower right", ncol=1)
    fig.tight_layout()
    fig.savefig(out_path, bbox_inches="tight")
    print("wrote", out_path)


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..", "journal", "en", "images", "placement_curve.pdf")
    main(out)
