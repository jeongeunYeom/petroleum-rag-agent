"""Independent structural/source/numeric validation before benchmark freeze."""

from __future__ import annotations

import ast
import hashlib
import json
import math
import operator
from collections import Counter
from pathlib import Path


OUT = Path(__file__).resolve().parent
PRODUCT_SHA = "f5182b8ae2907452e1c53373055e66c5182c9b90"
OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
       ast.Div: operator.truediv, ast.Pow: operator.pow}


def evaluate(expression: str) -> float:
    def visit(node: ast.AST) -> float:
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return -visit(node.operand)
        if isinstance(node, ast.BinOp) and type(node.op) in OPS:
            return OPS[type(node.op)](visit(node.left), visit(node.right))
        raise ValueError(f"unsafe numeric gold expression: {expression}")
    return visit(ast.parse(expression, mode="eval").body)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    benchmark = json.loads((OUT / "benchmark.json").read_text(encoding="utf-8"))
    tasks = benchmark["primary_tasks"]
    probes = benchmark["resume_probes"]
    pool = json.loads((OUT / "source_pool.json").read_text(encoding="utf-8"))
    exclusions = json.loads((OUT / "excluded_sources.json").read_text(encoding="utf-8"))
    novelty = json.loads((OUT / "novelty_check.json").read_text(encoding="utf-8"))
    pages = {(r["document"],r["page"]):r["text"] for r in pool["sources"]}
    excluded = {(r["document"],r["page"]) for r in exclusions["document_pages"]}
    assert len(tasks) == 36 and len(probes) == 4
    assert len({r["task_id"] for r in tasks}) == 36
    assert Counter(r["category"] for r in tasks) == {
        "knowledge_qa":8,"multi_claim_reasoning":6,"direct_calculation":6,
        "user_formula":4,"kb_formula":6,"false_premise":3,"unanswerable":3}
    assert sum(bool(r["numeric_targets"]) for r in tasks) == 16
    assert sum(r["question_language"] == "ko" for r in tasks) == 12
    assert sum(r["multi_goal"] for r in tasks) == 6
    assert all(r["pass"] for r in novelty["rows"])
    assert len(novelty["rows"]) == 40
    used = set()
    for row in tasks:
        assert row["required_claims"] and row["required_goals"]
        assert row["question_language"] in {"en","ko"}
        for source in row["gold_sources"]:
            key = (source["document"],source["page"])
            assert key in pages and key not in excluded, row["task_id"]
            assert source["exact_supporting_span"] in pages[key], row["task_id"]
            used.add(key)
        if row["category"] in {"knowledge_qa","multi_claim_reasoning","kb_formula","false_premise"}:
            assert row["gold_sources"], row["task_id"]
        if row["category"] == "kb_formula":
            f = row["formula_source"]
            assert f["required"] and (f["document"],f["page"]) in used
            assert f["exact_formula_span"] in pages[(f["document"],f["page"])], row["task_id"]
            assert f["exact_formula_span"].strip(), row["task_id"]
        for target in row["numeric_targets"]:
            independently_computed = evaluate(target["computation_expression"])
            assert math.isclose(independently_computed,target["expected_value"],rel_tol=1e-10,abs_tol=1e-10), row["task_id"]
            assert target["expected_unit"] and target["absolute_tolerance"] > 0
        if row["category"] == "unanswerable":
            assert not row["answerable"] and row["missing_inputs"] and not row["numeric_targets"]
        else:
            assert row["answerable"]
    for probe in probes:
        assert probe["turn_1"] != probe["turn_2"] and probe["missing_input"]
        assert math.isfinite(probe["expected_value"])

    manifest = {
        "evaluated_product_sha":PRODUCT_SHA,"seed":20261013,
        "primary_count":36,"resume_count":4,"numeric_count":16,"cross_language_count":12,
        "multi_goal_count":6,"category_distribution":dict(Counter(r["category"] for r in tasks)),
        "domain_distribution":dict(Counter(r["domain"] for r in tasks)),
        "question_language_distribution":dict(Counter(r["question_language"] for r in tasks)),
        "source_document_distribution":dict(Counter(s["document"] for r in tasks for s in r["gold_sources"])),
        "source_page_distribution":[{"document":d,"page":p} for d,p in sorted(used)],
        "source_selection":"Fixed seed 20261013; stratified pre-authoring Chroma pages, 14 equation-like plus 8 other per document. Previously used pages excluded mechanically.",
        "excluded_source_pairs":len(excluded),"excluded_source_provenance":exclusions["from_directories"],
        "novelty_method":novelty["method"],"novelty_threshold":novelty["threshold"],
        "prior_prompt_count":novelty["prior_prompt_count"],
        "max_similarity_per_task":{r["task_id"]:r["max_char4_jaccard"] for r in novelty["rows"]},
        "rejected_candidates":[],
        "validation":"Independent AST numeric recomputation, literal source/formula span membership, exclusion/novelty/quotas, and manual source-meaning review before freeze. No evaluated product call.",
        "evaluation_policy":"One attempt per system/task; no post-result replacement or rubric change; blinded single-reviewer AI-assisted semantic adjudication; paired bootstrap 10000 seed 20261013.",
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
    (OUT / "benchmark.sha256").write_text(sha(OUT / "benchmark.json")+"\n",encoding="ascii")
    print(json.dumps({"validated_tasks":len(tasks),"validated_resume":len(probes),"used_source_pages":len(used),
                      "excluded_source_pairs":len(excluded),"max_novelty_similarity":max(r["max_char4_jaccard"] for r in novelty["rows"]),
                      "benchmark_sha256":sha(OUT / "benchmark.json"),"rubric_sha256":sha(OUT / "rubric.json")},indent=2))


if __name__ == "__main__":
    main()
