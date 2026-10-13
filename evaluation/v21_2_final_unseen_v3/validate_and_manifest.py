"""Independent pre-freeze task, source, arithmetic, and quota validation."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

import chromadb
import fitz
import sympy


HERE = Path(__file__).resolve().parent
RAW = Path(r"D:\petroleum-rag-agent\data\raw")
KB = Path(r"D:\petroleum-rag-agent\data\vector_db")
PRODUCT_SHA = "f5182b8ae2907452e1c53373055e66c5182c9b90"
QUOTAS = {
    "knowledge_qa": 8,
    "multi_claim_reasoning": 6,
    "direct_calculation": 6,
    "user_formula": 4,
    "kb_formula": 6,
    "false_premise": 3,
    "unanswerable": 3,
}


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def key(document: str, page: int) -> tuple[str, int]:
    return re.sub(r"[^a-z0-9]", "", document.casefold()), int(page)


def compact(text: str) -> str:
    return " ".join(text.split())


def main() -> None:
    benchmark_path = HERE / "benchmark.json"
    benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
    tasks = benchmark["primary_tasks"]
    probes = benchmark["resume_probes"]
    assert len(tasks) == 36 and len(probes) == 4
    assert [t["task_id"] for t in tasks] == [f"V212V3-{i:03d}" for i in range(1, 37)]
    assert len({p["probe_id"] for p in probes}) == 4
    assert dict(Counter(t["category"] for t in tasks)) == QUOTAS
    assert sum(bool(t["numeric_targets"]) for t in tasks) == 16
    assert sum(t["question_language"] == "ko" for t in tasks) == 12
    assert sum(t["multi_goal"] for t in tasks) == 6
    assert all(len(t["required_goals"]) >= 2 for t in tasks if t["multi_goal"])
    assert all(t["question_language"] != "ko" or (re.search("[가-힣]", t["question"]) and t["gold_sources"]) for t in tasks)
    assert all(2 <= len(t["required_claims"]) <= 4 for t in tasks if t["category"] == "multi_claim_reasoning")
    assert all((not t["answerable"]) == bool(t["missing_inputs"]) for t in tasks)
    assert all(bool(t["formula_source"]["required"]) == (t["category"] == "kb_formula") for t in tasks)
    assert all(bool(t["gold_sources"]) == bool(t["citation_required_for_agent"]) for t in tasks)
    assert all(t["forbidden_claims"] for t in tasks if t["category"] in {"false_premise", "unanswerable"})
    assert all(not re.search(r"API gravity|Archie|Monel|hydrostatic|ECD|productivity.index", t["question"], re.I) for t in tasks)

    pool = json.loads((HERE / "source_pool.json").read_text(encoding="utf-8"))
    excluded = json.loads((HERE / "excluded_sources.json").read_text(encoding="utf-8"))
    sampled = {(x["document"], x["page"]) for x in pool["candidates"]}
    forbidden = {(x["document_key"], x["page"]) for x in excluded["document_pages"]}
    novelty = json.loads((HERE / "novelty_results.json").read_text(encoding="utf-8"))
    assert novelty["max_lexical_similarity"] <= 0.45
    assert novelty["max_semantic_cosine"] <= novelty["semantic_cosine_limit"]

    collection = chromadb.PersistentClient(path=str(KB)).get_collection("petroleum_knowledge")
    assert collection.count() == 18976
    data = collection.get(include=["metadatas", "documents"])
    pages: dict[tuple[str, int], list[str]] = defaultdict(list)
    for meta, text in zip(data["metadatas"], data["documents"]):
        if meta and text and meta.get("document") and meta.get("page"):
            pages[(meta["document"], int(meta["page"]))].append(text)
    assert len({doc for doc, _ in pages}) == 12

    checked: set[tuple[str, int, str]] = set()
    pdf_cache: dict[str, fitz.Document] = {}
    try:
        for row in tasks + probes:
            sources = row["gold_sources"]
            for ref in sources:
                doc, page, span = ref["document"], int(ref["page"]), ref["exact_span"]
                assert (doc, page) in sampled, (row.get("task_id") or row.get("probe_id"), "not sampled")
                assert key(doc, page) not in forbidden, (doc, page, "previously used")
                assert span.strip() and (doc, page) in pages
                if doc not in pdf_cache:
                    files = [p for p in RAW.glob("*.pdf") if p.name.endswith(doc)]
                    assert len(files) == 1, (doc, "PDF not unique")
                    pdf_cache[doc] = fitz.open(files[0])
                pdf = pdf_cache[doc]
                assert 1 <= page <= len(pdf)
                assert span in pdf[page - 1].get_text(), (doc, page, "span absent in raw PDF")
                # The exact raw-PDF span can cross a chunk boundary; its leading
                # anchor and any formula must remain present in the indexed page.
                indexed = compact(" ".join(pages[(doc, page)]))
                assert compact(span[: min(len(span), 60)]) in indexed, (doc, page, "span anchor absent in Chroma")
                checked.add((doc, page, span))
            for target in row.get("numeric_targets", [row.get("numeric_target")] if row.get("numeric_target") else []):
                recomputed = float(sympy.sympify(target["deterministic_expression"]))
                assert abs(recomputed - float(target["expected_value"])) < 1e-8
                assert target["tolerance"] > 0 and target["expected_unit"]
            if row in tasks and row["category"] == "kb_formula":
                fs = row["formula_source"]
                assert fs["exact_formula_span"] in next(s["exact_span"] for s in sources if s["document"] == fs["document"] and s["page"] == fs["page"])
                assert compact(fs["exact_formula_span"]) in compact(" ".join(pages[(fs["document"], fs["page"])]))
                assert fs["exact_formula_span"] not in row["question"]
    finally:
        for pdf in pdf_cache.values():
            pdf.close()

    rubric = {
        "policy": "POLICY.md",
        "atomic_claim_scores": [0, 0.5, 1],
        "technical_failure": {"goal_success": 0, "claim_coverage": 0, "numeric_accuracy": 0, "citation_support": 0, "hallucination": False, "hallucination_free": True, "unnecessary_refusal": False},
        "tasks": [
            {
                "task_id": t["task_id"],
                "category": t["category"],
                "required_goals": t["required_goals"],
                "required_claims": t["required_claims"],
                "forbidden_claims": t["forbidden_claims"],
                "numeric_targets": t["numeric_targets"],
                "formula_source": t["formula_source"],
                "missing_inputs": t["missing_inputs"],
            }
            for t in tasks
        ],
    }
    (HERE / "rubric.json").write_text(json.dumps(rubric, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (HERE / "benchmark.sha256").write_text(digest(benchmark_path) + "  benchmark.json\n", encoding="utf-8")
    manifest = {
        "product_sha": PRODUCT_SHA,
        "benchmark_sha256": digest(benchmark_path),
        "rubric_sha256": digest(HERE / "rubric.json"),
        "seed": 20261013,
        "primary_task_count": 36,
        "numeric_task_count": 16,
        "korean_question_english_source_count": 12,
        "multi_goal_count": 6,
        "resume_probe_count": 4,
        "category_distribution": dict(Counter(t["category"] for t in tasks)),
        "domain_distribution": dict(Counter(t["domain"] for t in tasks)),
        "language_distribution": dict(Counter(t["question_language"] for t in tasks)),
        "source_document_distribution": dict(Counter(s["document"] for t in tasks for s in t["gold_sources"])),
        "unique_primary_source_pages": len({(s["document"], s["page"]) for t in tasks for s in t["gold_sources"]}),
        "excluded_prior_page_count": len(forbidden),
        "sampled_source_page_count": pool["sampled_page_count"],
        "validated_exact_source_spans": len(checked),
        "novelty": {k: novelty[k] for k in ("prior_prompt_count", "lexical_limit", "semantic_cosine_limit", "max_lexical_similarity", "max_semantic_cosine")},
        "evaluation_policy": "POLICY.md",
        "freeze_commit": "recorded in freeze_receipt.json after commit to avoid a self-reference",
    }
    (HERE / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print({"validated_tasks": len(tasks), "validated_spans": len(checked), "source_documents": len(manifest["source_document_distribution"]), "source_pages": manifest["unique_primary_source_pages"]})


if __name__ == "__main__":
    main()
