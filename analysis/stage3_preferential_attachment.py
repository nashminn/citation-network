"""Stage 3: empirically measure preferential attachment (Ch. 5). See ANALYSIS_PIPELINE.md.

Method (Jeong-Neda-Barabasi style, pooled estimator):
For each year t, a cited node is "eligible" (in the population) once its own
publication year <= t. For each citation event in year t, record the cited
node's in-degree accumulated strictly before year t (k_before). Pi(k) is
estimated as (total new-citation-events landing on degree-k nodes, summed
over all years) / (total node-years spent at degree k across the same years).
Linear preferential attachment (the BA model's core assumption) predicts
Pi(k) ~ k, i.e. slope ~1 on a log-log plot.
"""
import json

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy import stats

from lib import FIGURES_DIR, Timer, append_results_section, get_logger, load_cached_graph

log = get_logger("stage3_preferential_attachment")


def main():
    with Timer(log, "load cached graph"):
        g = load_cached_graph()

    n = g.vcount()
    years = np.array([np.nan if y is None else float(y) for y in g.vs["year"]])
    known_year = ~np.isnan(years)
    log.info(f"nodes with known year: {known_year.sum():,} / {n:,}")

    with Timer(log, "extract & filter edges to known-year endpoints"):
        edge_list = np.array(g.get_edgelist())
        citing_idx = edge_list[:, 0]
        cited_idx = edge_list[:, 1]
        valid = known_year[citing_idx] & known_year[cited_idx]
        citing_idx = citing_idx[valid]
        cited_idx = cited_idx[valid]
        citing_year = years[citing_idx].astype(int)
    log.info(f"edges usable for temporal analysis: {valid.sum():,} / {len(valid):,} ({valid.mean():.1%})")

    node_year = years.copy()
    node_year[~known_year] = np.inf  # never eligible

    with Timer(log, "group edges by citing year"):
        df = pd.DataFrame({"citing_idx": citing_idx, "cited_idx": cited_idx, "citing_year": citing_year})
        year_groups = df.groupby("citing_year")
        sorted_years = sorted(df["citing_year"].unique())
    log.info(f"distinct citing years: {len(sorted_years)} (range {sorted_years[0]}-{sorted_years[-1]})")

    indeg_current = np.zeros(n, dtype=np.int64)
    max_possible_degree = int(df["cited_idx"].value_counts().max()) + 1

    numerator = np.zeros(max_possible_degree + 1, dtype=np.int64)   # new citation events landing on degree-k nodes
    denominator = np.zeros(max_possible_degree + 1, dtype=np.int64)  # node-years spent at degree k

    with Timer(log, f"walk {len(sorted_years)} year-steps, accumulate Pi(k) estimator"):
        for t in sorted_years:
            eligible = node_year <= t
            if eligible.any():
                degrees_of_eligible = indeg_current[eligible]
                pop_hist = np.bincount(degrees_of_eligible, minlength=max_possible_degree + 1)
                denominator[: len(pop_hist)] += pop_hist

            year_edges = year_groups.get_group(t)
            k_before = indeg_current[year_edges["cited_idx"].to_numpy()]
            event_hist = np.bincount(k_before, minlength=max_possible_degree + 1)
            numerator[: len(event_hist)] += event_hist

            # apply this year's new citations for the next iteration
            np.add.at(indeg_current, year_edges["cited_idx"].to_numpy(), 1)

    with np.errstate(divide="ignore", invalid="ignore"):
        pi_k = numerator / denominator
    valid_k = np.where((denominator >= 10) & (numerator > 0))[0]
    valid_k = valid_k[valid_k > 0]  # exclude k=0 from the log-log fit (log(0) undefined)
    log.info(f"degree values with sufficient support (population>=10, events>0, k>0): {len(valid_k)}")

    log_k = np.log10(valid_k)
    log_pi = np.log10(pi_k[valid_k])
    with Timer(log, "log-log linear regression on Pi(k)"):
        slope, intercept, r_value, p_value, std_err = stats.linregress(log_k, log_pi)
    log.info(f"log-log fit: slope={slope:.3f} (+/-{std_err:.3f}), R^2={r_value**2:.3f}, p={p_value:.2e}")

    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    with Timer(log, "plot Pi(k) vs k"):
        fig, ax = plt.subplots(figsize=(6, 5))
        ax.loglog(valid_k, pi_k[valid_k], "o", markersize=4, label="empirical Π(k)")
        fit_line = 10 ** (intercept + slope * log_k)
        ax.loglog(valid_k, fit_line, "-", color="red", label=f"fit: slope={slope:.2f}")
        ax.loglog(valid_k, valid_k / valid_k[0] * pi_k[valid_k][0], "--", color="gray", alpha=0.6, label="slope=1 (linear PA) reference")
        ax.set_xlabel("in-degree k (at time of citation)")
        ax.set_ylabel("Π(k) — attachment rate")
        ax.set_title("Empirical preferential attachment kernel")
        ax.legend()
        fig.tight_layout()
        fig.savefig(FIGURES_DIR / "preferential_attachment.png", dpi=150)
        plt.close(fig)

    result = {
        "usable_edges": int(valid.sum()),
        "total_edges": int(len(valid)),
        "distinct_years": len(sorted_years),
        "slope": slope,
        "slope_stderr": std_err,
        "r_squared": r_value**2,
        "p_value": p_value,
    }
    log.info(f"summary: {json.dumps(result, indent=2)}")

    interpretation = (
        "consistent with linear preferential attachment (slope near 1), "
        "matching the BA model's core assumption"
        if 0.8 <= slope <= 1.2
        else (
            "sub-linear attachment (slope < 1) — weaker rich-get-richer effect than the BA model assumes"
            if slope < 0.8
            else "super-linear attachment (slope > 1) — stronger-than-linear rich-get-richer effect"
        )
    )

    md = f"""## Stage 3 — Preferential attachment, measured empirically

**Status:** done

**Method:** pooled Jeong-Neda-Barabasi estimator. For each year, cited nodes
are "eligible" once their own publication year has arrived; for each
citation event, the cited node's in-degree accumulated *strictly before*
that year is recorded. Π(k) = (total citation events landing on degree-k
nodes) / (total node-years spent at degree k), pooled across all
{result['distinct_years']} distinct years in the data.

**Caveat:** restricted to edges where both citing and cited papers have a
known publication year — {result['usable_edges']:,} / {result['total_edges']:,}
edges ({result['usable_edges']/result['total_edges']:.1%}). Year granularity
is yearly, not exact dates, so citations within the same year are treated as
simultaneous (a coarser resolution than the crawl could in principle
support if exact dates were used).

**Result:**

- Log-log slope of Π(k) vs. k: **{slope:.3f}** (± {std_err:.3f})
- R² = {r_value**2:.3f}, p = {p_value:.2e}
- Interpretation: {interpretation}

Figure: `analysis/figures/preferential_attachment.png` (empirical Π(k),
fitted slope, and a slope=1 reference line for comparison)

Log: `analysis/logs/stage3_preferential_attachment.log`
"""
    append_results_section(md)
    log.info("Stage 3 complete.")


if __name__ == "__main__":
    main()
