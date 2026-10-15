"""Turn complete, task-level V4 semantic verdicts into audit-ready reports."""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FROZEN = "62e5c36f3d66e25addc8a2c37b63af12e2636e78"


def read(name: str) -> dict:
    return json.loads((HERE / name).read_text(encoding="utf-8"))


def sha(name: str) -> str:
    return hashlib.sha256((HERE / name).read_bytes()).hexdigest()


def pct(numerator: int, denominator: int) -> str:
    return f"{100 * numerator / denominator:.1f}%" if denominator else "n/a"


def summary(items: list[dict], condition: str) -> dict:
    rows = [item[condition] for item in items]
    goals = sum(row["goal_success"] is True for row in rows)
    completions = sum(row["task_completion"] is True for row in rows)
    hf = sum(row["hallucination_free"] is True for row in rows)
    covered = sum(row["covered_claims"] for row in rows)
    claims = sum(row["claim_count"] for row in rows)
    numeric_rows = [row for row in rows if row["numeric_accuracy"] is not None]
    numeric = sum(row["numeric_accuracy"] is True for row in numeric_rows)
    cited = sum(row.get("cited_claims", 0) for row in rows)
    cited_supported = sum(row.get("supported_cited_claims", 0) for row in rows)
    return {"goal_success": goals, "task_completion": completions,
            "hallucination_free": hf, "covered_claims": covered, "claim_count": claims,
            "numeric_accuracy": numeric, "numeric_denominator": len(numeric_rows),
            "cited_claims": cited, "supported_cited_claims": cited_supported,
            "uncertain_tasks": sum(row.get("uncertain", False) for row in rows),
            "citation_omissions": sum(row.get("citation_omissions", 0) for row in rows)}


def check() -> tuple[dict, dict, dict]:
    catalog = read("v4_catalog.json")
    catalog_hash = sha("v4_catalog.json")
    if catalog_hash != (HERE / "v4_catalog.sha256").read_text(encoding="ascii").split()[0]:
        raise RuntimeError("Sealed catalog changed")
    semantic = read("semantic_scores.json")
    automatic = read("automatic_scores.json")
    if semantic["catalog_sha256"] != catalog_hash or semantic["rubric_sha256"] != sha("V4_SCORING_RUBRIC.md"):
        raise RuntimeError("Semantic review targets a different catalog or rubric")
    if len(semantic["items"]) != 60 or len(catalog["tasks"]) != 60:
        raise RuntimeError("Incomplete semantic review")
    by_id = {item["id"]: item for item in semantic["items"]}
    if len(by_id) != 60 or set(by_id) != {task["id"] for task in catalog["tasks"]}:
        raise RuntimeError("Missing or duplicate task verdict")
    for task in catalog["tasks"]:
        item = by_id[task["id"]]
        expected_claims = len(task["gold"]["atomic_claims"]) + len(task["gold"]["numeric_outputs"])
        for condition in ("agent", "qwen_closed_book"):
            row = item[condition]
            if (row["claim_count"] != expected_claims or not 0 <= row["covered_claims"] <= expected_claims
                    or not isinstance(row["rationale"], str) or not row["rationale"].strip()):
                raise RuntimeError(f"Incomplete verdict: {task['id']} {condition}")
            if (condition == "agent" and (row["cited_claims"] < row["supported_cited_claims"]
                                         or row["citation_omissions"] < 0)):
                raise RuntimeError(f"Invalid citation counts: {task['id']}")
    if subprocess.run(["git", "diff", "--quiet", FROZEN, "HEAD", "--", "backend", "frontend"],
                      cwd=ROOT, check=False).returncode != 0:
        raise RuntimeError("Product differs from frozen SHA")
    return catalog, semantic, automatic


