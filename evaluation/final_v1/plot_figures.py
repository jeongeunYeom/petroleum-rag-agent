"""Create cautious, publication-ready static charts from measured final metrics."""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


HERE = Path(__file__).resolve().parent
OUT = HERE / "figures"
OUT.mkdir(exist_ok=True)
metrics = json.loads((HERE / "final_metrics.json").read_text(encoding="utf-8"))["tracks"]


def grouped_bars(tracks: list[str], title: str, file: str) -> None:
    labels = ["Agent", "Qwen 8B", "OpenAI"]
    keys = ["goal_success", "exact_accuracy", "claim_coverage", "hallucination"]
    names = ["Goal success", "Exact", "Claim coverage", "Hallucination"]
    x = np.arange(len(keys))
    fig, ax = plt.subplots(figsize=(10, 5.4), constrained_layout=True)
    colors = ["#3755ad", "#777c86", "#3d998c"]
    for index, (label, track) in enumerate(zip(labels, tracks)):
        values = [metrics[track][key] for key in keys]
        ax.bar(x + (index - (len(tracks) - 1) / 2) * 0.19,
               [100 * v if v is not None else np.nan for v in values],
               width=0.18, color=colors[index], label=label)
    ax.set_xticks(x, names)
    ax.set_ylim(0, 105)
    ax.set_ylabel("Percent of valid tasks / expected claims")
    ax.set_title(title)
    ax.legend(loc="upper right", frameon=False, ncol=2)
    ax.grid(axis="y", alpha=0.2)
    fig.savefig(OUT / file, dpi=220)
    plt.close(fig)


grouped_bars(["agent", "qwen_closed_book", "openai_closed_book"],
             "Track A: End-to-end (unequal information access)", "track_a_comparison.png")
grouped_bars(["agent", "qwen_same_evidence", "openai_same_evidence"],
             "Track B: Same Agent-retrieved text evidence", "track_b_comparison.png")

fig, ax = plt.subplots(figsize=(9, 4.7), constrained_layout=True)
tracks = ["agent", "qwen_closed_book", "openai_closed_book",
          "qwen_same_evidence", "openai_same_evidence"]
latencies = [metrics[key]["median_latency_seconds"] for key in tracks]
ax.barh(tracks[::-1], latencies[::-1], color="#6576a5")
ax.set_xlabel("Median client wall-clock seconds per task")
ax.set_title("Latency trade-off (local and remote infrastructure differ)")
ax.grid(axis="x", alpha=0.2)
fig.savefig(OUT / "median_latency.png", dpi=220)
plt.close(fig)

print("figures=3")
