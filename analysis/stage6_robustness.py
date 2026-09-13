"""Stage 6: robustness / "Achilles' heel" of scale-free networks (Ch. 8). See ANALYSIS_PIPELINE.md."""
import json

import igraph as ig
import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from lib import FIGURES_DIR, Timer, append_results_section, get_logger, load_cached_graph

log = get_logger("stage6_robustness")

N_STEPS = 40  # fraction-of-nodes-removed checkpoints
RANDOM_SEED = 42


def giant_component_fraction(g):
    return g.connected_components(mode="weak").giant().vcount() / g.vcount()


def simulate_removal_safe(g, order_labels_desc_priority, n_steps, log_label):
    """Index-safe removal simulation: rebuild a fresh igraph each checkpoint from
    an edge list filtered by a 'still alive' vertex mask, avoiding re-indexing bugs
    from repeated delete_vertices calls."""
    n = g.vcount()
    edge_list = np.array(g.get_edgelist())
    fractions_removed = np.linspace(0, 0.9, n_steps)
    giant_fracs = []
    alive = np.ones(n, dtype=bool)
    order = order_labels_desc_priority
    prev_target = 0
    for i, frac in enumerate(fractions_removed):
        target = int(frac * n)
        if target > prev_target:
            alive[order[prev_target:target]] = False
            prev_target = target
        if alive.sum() == 0:
            giant_fracs.append(0.0)
            continue
        mask = alive[edge_list[:, 0]] & alive[edge_list[:, 1]]
        sub_edges = edge_list[mask]
        # relabel alive vertices to a contiguous range for a small working graph
        alive_idx = np.nonzero(alive)[0]
        relabel = -np.ones(n, dtype=np.int64)
        relabel[alive_idx] = np.arange(len(alive_idx))
        sub_g = ig.Graph(n=len(alive_idx), edges=relabel[sub_edges].tolist(), directed=False)
        frac_giant = giant_component_fraction(sub_g) if sub_g.vcount() > 0 else 0.0
        giant_fracs.append(frac_giant)
        if i % 10 == 0:
            log.info(f"{log_label}: removed {frac:.0%} of nodes, giant component = {frac_giant:.3f} of remaining graph")
    return fractions_removed, giant_fracs


def main():
    with Timer(log, "load cached graph"):
        g = load_cached_graph()
    g_undirected = g.as_undirected(mode="collapse")
    n = g_undirected.vcount()

    with Timer(log, "compute degree sequence for targeted-attack ordering"):
        degrees = np.array(g_undirected.degree())

    rng = np.random.default_rng(RANDOM_SEED)
    random_order = rng.permutation(n)
    targeted_order = np.argsort(degrees)[::-1]  # highest-degree first

    with Timer(log, f"simulate random node removal ({N_STEPS} checkpoints)"):
        frac_random, giant_random = simulate_removal_safe(g_undirected, random_order, N_STEPS, "random-removal")

    with Timer(log, f"simulate targeted (highest-degree-first) removal ({N_STEPS} checkpoints)"):
        frac_targeted, giant_targeted = simulate_removal_safe(g_undirected, targeted_order, N_STEPS, "targeted-removal")

    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    with Timer(log, "plot robustness curves"):
        fig, ax = plt.subplots(figsize=(6, 5))
        ax.plot(frac_random, giant_random, "o-", label="random removal", markersize=3)
        ax.plot(frac_targeted, giant_targeted, "s-", label="targeted removal (highest-degree first)", markersize=3)
        ax.set_xlabel("fraction of nodes removed")
        ax.set_ylabel("giant component size (fraction of remaining graph)")
        ax.set_title("Robustness: random failure vs. targeted attack")
        ax.legend()
        fig.tight_layout()
        fig.savefig(FIGURES_DIR / "robustness.png", dpi=150)
        plt.close(fig)

    # find the fraction removed at which targeted attack drops giant component below 0.5
    below_half_targeted = next((f for f, gc in zip(frac_targeted, giant_targeted) if gc < 0.5), None)
    below_half_random = next((f for f, gc in zip(frac_random, giant_random) if gc < 0.5), None)

    result = {
        "final_giant_fraction_random": giant_random[-1],
        "final_giant_fraction_targeted": giant_targeted[-1],
        "removal_frac_to_break_giant_targeted": below_half_targeted,
        "removal_frac_to_break_giant_random": below_half_random,
    }
    log.info(f"summary: {json.dumps(result, indent=2)}")

    md = f"""## Stage 6 — Robustness / the "Achilles' heel"

**Status:** done

Simulated removing up to 90% of nodes from the (undirected projection of
the) giant component, under two strategies: random removal, and targeted
removal of the highest-degree nodes first. At each checkpoint, the giant
component size is re-measured as a fraction of whatever graph remains.

- After removing 90% of nodes **randomly**, giant component retains
  **{giant_random[-1]:.1%}** of the remaining graph.
- After removing 90% of nodes **by targeted attack**, giant component
  retains only **{giant_targeted[-1]:.1%}** of the remaining graph.
- Fraction of nodes needed to break the giant component below 50% —
  random removal: {f'{below_half_random:.0%}' if below_half_random is not None else 'not reached within 90%'};
  targeted removal: {f'{below_half_targeted:.0%}' if below_half_targeted is not None else 'not reached within 90%'}

This is the book's signature scale-free-network result: **robust under
random failure, fragile under targeted attack**. The gap between the two
curves (see figure) is the direct consequence of the hub structure
quantified in Stage 5 — removing a small number of high-degree hubs does
disproportionate damage to overall connectivity, while removing random
(mostly low-degree) nodes barely affects it.

Figure: `analysis/figures/robustness.png`

Log: `analysis/logs/stage6_robustness.log`
"""
    append_results_section(md)
    log.info("Stage 6 complete.")


if __name__ == "__main__":
    main()
