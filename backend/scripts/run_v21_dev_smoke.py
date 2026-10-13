"""Fresh, non-frozen production-KB development probes for v21."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


API = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://127.0.0.1:8002/api"
ONLY = set(sys.argv[2].split(",")) if len(sys.argv) > 2 else None
OUTPUT = Path(__file__).resolve().parents[2] / "evaluation" / "v21_dev" / "real_kb_smoke.json"
CASES = [
    ("K1", "knowledge", "내부 자료에서 상대투과도가 다상 유체 흐름에 미치는 영향을 설명해줘.", None),
    ("K2", "knowledge", "Explain how a well productivity index relates flow rate to drawdown using internal sources.", None),
    ("X1", "cross_language", "지층 비저항의 의미를 영어 교재 근거로 설명해줘.", None),
    ("X2", "cross_language", "이수 밀도와 정수압의 관계를 내부 자료 근거로 설명해줘.", None),
    ("D1", "direct", "초기 유량은 420 stb/d이고 변경 후 유량은 525 stb/d이다. 증가율을 계산해줘.", None),
    ("D2", "direct", "입구 압력은 3100 psi, 출구 압력은 2860 psi이다. 압력 강하량을 구해줘.", None),
    ("D3", "direct", "주입량 800 bbl 중 620 bbl을 회수했다. 회수율을 계산해줘.", None),
    ("F1", "kb_formula", "MW=9.4 ppg, TVD=6500 ft일 때 내부 시추 교재의 관계식으로 hydrostatic pressure를 계산해줘.", None),
    ("F2", "kb_formula", "phi=0.26, a=1.1, m=1.8이다. 내부 지층평가 교재에서 formation factor F의 식을 찾아 계산해줘.", None),
    ("F3", "kb_formula", "저류층의 k=75 mD, mu=2 cP이다. 내부 자료의 mobility 관계식을 찾아 유체 mobility를 계산해줘.", None),
    ("C1", "chain", "phi=0.26, a=1.1, m=1.8, Sw=0.42, Rw=0.12 Ω·m, n=2이다. 내부 지층평가 자료에서 F와 Rt 관계식을 찾아 Rt를 계산해줘.", None),
    ("C2", "chain", "MW=9.6 ppg, TVD=7200 ft, annular pressure loss=260 psi이다. 내부 시추 자료의 정수압과 ECD 관계식을 각각 찾아 ECD를 계산해줘.", None),
    ("R1", "resume", "phi=0.27, a=1.05이다. 내부 지층평가 교재의 formation factor F 식을 찾아 계산해줘.", "m=1.9"),
    ("R2", "resume", "MW=9.2 ppg이다. 내부 시추 교재의 정수압 관계식으로 hydrostatic pressure를 계산해줘.", "TVD=6900 ft"),
]


def call(method: str, path: str, payload: dict | None = None) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    request = Request(API + path, data=body, method=method,
                      headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=30) as response:
        return json.load(response)


def finished(run_id: str, timeout: float = 240) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        row = call("GET", f"/research/goal-runs/{run_id}")
        if row["run_status"] not in {"planned", "running"}:
            return row
        time.sleep(2)
    raise TimeoutError(f"run {run_id} exceeded {timeout}s")


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    existing = json.loads(OUTPUT.read_text(encoding="utf-8")).get("cases", []) if ONLY and OUTPUT.exists() else []
    rows = {row["id"]: row for row in existing}
    for _ in range(30):
        try:
            call("GET", "/system/checklist")
            break
        except URLError:
            time.sleep(2)
    else:
        raise RuntimeError("development backend did not become ready")
    for case_id, category, message, reply in CASES:
        if ONLY and case_id not in ONLY:
            continue
        started = time.monotonic()
        try:
            first = call("POST", "/research/goal-runs/from-message", {"message": message, "model": "qwen3:8b"})
            result = finished(first["run_id"])
            waiting = result["run_status"] == "waiting_for_user_input"
            same_run = None
            if reply and waiting:
                resumed = call("POST", f"/research/goal-runs/{first['run_id']}/resume", {"message": reply})
                same_run = resumed["run_id"] == first["run_id"]
                result = finished(first["run_id"])
            calculations = [item for item in result.get("computations", []) if item.get("validation_passed")]
            actions = [item["action_type"] for item in result.get("action_history", [])]
            grounded = bool(result.get("internal_sources")) and bool(result.get("final_answer"))
            passed = (result.get("status") == "achieved" and
                      (bool(calculations) if category in {"direct", "kb_formula", "chain", "resume"} else grounded) and
                      ("retrieve" not in actions if category == "direct" else True) and
                      (len(calculations) >= 2 if category == "chain" else True) and
                      (waiting and same_run if category == "resume" else True))
            rows[case_id] = {"id": case_id, "category": category, "pass": bool(passed), "run_id": first["run_id"],
                         "run_status": result.get("run_status"), "status": result.get("status"),
                         "actions": actions, "waiting_before_resume": waiting, "same_run_resume": same_run,
                         "validated_calculations": len(calculations),
                         "outputs": [calc.get("output_manifest", {}) for calc in calculations],
                         "sources": [{"document": item.get("document"), "page": item.get("page")}
                                     for item in result.get("internal_sources", [])],
                         "elapsed_seconds": round(time.monotonic() - started, 3),
                         "telemetry": {key: result.get("telemetry", {}).get(key) for key in
                                       ("request_computation_class", "formula_candidates_considered",
                                        "formula_source_verified", "formula_variables_missing",
                                        "clarification_resolved", "calculation_failure_stage")},
                         "answer_prefix": result.get("final_answer", "")[:400]}
        except (HTTPError, URLError, TimeoutError, ValueError, KeyError) as exc:
            rows[case_id] = {"id": case_id, "category": category, "pass": False,
                         "error": f"{type(exc).__name__}: {exc}",
                         "elapsed_seconds": round(time.monotonic() - started, 3)}
        ordered = [rows[name] for name, *_ in CASES if name in rows]
        OUTPUT.write_text(json.dumps({"type": "v21_development_smoke", "cases": ordered},
                                     ensure_ascii=False, indent=2), encoding="utf-8")
        print(case_id, "PASS" if rows[case_id]["pass"] else "FAIL", rows[case_id].get("actions", []),
              rows[case_id]["elapsed_seconds"], flush=True)


if __name__ == "__main__":
    main()
