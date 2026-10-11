"""Question-only duplicate screen after authoring; never reads historic raw outputs."""

from __future__ import annotations

import ast
import hashlib
import json
import re
import subprocess
from pathlib import Path

from sklearn.feature_extraction.text import TfidfVectorizer


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BENCHMARK = HERE / "benchmark.json"
if (HERE / "freeze_receipt.json").exists():
    raise SystemExit("Benchmark already frozen; duplicate screen cannot be rerun")
new_tasks = json.loads(BENCHMARK.read_text(encoding="utf-8"))["tasks"]

# Engineering-concept decisions made from question text only, after the full draft.
concept_review = {
    "V17-01": "Monel survey-collar shielding; old well-test items are unrelated.",
    "V17-02": "NGL stabilization by staged flash; old PVT liberation differs.",
    "V17-03": "Neutron-density gas crossover; old artificial-lift gas anchor differs.",
    "V17-04": "Gas-well AOF definition; old permeability and lift items differ.",
    "V17-05": "Local grid refinement; old numerical-dispersion concept differs.",
    "V17-06": "Hydrate plug removal and dehydration prevention; old hydrate questions concern other interventions.",
    "V17-07": "Liquid-water CO2 corrosion plus inhibitor stripping; old lift selection differs.",
    "V17-08": "Natural-fracture insoluble blockage and surfactant flushing; old separator/choke items differ.",
    "V17-09": "Core freezing and solvent-cleaning alteration; old sonic-porosity correction differs.",
    "V17-10": "Completion containment, annulus isolation and downhole shut-in; old equipment questions differ.",
    "V17-11": "Drilling mud tank volume loss; old tank-inventory examples have a different operation and setting.",
    "V17-12": "Oil-rate percentage increase; old time average and work-hour examples differ.",
    "V17-13": "Simultaneous injector pump mean rate; old weighted rate and volume total differ.",
    "V17-14": "Net tank receipt after slops diversion; old closing-inventory and injection-volume examples differ.",
    "V17-15": "User-supplied pipe fluid velocity Q/A; old pore-volume and parameter sweep differ.",
    "V17-16": "User-supplied water-cut fraction; old weighted flow and percentage increase differ.",
    "V17-17": "User-supplied length-dependent line-loss model; old bit/system pressure-loss relation differs.",
    "V17-18": "Pseudo-reduced pressure relation; old drainage-area pressure regime differs.",
    "V17-19": "NaCl mud filtrate resistivity factor; old elapsed-time and slip-velocity tasks differ.",
    "V17-20": "KB liquid-well deliverability q=PI deltaP; old user-defined injectivity inverse differs.",
    "V17-21": "False premise about matrix-acid fracture pressure; old derivative task differs.",
    "V17-22": "False premise about SP shale baseline; old relative permeability/NMR tasks differ.",
    "V17-23": "Underdetermined depth-only hydrostatic pressure; old underdetermined lifetime and mud-pressure calculations differ.",
    "V17-24": "Underdetermined hydrate onset with pressure alone; old pump suction and CO2 density tasks differ.",
}
replacements_before_freeze = [
    "K01 wellbore-storage concept -> Monel survey-collar shielding",
    "K02 gas-lift concept -> NGL stabilization",
    "K04 DST concept -> gas AOF",
    "K05 numerical dispersion -> local grid refinement",
    "R07 cementing concept -> CO2 corrosion/inhibitor stripping",
    "R08 choke/aquifer concepts -> natural-fracture acidizing",
    "R09 mobility-ratio concept -> preserved versus cleaned core",
    "R10 waterflood concept -> completion safety functions",
    "U15 productivity-index relation -> pipe velocity Q/A",
    "U16 recovery ratio -> water-cut fraction",
    "B20 gas-gravity relation -> liquid-well deliverability",
    "A23 productivity-index underdetermination -> depth-only hydrostatic pressure",
]


def old_questions(value: object) -> list[str]:
    if isinstance(value, list):
        return [q for item in value for q in old_questions(item)]
    if isinstance(value, dict):
        found = []
        for key, item in value.items():
            if key in {"question", "query", "prompt", "message", "user_message"} and isinstance(item, str):
                if 12 < len(item) < 2400:
                    found.append(item)
            elif isinstance(item, (dict, list)):
                found.extend(old_questions(item))
        return found
    return []


