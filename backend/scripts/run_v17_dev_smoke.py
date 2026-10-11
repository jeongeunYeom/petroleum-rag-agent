"""Opt-in local-model development smoke, with fresh synthetic retrieval fixtures.

Not a benchmark: real GoalExecutionAgent, qwen semantic judge and Python sandbox;
retrieval passages and rejecting evaluator are controlled to isolate fallback.
Never opens Chroma or any frozen evaluation directory.
"""
import asyncio
import hashlib
import json
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))

from app.core.config import Settings
from app.services.ollama import OllamaClient
from app.services.goal_execution_agent import GoalExecutionAgent
from test_agent_reliability_v17_dev import Sources, Evaluator, refusal, req, PASSAGES, MULTI


async def main():
    output = Path(sys.argv[1])
    if output.exists():
        raise SystemExit("Refusing to overwrite an existing development run")
    workspace = Path(tempfile.mkdtemp(prefix="petroleum-v17-dev-"))
    settings = Settings(data_dir=workspace / "data", agent_workspace_dir=workspace / "workspace")
    ollama = OllamaClient(settings)
    models = await ollama.list_models()
    if "qwen3:8b" not in models:
        raise SystemExit("qwen3:8b is not installed")
    cases = [
        ("cross_language", "호박색 카트리지가 용해된 염료를 제거하는 원리를 설명해줘.", PASSAGES, True),
        ("english", "Explain how the amber cartridge removes dissolved dye.", PASSAGES, True),
        ("multi_claim", MULTI, PASSAGES, True),
        ("partial", MULTI, PASSAGES[:2], False),
        ("false_premise", "호박색 카트리지는 염료를 첨가하므로 그 과정을 설명해줘.", PASSAGES, False),
        ("numeric_prose", "초기 측정값은 62 mm, 최종 측정값은 28 mm. 초기 측정값/최종 측정값 비율을 계산해줘.", [], True),
        ("compound_units", "c=3 Pa/(m/s)^2; v=4 m/s. Use P = c*v**2 to calculate P.", [], True),
        ("kb_calculation", "p=17 Pa, q=8 Pa. 내부 교재의 R 보정량 정의를 적용하여 R을 계산해줘.",
         ["Correction R is the combined offset. R = p + q. p (Pa) and q (Pa) are supplied offsets; R is in Pa."], True),
        ("underdetermined", "이 정보만으로 잔여 수명을 정확한 값으로 알려줘.",
         ["Remaining lifetime requires the measured wear depth and a calibrated wear rate."], True),
    ]
    rows = []
    for name, question, evidence, achieved in cases:
        agent = GoalExecutionAgent(Sources(evidence), ollama, evaluator=Evaluator(False), synthesizer=refusal)
        started = time.perf_counter()
        with patch("app.services.goal_execution_agent.get_settings", return_value=settings):
            result = await agent.run("GR-V17-DEV-" + name, req(question))
        passed = ((result.status.value == "achieved") == achieved and bool(result.final_answer)
                  and not result.telemetry.get("refusal_generated"))
        if name in {"multi_claim", "partial"}:
            passed = passed and result.telemetry.get("claim_count") == 3
            passed = passed and result.telemetry.get("supported_claim_count") == (3 if achieved else 2)
        if name == "false_premise":
            passed = passed and result.telemetry.get("contradicted_claim_count") == 1 and "반대" in result.final_answer
        if name == "underdetermined":
            passed = passed and "wear depth" in result.final_answer and "wear rate" in result.final_answer
        if name in {"numeric_prose", "compound_units", "kb_calculation"}:
            expected = {"numeric_prose": 62/28, "compound_units": 48, "kb_calculation": 25}[name]
            passed = passed and any(c.validation_passed and any(
                isinstance(o.get("value"), (float, int)) and abs(o["value"]-expected) < 1e-8
                for o in c.output_manifest.values()) for c in result.computations)
        rows.append({"case": name, "passed": passed, "seconds": time.perf_counter()-started,
                     "question": question, "sources": evidence, "result": result.model_dump(mode="json")})
        print(json.dumps({"case": name, "passed": passed, "status": result.status.value,
                          "support": result.telemetry.get("answerability_status")}), flush=True)
    payload = {"kind": "development_smoke_not_benchmark", "model": "qwen3:8b",
        "retrieval": "synthetic_in_memory_fixtures", "evaluator": "intentionally_rejecting",
        "semantic_judge": "real_local_qwen3:8b", "python": "real_bounded_sandbox",
        "frozen_evaluations_read": False, "chroma_opened": False,
        "code_hashes": {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                        for path in (Path(__file__).resolve().parents[1] / "app" / "services").glob("*.py")},
        "passed": sum(r["passed"] for r in rows), "total": len(rows), "rows": rows}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if not all(row["passed"] for row in rows):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
