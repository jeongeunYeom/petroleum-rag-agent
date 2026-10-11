"""Read-only v4 source, gold, and novelty audit. Run before the freeze commit."""

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
import unicodedata
import urllib.request


ROOT = Path(__file__).resolve().parents[2]
BENCHMARK = ROOT / "evaluation/final_benchmark_v4.json"
OUTPUT = ROOT / "evaluation/final_v4/benchmark_preflight.json"
EXPECTED = {
    "literature": 14, "direct_calculation": 10, "kb_calculation": 12,
    "user_formula_calculation": 4, "user_formula_simulation": 4,
    "false_premise": 6, "clarification": 4, "unsupported": 3, "figure": 3,
}
sys.path.insert(0, str(ROOT / "backend"))
from app.services.formula_source_registry import (FormulaSourceRegistry, EQUATION, TRANSLATION,
                                                   equation_ast)  # noqa: E402


def git_json(ref: str, path: str) -> dict | list:
    return json.loads(subprocess.check_output(
        ["git", "show", f"{ref}:{path}"], cwd=ROOT))


def old_questions() -> tuple[list[dict], dict[str, str], set[tuple[str, int]]]:
    refs = {name: subprocess.check_output(
        ["git", "rev-parse", name], cwd=ROOT, text=True).strip()
        for name in ("evaluation/final-benchmark-v1", "evaluation/final-benchmark-v2",
                     "evaluation/final-benchmark-v3")}
    rows: list[dict] = []
    old_pages: set[tuple[str, int]] = set()
    for label, ref, path in (
        ("final_v1", refs["evaluation/final-benchmark-v1"], "evaluation/final_benchmark_v1.json"),
        ("final_v2", refs["evaluation/final-benchmark-v2"], "evaluation/final_benchmark_v2.json"),
        ("final_v3", refs["evaluation/final-benchmark-v3"], "evaluation/final_benchmark_v3.json"),
    ):
        benchmark = git_json(ref, path)
        rows.extend({"set": label, "id": row["task_id"], "question": row["question"],
                     "formula": row.get("expected_formula")}
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
    for path in (*sorted((ROOT / "backend/tests").glob("test_*.py")),
                 *sorted((ROOT / "backend/scripts").glob("smoke_*.py"))):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        for index, node in enumerate(ast.walk(tree)):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and len(node.value) >= 35:
                if re.search(r"[가-힣]|\b(?:calculate|simulate|retrieve|pressure|porosity)\b",
                             node.value, re.I):
                    rows.append({"set": path.name, "id": str(index), "question": node.value})
    for path in (*sorted((ROOT / "evaluation/review").glob("*dev_smoke.json")),
                 *sorted((ROOT / "evaluation/dev").glob("*.json"))):
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        def visit(value: object, key: str = "") -> None:
            if isinstance(value, dict):
                for name, child in value.items():
                    visit(child, name)
            elif isinstance(value, list):
                for child in value:
                    visit(child, key)
            elif isinstance(value, str) and key in {
                "question", "message", "prompt", "goal", "topic", "user_message",
                "initial_message", "input", "request",
            } and len(value) >= 25:
                rows.append({"set": path.name, "id": str(len(rows)), "question": value})
        visit(data)
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
    return re.sub(r"[^\w#가-힣]", "", re.sub(r"\d+(?:\.\d+)?", "#",
                  unicodedata.normalize("NFKC", text).casefold()))


def normalized(text: str) -> str:
    return re.sub(r"[^\w가-힣]", "", unicodedata.normalize("NFKC", text).casefold())


def equation_shape(text: str) -> str | None:
    candidate = text if equation_ast(text) else next(
        (match.group("equation") for match in EQUATION.finditer(text)
         if equation_ast(match.group("equation"))), None)
    if not candidate:
        return None
    rhs = candidate.translate(TRANSLATION).split("=", 1)[1].strip()
    tree = ast.parse(rhs, mode="eval")
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            node.id = "VAR"
        elif isinstance(node, ast.Constant):
            node.value = 1
    return ast.dump(tree, include_attributes=False)


def source_audit(benchmark: dict) -> dict:
    import chromadb
    import pdfplumber

    collection = chromadb.PersistentClient(path=str(ROOT / "data/vector_db")).get_collection(
        "petroleum_knowledge")
    if collection.count() != 18976:
        raise RuntimeError(f"Existing collection count changed: {collection.count()}")
    metadata = collection.get(include=["metadatas"])["metadatas"]
    document_count = len({item.get("document") for item in metadata if item and item.get("document")})
    if document_count != 12:
        raise RuntimeError(f"Existing document count changed: {document_count}")
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
        note_name = source.get("figure_note")
        if len(pdf_text.strip()) < 100 and not note_name:
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
            "document_count": document_count,
            "sources": sources, "formula_span_matches": formula_hits}


