"""Read-only shortlist of unused literal equations in the existing extracted corpus."""

from __future__ import annotations

import json
import argparse
from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from app.services.formula_source_registry import FormulaSourceRegistry  # noqa: E402


def old_pages() -> set[tuple[str, int]]:
    used = set()
    for version in (1, 2, 3):
        raw = subprocess.check_output(
            ["git", "show", f"evaluation/final-benchmark-v{version}:evaluation/final_benchmark_v{version}.json"],
            cwd=ROOT,
        )
        benchmark = json.loads(raw)
        used.update((row["document"], row["page"])
                    for row in benchmark.get("source_catalog", {}).values())
    return used


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--doc")
    parser.add_argument("--page", type=int)
    parser.add_argument("--find")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--start", type=int, default=1)
    args = parser.parse_args()
    used = old_pages()
    for path in sorted((ROOT / "data/extracted").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        document = data["chunks"][0]["metadata"]["document"]
        if args.doc and args.doc.casefold() not in document.casefold():
            continue
        if args.page is not None:
            for page in data["pages"]:
                if page["page"] == args.page:
                    print(f"### {document} p{args.page}\n{page['text']}")
            continue
        if args.find:
            count = 0
            for page in data["pages"]:
                if (document, page["page"]) in used:
                    continue
                for line in page["text"].splitlines():
                    if re.search(args.find, line, re.I):
                        excerpt = re.sub(r"\s+", " ", line).strip()[:180]
                        print(f"p{page['page']}: {excerpt}")
                        count += 1
                        if count >= args.limit:
                            break
                if count >= args.limit:
                    break
            continue
        print(f"\n### {document}")
        printed = 0
        for page in data["pages"]:
            if page["page"] < args.start:
                continue
            if (document, page["page"]) in used:
                continue
            lines = [re.sub(r"\s+", " ", line).strip() for line in page["text"].splitlines()]
            for line in lines:
                if "=" not in line or len(line) > 125 or len(line) < 7:
                    continue
                records = FormulaSourceRegistry.from_evidence([{
                    "source_type": "knowledge_base", "evidence_id": "scan", "text": line,
                }]).records
                if (records and records[0].equation_ast and records[0].expression_candidate
                        and re.search(r"[+*/−-]", records[0].expression_candidate.split("=", 1)[1])):
                    print(f"p{page['page']}: {line[:115]} | {records[0].expression_candidate}")
                    printed += 1
                    if printed >= args.limit:
                        break
            if printed >= args.limit:
                break


if __name__ == "__main__":
    main()
