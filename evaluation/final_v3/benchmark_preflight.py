"""Read-only v3 source, gold, and novelty audit. Run before the freeze commit."""

from __future__ import annotations

import ast
from collections import Counter
from difflib import SequenceMatcher
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import urllib.request


ROOT = Path(__file__).resolve().parents[2]
BENCHMARK = ROOT / "evaluation/final_benchmark_v3.json"
OUTPUT = ROOT / "evaluation/final_v3/benchmark_preflight.json"
EXPECTED = {
    "literature": 16, "direct_calculation": 10, "kb_calculation": 12,
    "user_formula_calculation": 3, "user_formula_simulation": 3,
    "false_premise": 6, "clarification": 4, "unsupported": 3, "figure": 3,
}
sys.path.insert(0, str(ROOT / "backend"))
from app.services.formula_source_registry import FormulaSourceRegistry, equation_ast  # noqa: E402


def git_json(ref: str, path: str) -> dict | list:
    return json.loads(subprocess.check_output(
        ["git", "show", f"{ref}:{path}"], cwd=ROOT))


def old_questions() -> tuple[list[dict], dict[str, str], set[tuple[str, int]]]:
    refs = {name: subprocess.check_output(
        ["git", "rev-parse", name], cwd=ROOT, text=True).strip()
        for name in ("evaluation/final-benchmark-v1", "evaluation/final-benchmark-v2")}
    rows: list[dict] = []
    old_pages: set[tuple[str, int]] = set()
    for label, ref, path in (
        ("final_v1", refs["evaluation/final-benchmark-v1"], "evaluation/final_benchmark_v1.json"),
        ("final_v2", refs["evaluation/final-benchmark-v2"], "evaluation/final_benchmark_v2.json"),
    ):
        benchmark = git_json(ref, path)
        rows.extend({"set": label, "id": row["task_id"], "question": row["question"]}
                    for row in benchmark["tasks"])
        old_pages.update((item["document"], item["page"])
                         for item in benchmark["source_catalog"].values())
    agentic = json.loads((ROOT / "evaluation/agentic_heldout_v1.json").read_text(encoding="utf-8"))
    rows.extend({"set": "agentic_heldout_v1", "id": row["task_id"],
                 "question": f"{row.get('topic', '')} {row.get('goal', '')}"}
                for row in agentic["tasks"])
    for name in ("petroleum_agent_heldout_v1_questions.json", "well_test_agent_benchmark.json"):
        data = json.loads((ROOT / "evaluation" / name).read_text(encoding="utf-8"))
        for row in data:
            rows.append({"set": name, "id": row.get("id") or row.get("task_id"),
                         "question": row["question"]})
    for name in ("test_agent_reliability_v9.py", "test_agent_reliability_v10.py",
                 "smoke_agent_reliability_v10.py"):
        tree = ast.parse((ROOT / "backend" / ("scripts" if name.startswith("smoke") else "tests")
                          / name).read_text(encoding="utf-8"))
        for index, node in enumerate(ast.walk(tree)):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and len(node.value) >= 35:
                if re.search(r"[가-힣]|\b(?:calculate|simulate|retrieve|pressure|porosity)\b",
                             node.value, re.I):
                    rows.append({"set": name, "id": str(index), "question": node.value})
    # The v9 live-development report records scenario labels, not full prompts; include their
    # engineering targets so a translation or value-only change is still screened.
    for index, summary in enumerate((
        "User-only mean and sum of three rates", "User-only ratio and difference",
        "SG-to-API gravity equation calculation", "User-equation parameter sweep",
        "Reversed kick-pressure premise", "Missing SG then same-run API gravity resume",
    )):
        rows.append({"set": "v9_dev_smoke_scenarios", "id": str(index), "question": summary})
    return rows, refs, old_pages