def main() -> None:
    catalog, semantic, automatic = check()
    items = semantic["items"]
    agent = summary(items, "agent")
    qwen = summary(items, "qwen_closed_book")
    catalog_hash = sha("v4_catalog.json")
    by_id = {item["id"]: item for item in items}
    categories = Counter(task["category"] for task in catalog["tasks"])
    failure_lines = []
    category_lines = []
    for category, count in categories.items():
        subset = [by_id[task["id"]]["agent"] for task in catalog["tasks"]
                  if task["category"] == category]
        gs = sum(row["goal_success"] is True for row in subset)
        tc = sum(row["task_completion"] is True for row in subset)
        category_lines.append(f"| {category} | {gs}/{count} ({pct(gs,count)}) | {tc}/{count} ({pct(tc,count)}) |")
    for task in catalog["tasks"]:
        row = by_id[task["id"]]["agent"]
        if row["goal_success"] is not True:
            kinds = ", ".join(row["failure_classes"]) or "uncertain/unspecified"
            failure_lines.append(f"| {task['id']} | {task['category']} | {kinds} | {row['rationale']} |")
    latency_lines = []
    for category in ("direct", "user_formula", "knowledge", "kb_formula", "multi_goal", "resume", "overall"):
        value = automatic["summary"]["agent_latency"][category]
        latency_lines.append(f"| {category} | {value['n']} | {value['median_seconds']:.3f} s | {value['p95_seconds']:.3f} s |")

    def metric_lines(s: dict) -> list[str]:
        return [f"Goal Success: **{s['goal_success']}/60 ({pct(s['goal_success'],60)})**",
                f"Task Completion: **{s['task_completion']}/60 ({pct(s['task_completion'],60)})**",
                f"Claim Coverage: **{s['covered_claims']}/{s['claim_count']} ({pct(s['covered_claims'],s['claim_count'])})**",
                f"Hallucination-Free: **{s['hallucination_free']}/60 ({pct(s['hallucination_free'],60)})**",
                f"Numerical Accuracy: **{s['numeric_accuracy']}/{s['numeric_denominator']} ({pct(s['numeric_accuracy'],s['numeric_denominator'])})**"]

    report = ["# Final Unseen V4 — frozen V23 Agent",
              "", "This is a one-shot final unseen measurement of the frozen product, not a development gate."
              " Results are reported as observed; no item was dropped or changed after catalog sealing.", "",
              "## Integrity and conditions", "",
              f"- Frozen product SHA: `{FROZEN}`. Evaluation branch: `eval/v23-final-unseen-v4`."
              " Catalog/harness commit: `2de2ab847e30d245089ae57930e44cd3d014f5ff`;"
              " evaluation-only harness repair: `0c97f3ca4f91ad9509495d2709955c3927a950f5`.",
              f"- Sealed catalog SHA-256: `{catalog_hash}`. Rubric SHA-256: `{sha('V4_SCORING_RUBRIC.md')}`.",
              "- Existing read-only KB: `petroleum_knowledge`, 12 documents / 18,976 chunks;"
              " `chroma.sqlite3` precheck SHA-256 `1b389044d7efec1273a5d4d52a999d4831188e08a808d4a956a72ba816659fea`.",
              "- Local model: `qwen3:8b` (Ollama digest `500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41`)."
              " Agent used hybrid KB retrieval and bounded tools; web was disabled."
              " Qwen baseline was closed-book, with no KB, tools, or gold text.",
              "- Product code, retrieval behavior and sealed catalog remained unchanged after V4 execution began."
              " The initial harness-only Chroma settings incident is preserved separately in `HARNESS_INCIDENT.md`."
              " Its 60 zero-time infrastructure rows were not model answers; the same immutable catalog was rerun"
              " after an evaluation-only settings fix. No task was silently excluded.",
              "", "## Frozen Agent metrics", "", *["- " + line for line in metric_lines(agent)],
              f"- Citation Support Rate: **{agent['supported_cited_claims']}/{agent['cited_claims']}"
              f" ({pct(agent['supported_cited_claims'],agent['cited_claims'])})**;"
              f" citation omissions recorded: {agent['citation_omissions']}.",
              f"- Uncertain semantic judgments: **{agent['uncertain_tasks']}**;"
              " unresolved cases are not silently counted as successes.",
              "", "## Agent category results", "",
              "| Category | Goal Success | Task Completion |", "|---|---:|---:|", *category_lines,
              "", "## Qwen3:8b closed-book vs frozen Agent", "",
              "The conditions do **not** have equal information access: the Agent had its internal KB and"
              " tools, while Qwen answered from the same visible user turns without retrieval or tools.", "",
              "| Metric | Qwen closed-book | Frozen Agent |", "|---|---:|---:|",
              f"| Goal Success | {qwen['goal_success']}/60 ({pct(qwen['goal_success'],60)}) | {agent['goal_success']}/60 ({pct(agent['goal_success'],60)}) |",
              f"| Claim Coverage | {qwen['covered_claims']}/{qwen['claim_count']} ({pct(qwen['covered_claims'],qwen['claim_count'])}) | {agent['covered_claims']}/{agent['claim_count']} ({pct(agent['covered_claims'],agent['claim_count'])}) |",
              f"| Hallucination-Free | {qwen['hallucination_free']}/60 ({pct(qwen['hallucination_free'],60)}) | {agent['hallucination_free']}/60 ({pct(agent['hallucination_free'],60)}) |",
              f"| Numerical Accuracy | {qwen['numeric_accuracy']}/{qwen['numeric_denominator']} ({pct(qwen['numeric_accuracy'],qwen['numeric_denominator'])}) | {agent['numeric_accuracy']}/{agent['numeric_denominator']} ({pct(agent['numeric_accuracy'],agent['numeric_denominator'])}) |",
              "", "## Agent reliability and latency", "",
              f"- Technical crashes: {automatic['summary']['agent_crashes']};"
              f" blank responses: {automatic['summary']['agent_blank']};"
              f" raw error leaks: {automatic['summary']['agent_raw_error_leaks']};"
              f" invalid citation-ID rows: {automatic['summary']['agent_invalid_citation_id_rows']};"
              f" repeated identical clarifications: {automatic['summary']['agent_repeated_clarifications']};"
              f" external-source rows: {automatic['summary']['agent_external_source_rows']}.",
              "", "| Category | N | Median | P95 |", "|---|---:|---:|---:|", *latency_lines,
              "", "## All Agent Goal Success failures", "",
              "| ID | Category | Failure class | Task-level rationale |", "|---|---|---|---|",
              *(failure_lines or ["| None | — | — | — |"]),
              "", "## Scoring method and limitations", "",
              "Automatic flags checked status, numeric tolerance/unit candidates, citation IDs, technical"
              " events and latency. One frozen rubric then guided **single-reviewer AI-assisted semantic"
              " adjudication** of every task, preserving task-level rationale in `semantic_scores.json`."
              " A valid citation ID alone did not establish semantic support. Numeric heuristic matches"
              " were reviewed against target attribution and units. There was no human multi-reviewer"
              " consensus, no equal-information-access baseline, and only one catalog/model seed.",
              "", "## Poster-safe conclusions", "",
              "- Quote observed numerators and denominators, not aspirational protocol targets.",
              "- Interpret the closed-book comparison as a product-plus-KB/tools contrast, not a"
              " pure model-quality comparison.",
              "- The V4 results are final for this frozen SHA. Any product repair motivated by V4"
              " would require a new unseen V5 for a new final claim.", ""]
    (HERE / "V4_FINAL_REPORT.md").write_text("\n".join(report), encoding="utf-8")

    poster = ["# V4 poster numbers — frozen product", "",
              f"Product `{FROZEN}`; catalog `{catalog_hash}`; 60 sealed tasks; local `qwen3:8b`.",
              "Qwen comparison is closed-book without KB/tools; Agent has internal KB/tools."
              " Single-reviewer AI-assisted semantic adjudication; no human consensus.", "",
              "| Metric | Frozen Agent | Qwen closed-book |", "|---|---:|---:|",
              f"| Goal Success | {agent['goal_success']}/60 ({pct(agent['goal_success'],60)}) | {qwen['goal_success']}/60 ({pct(qwen['goal_success'],60)}) |",
              f"| Task Completion | {agent['task_completion']}/60 ({pct(agent['task_completion'],60)}) | {qwen['task_completion']}/60 ({pct(qwen['task_completion'],60)}) |",
              f"| Claim Coverage | {agent['covered_claims']}/{agent['claim_count']} ({pct(agent['covered_claims'],agent['claim_count'])}) | {qwen['covered_claims']}/{qwen['claim_count']} ({pct(qwen['covered_claims'],qwen['claim_count'])}) |",
              f"| Hallucination-Free | {agent['hallucination_free']}/60 ({pct(agent['hallucination_free'],60)}) | {qwen['hallucination_free']}/60 ({pct(qwen['hallucination_free'],60)}) |",
              f"| Numerical Accuracy | {agent['numeric_accuracy']}/{agent['numeric_denominator']} ({pct(agent['numeric_accuracy'],agent['numeric_denominator'])}) | {qwen['numeric_accuracy']}/{qwen['numeric_denominator']} ({pct(qwen['numeric_accuracy'],qwen['numeric_denominator'])}) |",
              f"| Citation Support (Agent only) | {agent['supported_cited_claims']}/{agent['cited_claims']} ({pct(agent['supported_cited_claims'],agent['cited_claims'])}) | n/a |",
              "", f"Agent overall latency median / P95: {automatic['summary']['agent_latency']['overall']['median_seconds']:.3f} /"
              f" {automatic['summary']['agent_latency']['overall']['p95_seconds']:.3f} s.",
              "Do not label closed-book Qwen as having the same evidence or tools.", ""]
    (HERE / "V4_POSTER_NUMBERS.md").write_text("\n".join(poster), encoding="utf-8")
    print(json.dumps({"agent": agent, "qwen_closed_book": qwen,
                      "agent_failed_ids": [task["id"] for task in catalog["tasks"]
                                           if by_id[task["id"]]["agent"]["goal_success"] is not True]},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
