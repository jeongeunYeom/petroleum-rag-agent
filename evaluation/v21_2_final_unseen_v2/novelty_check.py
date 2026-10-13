"""Compare text mechanically without printing or exposing prior questions."""

from __future__ import annotations

import ast
import json
import re
import subprocess
import unicodedata
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
REPORT_SHA = "f04e56503564da9e9ac7c3bbbf5403dcf8cdea52"
LOCAL_BROWSER = Path(r"D:\petroleum-rag-agent\evaluation\v20_1_browser_e2e")
OLD_PREFIXES = (
    "evaluation/v20_1_browser_e2e/", "evaluation/v21_dev/",
    "evaluation/v21_1_dev/", "evaluation/v21_2_dev/",
    "evaluation/v21_2_regression_old24/raw/",
    "evaluation/agentic_heldout_v1.json", "evaluation/petroleum_agent_heldout_v1.json",
    "evaluation/final_benchmark_v1.json", "evaluation/final_benchmark_v2.json",
)
DEV_SCRIPT_PREFIXES = (
    "backend/scripts/run_v21_dev_smoke.py",
    "backend/scripts/run_v19_dev_smoke.py",
    "backend/scripts/run_v18_dev_smoke.py",
)
TEXT_KEYS = {"question", "prompt", "user_message", "input_message", "turn_1"}


def git(*args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=ROOT)


def old_prompts() -> tuple[list[str], dict[str, int]]:
    paths = git("ls-tree", "-r", "--name-only", REPORT_SHA, "evaluation", "backend/scripts").decode().splitlines()
    prompts: set[str] = set()
    counts = {prefix: 0 for prefix in (*OLD_PREFIXES, *DEV_SCRIPT_PREFIXES)}
    for path in paths:
        if "/judge/" in path:
            continue
        matching = next((prefix for prefix in (*OLD_PREFIXES, *DEV_SCRIPT_PREFIXES) if path.startswith(prefix)), None)
        if not matching:
            continue
        if path.endswith(".md") and matching in OLD_PREFIXES[:4]:
            local = {line.strip() for line in git("show", f"{REPORT_SHA}:{path}").decode("utf-8",errors="replace").splitlines() if 12 <= len(line.strip()) <= 1400}
            counts[matching] += len(local)
            prompts.update(local)
            continue
        if path.endswith(".py") and matching in DEV_SCRIPT_PREFIXES:
            try:
                tree = ast.parse(git("show", f"{REPORT_SHA}:{path}").decode("utf-8",errors="replace"))
                local = {node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value,str) and 12 <= len(node.value) <= 1400}
            except SyntaxError:
                local = set()
            counts[matching] += len(local)
            prompts.update(local)
            continue
        if not path.endswith(".json"):
            continue
        try:
            data = json.loads(git("show", f"{REPORT_SHA}:{path}"))
        except (subprocess.CalledProcessError, json.JSONDecodeError):
            continue
        local: set[str] = set()

        def walk(value: object) -> None:
            if isinstance(value, dict):
                for key, child in value.items():
                    if key in TEXT_KEYS and isinstance(child, str) and 12 <= len(child) <= 1400:
                        local.add(child)
                    else:
                        walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)

        walk(data)
        counts[matching] += len(local)
        prompts.update(local)
    browser_count = 0
    if LOCAL_BROWSER.is_dir():
        for path in sorted(LOCAL_BROWSER.rglob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            local: set[str] = set()

            def walk_browser(value: object) -> None:
                if isinstance(value, dict):
                    for key, child in value.items():
                        if key in TEXT_KEYS and isinstance(child, str) and 12 <= len(child) <= 1400:
                            local.add(child)
                        else:
                            walk_browser(child)
                elif isinstance(value, list):
                    for child in value:
                        walk_browser(child)

            walk_browser(data)
            browser_count += len(local)
            prompts.update(local)
    counts["local D:/petroleum-rag-agent/evaluation/v20_1_browser_e2e/"] = browser_count
    return sorted(prompts), counts


def normalize(value: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value).casefold()).strip()


def fourgrams(value: str) -> set[str]:
    value = normalize(value)
    return {value[i:i + 4] for i in range(max(0, len(value) - 3))}


def score(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def eight_word_overlap(a: str, b: str) -> bool:
    aa = re.findall(r"\w+", normalize(a))
    bb = re.findall(r"\w+", normalize(b))
    if len(aa) < 8 or len(bb) < 8:
        return False
    grams = {tuple(aa[i:i + 8]) for i in range(len(aa) - 7)}
    return any(tuple(bb[i:i + 8]) in grams for i in range(len(bb) - 7))


def main() -> None:
    old, counts = old_prompts()
    old_grams = [fourgrams(p) for p in old]
    benchmark = json.loads((OUT / "benchmark.json").read_text(encoding="utf-8"))
    rows = []
    for task in benchmark["primary_tasks"]:
        question = task["question"]
        grams = fourgrams(question)
        best = max((score(grams, other) for other in old_grams), default=0.0)
        long_copy = any(eight_word_overlap(question, prior) for prior in old)
        rows.append({"task_id": task["task_id"], "max_char4_jaccard": round(best, 4),
                     "eight_word_overlap": long_copy, "pass": best <= 0.45 and not long_copy})
    for task in benchmark["resume_probes"]:
        question = task["turn_1"]
        grams = fourgrams(question)
        best = max((score(grams, other) for other in old_grams), default=0.0)
        long_copy = any(eight_word_overlap(question, prior) for prior in old)
        rows.append({"task_id": task["probe_id"], "max_char4_jaccard": round(best, 4),
                     "eight_word_overlap": long_copy, "pass": best <= 0.45 and not long_copy})
    result = {"method": "Unicode NFKC casefolded character-4-gram Jaccard plus exact 8-word overlap", "threshold": 0.45,
              "prior_prompt_count": len(old), "prior_prompt_sources": counts, "rows": rows}
    (OUT / "novelty_check.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"prior_prompt_count":len(old),"max_similarity":max(r["max_char4_jaccard"] for r in rows),"failed_task_ids":[r["task_id"] for r in rows if not r["pass"]],"source_counts":counts},indent=2))
    assert all(row["pass"] for row in rows), "near-duplicate candidate: reject before freeze"


if __name__ == "__main__":
    main()