def embed(texts: list[str]) -> list[list[float]]:
    vectors: list[list[float]] = []
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
    import pdfplumber

    collection = chromadb.PersistentClient(path=str(ROOT / "data/vector_db")).get_collection(
        "petroleum_knowledge")
    if collection.count() != 18976:
        raise RuntimeError(f"Existing collection count changed: {collection.count()}")
    extracted = {}
    for path in (ROOT / "data/extracted").glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        extracted[data["chunks"][0]["metadata"]["document"]] = data
    sources, formula_hits = {}, {}
    normalize = lambda value: re.sub(r"\s+", " ", value).casefold()
    for source_id, source in benchmark["source_catalog"].items():
        document, page = source["document"], source["page"]
        pages = extracted[document]["pages"]
        extracted_text = next(row["text"] for row in pages if row["page"] == page)
        if normalize(source["span"]) not in normalize(extracted_text):
            raise RuntimeError(f"Extracted-page anchor missing: {source_id}")
        rows = collection.get(where={"$and": [{"document": document}, {"page": page}]},
                              include=["documents", "metadatas"])
        matching = [(cid, text) for cid, text in zip(rows["ids"], rows["documents"])
                    if normalize(source["span"]) in normalize(text)]
        if not matching:
            raise RuntimeError(f"Exact Chroma page/span missing: {source_id}")
        raw_files = list((ROOT / "data/raw").glob("*_" + document))
        if len(raw_files) != 1:
            raise RuntimeError(f"Original PDF path ambiguous: {source_id}")
        with pdfplumber.open(raw_files[0]) as pdf:
            pdf_text = pdf.pages[page - 1].extract_text() or ""
        if len(pdf_text.strip()) < 100:
            raise RuntimeError(f"Original PDF page text unavailable: {source_id}")
        formula = source.get("formula")
        if formula:
            expected_ast = equation_ast(formula)
            if expected_ast is None:
                raise RuntimeError(f"Gold formula is not parseable: {source_id}")
            hits = [cid for cid, text in zip(rows["ids"], rows["documents"])
                    if any(record.equation_ast == expected_ast
                           and text[record.span_start:record.span_end] == record.raw_span
                           for record in FormulaSourceRegistry.from_evidence([{
                               "source_type": "knowledge_base", "evidence_id": cid,
                               "text": text}]).records)]
            if not hits:
                raise RuntimeError(f"No literal equation AST in Chroma span: {source_id}")
            formula_hits[source_id] = hits
        note_name = source.get("figure_note")
        if note_name:
            note_path = ROOT / "data/figure_notes" / note_name
            note = note_path.read_text(encoding="utf-8")
            if f"page_number: {page}" not in note or f"document_name: {document}" not in note:
                raise RuntimeError(f"Figure note metadata mismatch: {source_id}")
            image = next((line.removeprefix("image_path: ").strip()
                          for line in note.splitlines() if line.startswith("image_path: ")), "")
            if not image or not Path(image).is_file():
                raise RuntimeError(f"Figure image missing: {source_id}")
        sources[source_id] = {
            "document": document, "page": page, "chroma_chunks_on_page": len(rows["ids"]),
            "anchor_chunk_ids": [cid for cid, _ in matching],
            "pdf_text_layer_contains_literal_anchor": normalize(source["span"]) in normalize(pdf_text),
            "formula_ast_matched": bool(formula_hits.get(source_id)),
            "figure_note_and_image_present": bool(note_name),
        }
    return {"collection_name": "petroleum_knowledge", "collection_count": collection.count(),
            "sources": sources, "formula_span_matches": formula_hits}


def gold_audit(tasks: list[dict]) -> dict:
    calculations = [row for row in tasks if row.get("required_numeric_result")]
    resumptions = [row for row in tasks if row.get("expected_after_resume")]
    for row in calculations + resumptions:
        values = row.get("required_numeric_result") or row.get("expected_after_resume")
        if not values or not all(isinstance(v, (int, float)) and math.isfinite(v)
                                 for v in values.values()):
            raise RuntimeError(f"Non-finite or missing numeric gold: {row['task_id']}")
        if row.get("expected_formula") and equation_ast(row["expected_formula"]) is None:
            raise RuntimeError(f"Unparseable task formula: {row['task_id']}")
    # Independent arithmetic checks for all numerical gold values (not model scoring).
    checks = {
        "D01": 50 + 90, "D02": 900 * 2 / 9, "D03": sorted([2990,3010,3050,3070,3100])[2],
        "D04": math.sqrt(sum((v - 13) ** 2 for v in (10,12,14,16)) / 4),
        "D05": 500 / 28, "D06": 40 + (80 - 40) * .5, "D07": 80 + 70,
        "D08": math.sqrt(9 * 36), "D09": 3000 * .9 ** 3, "D10": 1000 * 2 + 400 * 3,
        "K01": 105 + 32, "K02": 1e-5 * .75 + 3e-6 * .25 + 5e-6,
        "K03": 2400 - 900 / 1.5,
        "K04": .24 / .08, "K05": 3600 - 2800, "K06": .045 / .015,
        "K07": 3200 + 140, "K08": 720 / 240, "K09": .9 / 3,
        "K10": 3 / .006, "K11": 30 / 6, "K12": 500000 - 80000 + 20000,
        "M01": (1450 - 1000) / 1000, "M02": 12 * 850 * .9,
        "M03": (80 - 5) / 100, "S01": max(40 - (x - 6) ** 2 for x in range(0, 13, 3)),
        "S02": min(.5 * q * q - 6 * q + 50 for q in range(0, 13, 3)),
        "S03": max(2 * a * 6 - a * a for a in range(0, 11, 2)),
        "C01": 2500 - 900 / 1.8, "C02": 1.2 / 4,
        "C03": 120 / 15, "C04": 7 + 9 + 5,
    }
    audited = {}
    for row in calculations + resumptions:
        if row["task_id"] not in checks:
            raise RuntimeError(f"Independent gold arithmetic absent: {row['task_id']}")
        values = row.get("required_numeric_result") or row.get("expected_after_resume")
        primary = next((v for key, v in values.items()
                        if not key.startswith(("case_count", "best_", "mean_"))
                        and key not in {"X_m3", "Y_m3", "Z_m3"}), None)
        if row["task_id"] == "D02":
            primary = values["X_m3"]
        elif row["task_id"] == "D04":
            primary = values["population_sd_md"]
        if primary is None or not math.isclose(checks[row["task_id"]], primary, rel_tol=1e-8,
                                                abs_tol=float(row.get("tolerance", {}).get("absolute",
                                                                                          row.get("resume_tolerance", .01)))):
            raise RuntimeError(f"Gold arithmetic mismatch: {row['task_id']}")
        audited[row["task_id"]] = {"independent_primary_result": checks[row["task_id"]],
                                    "gold_primary_result": primary}
    return {"calculation_tasks": len(calculations), "resume_tasks": len(resumptions),
            "independent_arithmetic": audited}


