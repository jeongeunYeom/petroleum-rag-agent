"""Pre-run and post-run integrity gate; never alters the frozen benchmark or KB."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter

import chromadb

from common import HERE, frozen_assets, frozen_product, load, now, save
from prepare_sources import DB, db_snapshot


def verify(*, post: bool) -> dict:
    frozen_assets()
    frozen_product()
    benchmark = load("benchmark.json")
    tasks = benchmark["primary_tasks"]
    probes = benchmark["resume_probes"]
    assert len(tasks) == 36 and len({r["task_id"] for r in tasks}) == 36
    assert Counter(r["category"] for r in tasks) == {
        "knowledge_qa":8,"multi_claim_reasoning":6,"direct_calculation":6,
        "user_formula":4,"kb_formula":6,"false_premise":3,"unanswerable":3}
    assert sum(bool(r["numeric_targets"]) for r in tasks) == 16
    assert sum(r["question_language"] == "ko" and bool(r["gold_sources"]) for r in tasks) == 12
    assert len(probes) == 4
    assert os.getenv("RETRIEVAL_MODE") == "hybrid", "RETRIEVAL_MODE must be hybrid"
    assert os.getenv("DATA_DIR", "").casefold() == str(DB.parent).casefold(), "DATA_DIR must use production KB parent"
    sys.path.insert(0, str(HERE.parents[1] / "backend"))
    from app.services.goal_message_parser import GoalMessageRequest, parse_goal_message
    parsed = [parse_goal_message(GoalMessageRequest(message=r["question"],model="qwen3:8b")) for r in tasks]
    assert all(p.use_internal and not p.use_external and p.execution_mode == "autonomous_goal_execution" for p in parsed), "web or non-autonomous route selected"
    before = load("kb_snapshot_before.json")
    current = db_snapshot()
    assert before == current, "KB file hashes changed"
    collection = chromadb.PersistentClient(path=str(DB)).get_collection("petroleum_knowledge")
    assert collection.count() == 18976
    metadata = collection.get(include=["metadatas"])["metadatas"]
    documents = {m.get("document") for m in metadata if m and m.get("document")}
    assert len(documents) == 12
    row = {"checked_at":now(),"phase":"post" if post else "pre","frozen_assets_unchanged":True,
           "product_code_unchanged":True,"kb_snapshot_unchanged":True,"collection":"petroleum_knowledge",
           "chunks":18976,"documents":12,"retrieval_mode":"hybrid","web":False,
           "primary":36,"numeric":16,"korean_english_source":12,"resume":4}
    if post:
        required = {"v21_2_agent":36,"qwen_closed_book":36,"gpt_reference":36}
        for system, count in required.items():
            files = sorted((HERE / "raw" / system).glob("V212U-*.json"))
            assert len(files) == count, f"{system} raw count {len(files)} != {count}"
            rows = [json.loads(path.read_text(encoding="utf-8")) for path in files]
            assert all(r.get("attempt_count") == 1 and r.get("status") == "completed" for r in rows), system
            assert len({r.get("attempt_id") for r in rows}) == count, f"duplicate attempt IDs: {system}"
        judge_files = sorted((HERE / "judge").glob("V212U-*.json"))
        assert len(judge_files) == 36
        assert all(json.loads(p.read_text(encoding="utf-8")).get("status") == "completed" for p in judge_files)
        row["raw_counts"] = required
        row["judge_count"] = 36
    save(HERE / ("integrity_post.json" if post else "integrity_pre.json"),row)
    return row


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--post",action="store_true")
    args = parser.parse_args()
    print(json.dumps(verify(post=args.post),ensure_ascii=False,indent=2))