def gold_audit(tasks: list[dict]) -> dict:
    calculations = [row for row in tasks if row.get("required_numeric_result")]
    resumptions = [row for row in tasks if row.get("expected_after_resume")]
    independent = {
        "D01": {"weighted_rate": (80 * 3 + 140 * 2) / 5},
        "D02": {"sample_sd": math.sqrt(sum((x - 6) ** 2 for x in (4, 6, 8)) / 2)},
        "D03": {"pipe_volume_bbl": 3.14159265 * (4 / 12 / 2)**2 * 1000 / 5.615},
        "D04": {"slope": (3040 - 3100) / 2},
        "D05": {"decrease_percent": (500 - 425) / 500 * 100},
        "D06": {"net_injection": 420 - 275},
        "D07": {"tracer_concentration": 5 * 1_000_000 / (250 * 1000)},
        "D08": {"energy_kwh": (55 + 40 + 65) * 6},
        "D09": {"hourly_rate": 720 / 24},
        "D10": {"central_derivative": (2860 - 3000) / (4 - 0)},
        "K01": {"L_ft": 30000 / 120}, "K02": {"HHPb_hp": 1050 - 320},
        "K03": {"Pt_psi": 70 + 300 + 850 + 180},
        "K04": {"DPVL_psi": 120 + 600 + 30},
        "K05": {"Popening_psi": 800 / (1 - 1 / 5)},
        "K06": {"Fcd": 6000 / 2000},
        "K07": {"Sw": (.75 - .15) / (1 - .15)},
        "K08": {"MSIG": .24 + .06},
        "K09": {"A": 90 / 15}, "K10": {"Mg_kg": 5000 - 1200},
        "K11": {"F_million_rb": sum((80, 12, 5, 3))},
        "K12": {"qo_stbd": 430 - 95},
        "U01": {"net_stbd": (500 - 120) * .9},
        "U02": {"t_arrival_s": 900 / 3000 + .12},
        "U03": {"P2_psi": 1500 / (1 + .05 * 4)},
        "U04": {"index": (3 * 3 + 5 * 5) / 2},
        "S01": {"case_count": len([.10 + .05 * i for i in range(5)]),
                "best_phi": .30, "best_score": max(100 * x / (1 + x) for x in [.10 + .05 * i for i in range(5)])},
        "S02": {"case_count": len(range(2, 11, 2)), "best_n": 2,
                "minimum_cost": min(50 + 8 * n for n in range(2, 11, 2))},
        "S03": {"case_count": len(range(0, 4)), "best_x": 3,
                "best_metric": max(4 * x**3 - 2 * x for x in range(0, 4))},
        "S04": {"case_count": len(range(1, 6)), "best_k": 5,
                "minimum_risk": min(120 / (k + 2) for k in range(1, 6))},
        "C01": {"weighted_rate": (100 * 3 + 200 * 2) / 5},
        "C02": {"R_mph": 600 / (20 * 3)},
        "C03": {"qo_stbd": 450 - 120},
        "C04": {"case_count": len(range(1, 6)), "best_x": 5,
                "best_score": max(4 * x for x in range(1, 6))},
    }
    audited = {}
    for row in calculations + resumptions:
        task_id = row["task_id"]
        gold = row.get("required_numeric_result") or row.get("expected_after_resume")
        expected = independent.get(task_id)
        if expected is None or set(gold) != set(expected):
            raise RuntimeError(f"Missing independent gold check: {task_id}")
        tolerance = float(row.get("tolerance", {}).get("absolute",
                                  row.get("resume_tolerance", 0)))
        if tolerance <= 0 or not row.get("expected_units"):
            raise RuntimeError(f"Missing tolerance/units: {task_id}")
        for field, value in gold.items():
            if not isinstance(value, (int, float)) or not math.isfinite(value):
                raise RuntimeError(f"Non-finite gold: {task_id}.{field}")
            if not math.isclose(value, expected[field], rel_tol=1e-8, abs_tol=tolerance):
                raise RuntimeError(f"Gold mismatch: {task_id}.{field}: {value} != {expected[field]}")
        if row.get("expected_formula") and equation_ast(row["expected_formula"]) is None:
            raise RuntimeError(f"Unparseable formula: {task_id}")
        audited[task_id] = {"independent": expected, "gold": gold, "tolerance": tolerance}
    return {"calculation_tasks": len(calculations), "resume_tasks": len(resumptions),
            "independent_arithmetic": audited}