def main() -> None:
    benchmark = json.loads(BENCHMARK.read_text(encoding="utf-8"))
    tasks = benchmark["tasks"]
    if benchmark["evaluated_product_sha"] != "1fd303255ea151869905092d55096d29f6771128":
        raise RuntimeError("Wrong evaluated product SHA")
    if len(tasks) != 60 or Counter(row["category"] for row in tasks) != EXPECTED:
        raise RuntimeError("Task count/category distribution mismatch")
    if len({row["task_id"] for row in tasks}) != 60:
        raise RuntimeError("Duplicate task IDs")
    if any(source not in benchmark["source_catalog"]
           for row in tasks for source in row.get("expected_source_ids", [])):
        raise RuntimeError("Task references unknown source")
    old, refs, old_pages = old_questions()
    vectors = embed([row["question"] for row in tasks + old])
    top = []
    for index, row in enumerate(tasks):
        pairs = sorted(({
            "set": old_row["set"], "old_id": old_row["id"],
            "semantic_similarity": round(cosine(vectors[index], vectors[len(tasks) + j]), 4),
            "numeric_masked_similarity": round(SequenceMatcher(
                None, masked(row["question"]), masked(old_row["question"])).ratio(), 4),
            "old_question": old_row["question"],
        } for j, old_row in enumerate(old)), key=lambda x: max(
            x["semantic_similarity"], x["numeric_masked_similarity"]), reverse=True)
        top.append({"task_id": row["task_id"], "nearest_old": pairs[:3]})
    source = source_audit(benchmark)
    gold = gold_audit(tasks)
    overlap = {source_id: {"document": item["document"], "page": item["page"]}
               for source_id, item in benchmark["source_catalog"].items()
               if (item["document"], item["page"]) in old_pages}
    flagged = [row for row in top if row["nearest_old"] and
               (row["nearest_old"][0]["semantic_similarity"] >= .82 or
                row["nearest_old"][0]["numeric_masked_similarity"] >= .78)]
    result = {
        "benchmark_sha256": hashlib.sha256(BENCHMARK.read_bytes()).hexdigest(),
        "task_count": len(tasks), "category_distribution": dict(Counter(row["category"] for row in tasks)),
        "domain_distribution": dict(Counter(row["domain"] for row in tasks)),
        "old_evaluation_refs": refs, "old_question_count": len(old),
        "embedding_model": "qwen3-embedding:0.6b", "dedup_top_pairs": top,
        "maximum_semantic_similarity": max(x["nearest_old"][0]["semantic_similarity"] for x in top),
        "maximum_numeric_masked_similarity": max(
            x["nearest_old"][0]["numeric_masked_similarity"] for x in top),
        "flagged_near_duplicates": flagged, "prior_source_page_overlap": overlap,
        "source_audit": source, "gold_audit": gold,
    }
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "task_count": len(tasks), "old_questions": len(old),
        "formula_span_matches": len(source["formula_span_matches"]),
        "flagged_near_duplicates": [{"task_id": x["task_id"], **x["nearest_old"][0]} for x in flagged],
        "prior_source_page_overlap": overlap,
        "maximum_semantic_similarity": result["maximum_semantic_similarity"],
        "maximum_numeric_masked_similarity": result["maximum_numeric_masked_similarity"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
