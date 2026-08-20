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

        bx, _ = agg(base, "cs_in_net")
        by, bye = agg(base, "soc_end_mean" if idx == 1 else "below20")
        ax.errorbar([bx], [by], yerr=[bye], marker="s", markersize=5, capsize=3,
                    linewidth=1.4, color="#4a4a4a", label="Existing infrastructure", zorder=3)

        ax.set_xlabel("Charging stations in network")
        ax.set_ylabel(ylabel)
        ax.grid(True, linewidth=0.4, alpha=0.5)
        ax.set_xscale("log")
        ax.set_xticks([26, 39, 51, 75, 124, 222])
        ax.get_xaxis().set_major_formatter(matplotlib.ticker.ScalarFormatter())

    axes[0].legend(frameon=False, fontsize=8, loc="lower right")
    fig.tight_layout()
    fig.savefig(out_path, bbox_inches="tight")
    print("wrote", out_path)


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..", "journal", "en", "images", "placement_curve.pdf")
    main(out)
