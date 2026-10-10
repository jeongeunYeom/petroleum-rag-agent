"""Pre-freeze source and semantic-overlap audit; never runs benchmark tasks."""

from __future__ import annotations

from collections import Counter
from difflib import SequenceMatcher
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import urllib.request


ROOT = Path(__file__).resolve().parents[2]
BENCHMARK = ROOT / "evaluation/final_benchmark_v2.json"
V1_SHA = "9393606f44d2da88d2c18aa19392d52e226a87aa"
EXPECTED = {"literature": 18, "direct_calculation": 10, "kb_calculation": 10,
            "simulation": 6, "clarification": 4, "false_premise": 4,
            "unsupported_formula": 4, "figure": 4}


def old_questions() -> list[dict]:
    v1 = json.loads(subprocess.check_output(
        ["git", "show", f"{V1_SHA}:evaluation/final_benchmark_v1.json"], cwd=ROOT))
    rows = [{"set": "final_v1", "id": row["task_id"], "question": row["question"]}
            for row in v1["tasks"]]
    agentic = json.loads((ROOT / "evaluation/agentic_heldout_v1.json").read_text(encoding="utf-8"))
    rows.extend({"set": "agentic_heldout_v1", "id": row["task_id"],
                 "question": f"{row.get('topic', '')} {row.get('goal', '')}"}
                for row in agentic["tasks"])
    for name in ("petroleum_agent_heldout_v1_questions.json", "well_test_agent_benchmark.json"):
        for row in json.loads((ROOT / "evaluation" / name).read_text(encoding="utf-8")):
            rows.append({"set": name, "id": row.get("id") or row.get("task_id"),
                         "question": row["question"]})
    return rows


def embed(texts: list[str]) -> list[list[float]]:
    vectors = []
    for start in range(0, len(texts), 24):
        request = urllib.request.Request(
            "http://127.0.0.1:11434/api/embed",
            data=json.dumps({"model": "qwen3-embedding:0.6b", "input": texts[start:start + 24]}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(request, timeout=180) as response:
            vectors.extend(json.load(response)["embeddings"])
    if len(vectors) != len(texts):
        raise RuntimeError("Embedding count mismatch")
    return vectors


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b)) / math.sqrt(
        sum(x * x for x in a) * sum(y * y for y in b))


def masked(text: str) -> str:
    return re.sub(r"\s+", "", re.sub(r"\d+(?:\.\d+)?", "#", text.casefold()))


def source_audit(benchmark: dict) -> dict:
    import chromadb
    import sys
    sys.path.insert(0, str(ROOT / "backend"))
    from app.services.formula_source_registry import FormulaSourceRegistry, equation_ast

    collection = chromadb.PersistentClient(path=str(ROOT / "data/vector_db")).get_collection("petroleum_knowledge")
    if collection.count() != 18976:
        raise RuntimeError(f"Wrong Chroma collection: {collection.count()}")
    data = collection.get(include=["documents", "metadatas"])
    by_page: dict[tuple[str, int], list[str]] = {}
    for content, meta in zip(data["documents"], data["metadatas"]):
        by_page.setdefault((meta.get("document"), meta.get("page")), []).append(content)
    sources = {}
    for source_id, source in benchmark["source_catalog"].items():
        pair = source["document"], source["page"]
        if pair not in by_page:
            raise RuntimeError(f"Missing Chroma source page: {source_id} {pair}")
        note = source.get("figure_note")
        if note:
            note_path = ROOT / "data/figure_notes" / note
            if not note_path.is_file():
                raise RuntimeError(f"Missing figure note: {note}")
            note_text = note_path.read_text(encoding="utf-8")
            if f"page_number: {source['page']}" not in note_text:
                raise RuntimeError(f"Figure note page mismatch: {note}")
        sources[source_id] = {"document": pair[0], "page": pair[1],
                              "chunks_on_page": len(by_page[pair]), "figure_note": note}
    formulas = {}
    for task in benchmark["tasks"]:
        formula = task.get("expected_formula")
        if not formula:
            continue
        gold_ast = equation_ast(formula)
        if not gold_ast:
            raise RuntimeError(f"Unparseable expected formula: {task['task_id']}")
        matches = []
        for source_id in task["expected_source_ids"]:
            source = benchmark["source_catalog"][source_id]
            for chunk_index, content in enumerate(by_page[(source["document"], source["page"])]):
                registry = FormulaSourceRegistry.from_evidence([{
                    "source_type": "knowledge_base", "evidence_id": source_id, "text": content}])
                for record in registry.records:
                    if record.equation_ast == gold_ast and content[record.span_start:record.span_end] == record.raw_span:
                        matches.append({"source_id": source_id, "page": source["page"],
                                        "page_chunk_index": chunk_index, "literal_equation": record.raw_span})
        formulas[task["task_id"]] = matches
        if not matches:
            raise RuntimeError(f"No exact equation-bearing source span: {task['task_id']}")
    return {"collection_count": collection.count(), "source_pages": sources,
            "formula_span_matches": formulas}


def main() -> None:
    benchmark = json.loads(BENCHMARK.read_text(encoding="utf-8"))
    tasks = benchmark["tasks"]
    if len(tasks) != 60 or Counter(row["category"] for row in tasks) != EXPECTED:
        raise RuntimeError("Benchmark count/distribution mismatch")
    if len({row["task_id"] for row in tasks}) != len(tasks):
        raise RuntimeError("Duplicate benchmark task ID")
    old = old_questions()
    vectors = embed([row["question"] for row in tasks + old])
    tops = []
    for index, task in enumerate(tasks):
        scored = []
        for j, row in enumerate(old):
            semantic = cosine(vectors[index], vectors[len(tasks) + j])
            lexical = SequenceMatcher(None, masked(task["question"]), masked(row["question"])).ratio()
            scored.append({"set": row["set"], "old_id": row["id"],
                           "semantic_similarity": round(semantic, 4),
                           "numeric_masked_similarity": round(lexical, 4),
                           "old_question": row["question"]})
        scored.sort(key=lambda pair: max(pair["semantic_similarity"], pair["numeric_masked_similarity"]),
                    reverse=True)
        tops.append({"task_id": task["task_id"], "nearest_old": scored[:3]})
    source = source_audit(benchmark)
    output = {"benchmark_sha256": hashlib.sha256(BENCHMARK.read_bytes()).hexdigest(),
              "task_count": len(tasks), "category_distribution": EXPECTED,
              "old_question_count": len(old), "embedding_model": "qwen3-embedding:0.6b",
              "dedup_top_pairs": tops, "source_audit": source}
    target = ROOT / "evaluation/final_v2/benchmark_preflight.json"
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    flagged = [row for row in tops if max(row["nearest_old"][0][key] for key in
               ("semantic_similarity", "numeric_masked_similarity")) >= 0.82]
    print(json.dumps({"task_count": len(tasks), "old_questions": len(old),
                      "formula_tasks_with_literal_span": len(source["formula_span_matches"]),
                      "flagged_near_duplicates": flagged}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
