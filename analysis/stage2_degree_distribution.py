"""Stage 2: degree distribution & scale-free test (Ch. 4). See ANALYSIS_PIPELINE.md."""
import json

import matplotlib
import numpy as np
import powerlaw

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from lib import FIGURES_DIR, Timer, append_results_section, get_logger, load_cached_graph

log = get_logger("stage2_degree_distribution")


def plot_loglog_hist(degrees, title, path):
    positive = np.array([d for d in degrees if d > 0])
    counts, bins = np.histogram(positive, bins=np.logspace(0, np.log10(positive.max()), 50))
    bin_centers = (bins[:-1] + bins[1:]) / 2
    mask = counts > 0
    fig, ax = plt.subplots(figsize=(6, 5))
    ax.loglog(bin_centers[mask], counts[mask], "o", markersize=4)
    ax.set_xlabel("degree k")
    ax.set_ylabel("count")
    ax.set_title(title)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def main():
    with Timer(log, "load cached graph"):
        g = load_cached_graph()

    indeg = np.array(g.indegree())
    outdeg = np.array(g.outdegree())

    zero_indeg = int((indeg == 0).sum())
    zero_outdeg = int((outdeg == 0).sum())
    log.info(f"nodes with in-degree 0 (never cited within crawl): {zero_indeg:,} ({zero_indeg/len(indeg):.1%})")
    log.info(f"nodes with out-degree 0 (no references crawled): {zero_outdeg:,} ({zero_outdeg/len(outdeg):.1%})")
    log.info(f"max out-degree: {outdeg.max()} vs max in-degree: {indeg.max()} — out-degree is crawler-capped, see caveat below")

    FIGURES_DIR.mkdir(parents=True, exist_ok=True)

    with Timer(log, "plot in-degree log-log histogram"):
        plot_loglog_hist(indeg, "In-degree distribution (log-log)", FIGURES_DIR / "indegree_loglog.png")

    with Timer(log, "plot out-degree log-log histogram"):
        plot_loglog_hist(outdeg, "Out-degree distribution (log-log)", FIGURES_DIR / "outdegree_loglog.png")

    with Timer(log, "powerlaw.Fit on in-degree (this can be slow: xmin search)"):
        indeg_positive = indeg[indeg > 0]
        fit = powerlaw.Fit(indeg_positive, discrete=True)

    alpha = fit.power_law.alpha
    xmin = fit.power_law.xmin
    log.info(f"in-degree power-law fit: alpha={alpha:.3f}, xmin={xmin}")

    with Timer(log, "compare power law vs lognormal vs exponential"):
        R_lognorm, p_lognorm = fit.distribution_compare("power_law", "lognormal")
        R_exp, p_exp = fit.distribution_compare("power_law", "exponential")
        R_trunc, p_trunc = fit.distribution_compare("power_law", "truncated_power_law")

    log.info(f"power_law vs lognormal: R={R_lognorm:.3f}, p={p_lognorm:.4f}")
    log.info(f"power_law vs exponential: R={R_exp:.3f}, p={p_exp:.4f}")
    log.info(f"power_law vs truncated_power_law: R={R_trunc:.3f}, p={p_trunc:.4f}")

    def verdict(R, p):
        if p > 0.1:
            return "inconclusive (p > 0.1, can't distinguish)"
        return "power law favored" if R > 0 else "alternative favored"

    comparisons = {
        "power_law_vs_lognormal": {"R": R_lognorm, "p": p_lognorm, "verdict": verdict(R_lognorm, p_lognorm)},
        "power_law_vs_exponential": {"R": R_exp, "p": p_exp, "verdict": verdict(R_exp, p_exp)},
        "power_law_vs_truncated_power_law": {"R": R_trunc, "p": p_trunc, "verdict": verdict(R_trunc, p_trunc)},
    }
    log.info(f"comparisons: {json.dumps(comparisons, indent=2)}")

    md = f"""## Stage 2 — Degree distribution & scale-free test

**Status:** done

**Caveat first:** out-degree is artificially capped by the crawler's
per-paper reference-fetch limit (max observed out-degree: {outdeg.max()}, vs.
max in-degree {indeg.max():,}). Out-degree distribution below is reported for
completeness but should **not** be interpreted as an organic/natural
distribution — the scale-free test focuses on in-degree only, which is not
subject to this cap (a paper's citation count within the crawl isn't limited
by anything the crawler imposed).

- Nodes with in-degree 0 (never cited within this crawl): {zero_indeg:,} ({zero_indeg/len(indeg):.1%})
- Nodes with out-degree 0 (no crawled references): {zero_outdeg:,} ({zero_outdeg/len(outdeg):.1%})

**In-degree power-law fit** (via `powerlaw` package, Clauset-Shalizi-Newman method):

- α (scaling exponent) = {alpha:.3f}
- x_min (fit starts at degree ≥) = {xmin}

**Distribution comparison** (log-likelihood ratio test; R > 0 favors power
law, p < 0.1 means the comparison is meaningful rather than inconclusive):

| Comparison | R | p | Verdict |
|---|---|---|---|
| power law vs. lognormal | {R_lognorm:.3f} | {p_lognorm:.4f} | {comparisons['power_law_vs_lognormal']['verdict']} |
| power law vs. exponential | {R_exp:.3f} | {p_exp:.4f} | {comparisons['power_law_vs_exponential']['verdict']} |
| power law vs. truncated power law | {R_trunc:.3f} | {p_trunc:.4f} | {comparisons['power_law_vs_truncated_power_law']['verdict']} |

Figures: `analysis/figures/indegree_loglog.png`, `analysis/figures/outdegree_loglog.png`

Log: `analysis/logs/stage2_degree_distribution.log`
"""
    append_results_section(md)
    log.info("Stage 2 complete.")


if __name__ == "__main__":
    main()
