"""Shared helpers for the network-science analysis pipeline (ANALYSIS_PIPELINE.md)."""
import logging
import sqlite3
import sys
import time
from pathlib import Path

ANALYSIS_DIR = Path(__file__).resolve().parent
PROJECT_DIR = ANALYSIS_DIR.parent
DB_PATH = PROJECT_DIR / "data" / "db" / "citation_network_v3.db"
CACHE_DIR = ANALYSIS_DIR / "cache"
LOG_DIR = ANALYSIS_DIR / "logs"
FIGURES_DIR = ANALYSIS_DIR / "figures"
GRAPH_CACHE_PATH = CACHE_DIR / "graph.pkl"
RESULTS_MD_PATH = PROJECT_DIR / "ANALYSIS_RESULTS.md"


def get_logger(stage_name: str) -> logging.Logger:
    logger = logging.getLogger(stage_name)
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")

    fh = logging.FileHandler(LOG_DIR / f"{stage_name}.log", mode="w")
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(sh)

    return logger


class Timer:
    """Context manager that logs how long a block took."""

    def __init__(self, logger: logging.Logger, label: str):
        self.logger = logger
        self.label = label

    def __enter__(self):
        self.start = time.monotonic()
        self.logger.info(f"START: {self.label}")
        return self

    def __exit__(self, *exc):
        elapsed = time.monotonic() - self.start
        self.logger.info(f"DONE: {self.label} ({elapsed:.1f}s)")


def db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    return conn


def load_cached_graph():
    """Load the igraph.Graph built by stage0. Raises if stage0 hasn't run yet."""
    import pickle

    if not GRAPH_CACHE_PATH.exists():
        raise FileNotFoundError(
            f"{GRAPH_CACHE_PATH} not found — run stage0_load_clean.py first."
        )
    with open(GRAPH_CACHE_PATH, "rb") as f:
        return pickle.load(f)


def append_results_section(markdown: str):
    """Append a stage's results section to ANALYSIS_RESULTS.md, creating it if needed."""
    is_new = not RESULTS_MD_PATH.exists()
    with open(RESULTS_MD_PATH, "a") as f:
        if is_new:
            f.write("# Analysis Results\n\n")
            f.write(
                "Execution log and results for stages 1-7 of ANALYSIS_PIPELINE.md. "
                "Each section is appended as its stage completes.\n\n"
            )
        f.write(markdown.rstrip() + "\n\n")
