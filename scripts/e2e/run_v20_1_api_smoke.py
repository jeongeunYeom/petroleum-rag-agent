"""Real local-KB API smoke using the unchanged V20 browser prompt strings."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "evaluation" / "v20_1_dev" / "real_api_smoke.json"
API = os.getenv("V20_API_URL", "http://127.0.0.1:8001/api")
PROMPTS = {
    "A": "방향 측정기 근처에 Monel drill collar를 사용하는 이유를 내부 자료에 근거해 설명해줘.",
    "B": "비중(SG)이 0.918인 원유의 API gravity를 내부 교재의 관계식을 이용해 계산하고, 사용한 식과 출처를 검증해줘.",
    "C": "그럼 0.85면?",
    "D": "내부 Formation Evaluation 자료에서 공극률, 물 포화도, 물의 비저항과 지층의 진비저항 사이의 관계를 찾아서, φ=0.22, Sw=0.35, Rw=0.08 Ω·m, a=1, m=2, n=2일 때 Rt를 계산하고 근거와 계산 결과를 검증해줘.",
    "E": "내부 Drilling Engineering 자료에서 mud weight와 TVD를 이용한 hydrostatic pressure 관계식을 찾아서, MW=10.1 ppg일 때 압력을 계산하고 검증해줘.",
    "E_reply": "TVD는 8000 ft야.",
    "F": "A=187, B=234, C=163 stb/d의 평균을 구하고 큰 순서대로 정렬해줘.",
}
TERMINAL = {"completed", "stopped", "failed", "canceled", "waiting_for_user_input"}


def call(method: str, path: str, body: dict | None = None) -> dict:
    data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
    req = Request(API + path, data=data, method=method,
                  headers={"Content-Type": "application/json"})
    with urlopen(req, timeout=30) as response:
        return json.load(response)


def wait(run_id: str) -> dict:
    deadline = time.monotonic() + 480
    while time.monotonic() < deadline:
        run = call("GET", f"/research/goal-runs/{run_id}")
        if run["run_status"] in TERMINAL:
            return run
        time.sleep(.75)
    raise TimeoutError(run_id)


def trace(case: str, run: dict) -> dict:
    outputs = [{"calc_id": calc["computation_id"], **row,
                "formula_source_ids": calc.get("formula_source_ids", []),
                "validation_passed": calc.get("validation_passed")}
               for calc in run.get("computations", []) for row in calc.get("output_manifest", {}).values()]
    telemetry = run.get("telemetry") or {}
    return {"case": case, "prompt": PROMPTS[case], "run_id": run["run_id"],
            "run_status": run["run_status"], "goal_status": run["status"],
            "stop_reason": run.get("stop_reason"),
            "actions": [row["action_type"] for row in run.get("action_history", [])],
            "action_details": [{"type": row["action_type"], "details": row.get("details")}
                               for row in run.get("action_history", [])],
            "sources": [{"id": source["evidence_id"], "document": source["document"],
                         "page": source["page"]} for source in run.get("internal_sources", [])],
            "outputs": outputs, "required_inputs": run.get("required_inputs"),
            "clarification_question": run.get("clarification_question"),
            "final_answer": run.get("final_answer"),
            "telemetry": {key: telemetry.get(key) for key in (
                "conversation_context_used", "required_target_outputs", "target_output_satisfied",
                "formula_source_verified", "formula_dependency_target", "formula_dependency_resolution_success",
                "requested_semantic_target", "selected_formula_semantic_target",
                "group_unit_propagation_used", "group_unit_propagation_unit",
                "retrieval_refinement_used", "retrieval_refinement_query",
                "internal_calculation_error_type", "calculation_failure_stage")}}


def start(case: str, *, context: list[dict] | None = None) -> dict:
    response = call("POST", "/research/goal-runs/from-message",
                    {"message": PROMPTS[case], "model": "qwen3:8b",
                     "context_messages": context or []})
    return wait(response["run_id"])


def main() -> None:
    traces = []
    for case in ("B", "C", "D", "E", "E_reply", "F", "A"):
        try:
            if case == "C":
                run = start(case, context=[{"role": "user", "content": PROMPTS["B"]},
                                           {"role": "assistant", "content": prior["final_answer"] or "Completed."}])
            elif case == "E_reply":
                if prior["run_status"] != "waiting_for_user_input":
                    raise RuntimeError("E did not pause for clarification")
                response = call("POST", f"/research/goal-runs/{prior['run_id']}/resume",
                                {"message": PROMPTS[case]})
                run = wait(response["run_id"])
            else:
                run = start(case)
            traces.append(trace(case, run))
            prior = run
            print(case, run["run_id"], run["run_status"], run["status"],
                  ",".join(row["action_type"] for row in run.get("action_history", [])), flush=True)
        except Exception as exc:
            traces.append({"case": case, "prompt": PROMPTS[case], "error": str(exc)})
            print(case, "ERROR", type(exc).__name__, str(exc), flush=True)
            if case in {"B", "E"}:
                prior = {}
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps({"api_url": API, "model": "qwen3:8b",
                                   "retrieval_mode": "hybrid", "traces": traces},
                                  ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