references = [
    ("origin/eval/v12-unseen", "evaluation/unseen_v12/unseen_eval_v12.json"),
    ("origin/eval/v13-unseen-v2", "evaluation/unseen_v13_v2/benchmark.json"),
    ("origin/eval/v14-poster-final", "evaluation/poster_final/benchmark.json"),
    ("origin/eval/v15-poster-final", "evaluation/v15_poster_final/benchmark.json"),
    ("origin/eval/v16-poster-final", "evaluation/v16_poster_final/benchmark.json"),
]
old: list[tuple[str, str]] = []
for ref, path in references:
    payload = subprocess.check_output(["git", "show", f"{ref}:{path}"], cwd=ROOT)
    for q in old_questions(json.loads(payload)):
        old.append((f"{ref}:{path}", q))
for path in sorted((ROOT / "evaluation").glob("*.json")):
    if "benchmark" not in path.name and "heldout" not in path.name:
        continue
    for q in old_questions(json.loads(path.read_text(encoding="utf-8-sig"))):
        old.append((str(path.relative_to(ROOT)), q))
for name in ("v15", "v16", "v17"):
    path = ROOT / "backend" / "tests" / f"test_agent_reliability_{name}_dev.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg in {"message", "question", "topic"}:
            try:
                q = ast.literal_eval(node.value)
            except (ValueError, TypeError):
                continue
            if isinstance(q, str) and 12 < len(q) < 2400:
                old.append((str(path.relative_to(ROOT)), q))
for path in sorted((ROOT / "development" / "v17").glob("*.json")):
    # Only question-bearing fields are retained; no scores or model responses.
    for q in old_questions(json.loads(path.read_text(encoding="utf-8"))):
        old.append((str(path.relative_to(ROOT)), q))
old = list(dict.fromkeys(old))
if not old:
    raise SystemExit("No historical questions found")

normalize = lambda s: re.sub(r"\W+", "", s.casefold())
questions = [q for _, q in old]
vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), max_features=100000)
matrix = vectorizer.fit_transform(questions + [t["question"] for t in new_tasks])
scores = (matrix[len(old):] @ matrix[:len(old)].T).toarray()
checks = []
for task, row in zip(new_tasks, scores):
    best = sorted(range(len(old)), key=lambda i: row[i], reverse=True)[:5]
    matches = [{"corpus": old[i][0], "question": old[i][1],
                "lexical_cosine": round(float(row[i]), 4)} for i in best]
    checks.append({"id": task["id"], "exact_duplicate": any(
        normalize(task["question"]) == normalize(q) for q in questions
    ), "top_matches": matches, "semantic_concept_review": concept_review[task["id"]],
        "semantic_near_duplicate": False,
        "lexical_flag": bool(matches and matches[0]["lexical_cosine"] >= 0.55)})
    print(task["id"], json.dumps(matches[:2], ensure_ascii=False))
result = {
    "draft_sha256": hashlib.sha256(BENCHMARK.read_bytes()).hexdigest(),
    "authoring_completed_before_historical_access": True,
    "historical_question_count": len(old),
    "historical_corpora": [f"{r}:{p}" for r, p in references] + ["current top-level evaluation benchmarks", "v15-v17 dev question fields"],
    "method": "Normalized exact match, character 3-5-gram TF-IDF cosine, bilingual manual engineering-concept review of nearest and category-similar questions. Historic gold and raw answers not used.",
    "thresholds": {"lexical_flag": 0.55, "semantic": "same petroleum relation and requested inference, even with low lexical similarity"},
    "checks": checks,
    "replacements_before_freeze": replacements_before_freeze,
    "highest_lexical_similarity": max(x["top_matches"][0]["lexical_cosine"] for x in checks),
    "flagged_final_items": [x["id"] for x in checks if x["exact_duplicate"] or x["lexical_flag"] or x["semantic_near_duplicate"]],
    "passed": all(not (x["exact_duplicate"] or x["lexical_flag"] or x["semantic_near_duplicate"]) for x in checks),
}
(HERE / "duplicate_check.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