def main() -> None:
    benchmark = json.loads(BENCHMARK.read_text(encoding="utf-8"))
    tasks = benchmark["tasks"]
    if benchmark["evaluated_product_sha"] != "9739350b95db212fd01d49683fb0d027f77d1fc7":
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
    equation_matches = []
    for index, row in enumerate(tasks):
        pairs = sorted(({
            "set": old_row["set"], "old_id": old_row["id"],
            "semantic_similarity": round(cosine(vectors[index], vectors[len(tasks) + j]), 4),
            "normalized_similarity": round(SequenceMatcher(
                None, normalized(row["question"]), normalized(old_row["question"])).ratio(), 4),
            "numeric_masked_similarity": round(SequenceMatcher(
                None, masked(row["question"]), masked(old_row["question"])).ratio(), 4),
            "old_question": old_row["question"],
        } for j, old_row in enumerate(old)), key=lambda x: max(
            x["semantic_similarity"], x["numeric_masked_similarity"]), reverse=True)
        top.append({"task_id": row["task_id"], "nearest_old": pairs[:3]})
        shape = equation_shape(row.get("expected_formula") or "")
        if shape:
            equation_matches.extend({"task_id": row["task_id"], "old_set": other["set"],
                                     "old_id": other["id"], "same_equation_structure": True}
                                    for other in old if equation_shape(
                                        other.get("formula") or other["question"]) == shape)
    source = source_audit(benchmark)
    gold = gold_audit(tasks)
    overlap = {source_id: {"document": item["document"], "page": item["page"]}
               for source_id, item in benchmark["source_catalog"].items()
               if (item["document"], item["page"]) in old_pages}
    flagged = [row for row in top if row["nearest_old"] and
               (row["nearest_old"][0]["semantic_similarity"] >= .86 or
                row["nearest_old"][0]["numeric_masked_similarity"] >= .78 or
                row["nearest_old"][0]["normalized_similarity"] >= .82)]
    result = {
        "benchmark_sha256": hashlib.sha256(BENCHMARK.read_bytes()).hexdigest(),
        "task_count": len(tasks), "category_distribution": dict(Counter(row["category"] for row in tasks)),
        "domain_distribution": dict(Counter(row["domain"] for row in tasks)),
        "old_evaluation_refs": refs, "old_question_count": len(old),
        "embedding_model": "qwen3-embedding:0.6b", "dedup_top_pairs": top,
        "maximum_semantic_similarity": max(x["nearest_old"][0]["semantic_similarity"] for x in top),
        "maximum_normalized_similarity": max(x["nearest_old"][0]["normalized_similarity"] for x in top),
        "maximum_numeric_masked_similarity": max(
            x["nearest_old"][0]["numeric_masked_similarity"] for x in top),
        "equation_structure_matches": equation_matches,
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
        "maximum_normalized_similarity": result["maximum_normalized_similarity"],
        "maximum_numeric_masked_similarity": result["maximum_numeric_masked_similarity"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
