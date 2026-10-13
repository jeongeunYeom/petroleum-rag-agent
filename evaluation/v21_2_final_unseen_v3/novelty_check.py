"""Blind mechanical overlap check; prior prompts are never printed/exported."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
V2_REV = "b8334b58bcebe36aaa79c50399e8a8110b782216"
PROMPT_KEYS = {"question", "prompt", "user_message", "user_request", "turn1", "turn2"}
LEXICAL_LIMIT = 0.45
SEMANTIC_COSINE_LIMIT = 0.90


def prompt_strings(value: object) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for k, v in value.items():
            if k in PROMPT_KEYS and isinstance(v, str) and len(v.strip()) >= 25:
                found.append(v.strip())
            else:
                found.extend(prompt_strings(v))
    elif isinstance(value, list):
        for v in value:
            found.extend(prompt_strings(v))
    return found


def chargrams(text: str) -> set[str]:
    normalized = re.sub(r"\s+", " ", text.casefold()).strip()
    return {normalized[i : i + 4] for i in range(max(0, len(normalized) - 3))}


def jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a or b else 0.0


def main() -> None:
    benchmark = json.loads((HERE / "benchmark.json").read_text(encoding="utf-8"))
    current = [(t["task_id"], t["question"]) for t in benchmark["primary_tasks"]]
    current += [(p["probe_id"] + "-turn1", p["turn1"]) for p in benchmark["resume_probes"]]
    current += [(p["probe_id"] + "-turn2", p["turn2"]) for p in benchmark["resume_probes"]]
    prior: list[str] = []
    roots = [
        REPO / "evaluation" / name
        for name in (
            "v20_1_browser_e2e",
            "v21_dev",
            "v21_1_dev",
            "v21_2_dev",
            "v21_2_regression_old24",
        )
    ]
    roots += [REPO / "evaluation"]  # includes old frozen benchmark JSON assets
    seen_files: set[Path] = set()
    for root in roots:
        if not root.exists():
            continue
        for file in root.rglob("*.json"):
            if file in seen_files or HERE in file.parents:
                continue
            seen_files.add(file)
            try:
                prior.extend(prompt_strings(json.loads(file.read_text(encoding="utf-8"))))
            except (OSError, ValueError):
                continue
    # V2 questions are only consumed in memory for overlap checking.
    v2 = json.loads(
        subprocess.check_output(
            ["git", "show", f"{V2_REV}:evaluation/v21_2_final_unseen_v2/benchmark.json"],
            cwd=REPO,
        )
    )
    prior.extend(prompt_strings(v2))
    prior = list(dict.fromkeys(prior))
    prior_grams = [chargrams(text) for text in prior]
    rows = []
    for task_id, text in current:
        grams = chargrams(text)
        score = max((jaccard(grams, other) for other in prior_grams), default=0.0)
        rows.append({"task_id": task_id, "max_lexical_similarity": round(score, 6)})
    if any(row["max_lexical_similarity"] > LEXICAL_LIMIT for row in rows):
        bad = [row["task_id"] for row in rows if row["max_lexical_similarity"] > LEXICAL_LIMIT]
        raise ValueError(f"lexical near-duplicates exceed frozen 0.45 threshold: {bad}")

    # Independent multilingual embedding screen: no evaluated generation call.
    from sentence_transformers import SentenceTransformer
    from sentence_transformers.util import cos_sim

    model = SentenceTransformer("BAAI/bge-m3", local_files_only=True, device="cpu")
    current_vectors = model.encode([text for _, text in current], normalize_embeddings=True)
    prior_vectors = model.encode(prior, normalize_embeddings=True, batch_size=16)
    semantic = cos_sim(current_vectors, prior_vectors).max(dim=1).values.tolist()
    for row, score in zip(rows, semantic):
        row["max_semantic_cosine"] = round(float(score), 6)
    if any(row["max_semantic_cosine"] > SEMANTIC_COSINE_LIMIT for row in rows):
        bad = [row["task_id"] for row in rows if row["max_semantic_cosine"] > SEMANTIC_COSINE_LIMIT]
        raise ValueError(f"semantic near-duplicates exceed predeclared cosine limit: {bad}")
    payload = {
        "prior_prompt_count": len(prior),
        "prior_file_count": len(seen_files) + 1,
        "lexical_limit": LEXICAL_LIMIT,
        "semantic_cosine_limit": SEMANTIC_COSINE_LIMIT,
        "max_lexical_similarity": max(row["max_lexical_similarity"] for row in rows),
        "max_semantic_cosine": max(row["max_semantic_cosine"] for row in rows),
        "tasks": rows,
    }
    (HERE / "novelty_results.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print({k: payload[k] for k in ("prior_prompt_count", "max_lexical_similarity", "max_semantic_cosine")})


if __name__ == "__main__":
    main()
