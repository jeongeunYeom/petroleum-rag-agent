from __future__ import annotations

import json
import sys
import urllib.error
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import run_external_baseline as runner  # noqa: E402


def test_frozen_question_counts() -> None:
    assert len(runner.select_questions("closed_book")) == 50
    assert len(runner.select_questions("same_evidence")) == 50
    assert len(runner.select_questions("figure")) == 10


@pytest.mark.parametrize("provider", ["qwen", "openai", "gemini"])
@pytest.mark.parametrize("condition", ["closed_book", "same_evidence"])
def test_provider_prompt_equivalence_and_no_ground_truth_leakage(provider: str, condition: str) -> None:
    selected = runner.select_questions(condition)[:3]
    metadata = runner.build_dry_run(provider, condition, selected)
    assert metadata["question_count"] == 3
    assert metadata["web_used"] is False
    assert metadata["tools_used"] is False


def test_provider_syntax_does_not_change_prompt_content() -> None:
    question = runner.select_questions("closed_book")[0]
    prompts = [runner.build_prompt(question, "closed_book") for _provider in runner.MODEL_CONFIG]
    assert len({(prompt.system, prompt.user) for prompt in prompts}) == 1


def test_closed_book_has_no_evidence() -> None:
    prompt = runner.build_prompt(runner.select_questions("closed_book")[0], "closed_book")
    assert "Evidence:" not in prompt.user
    assert "[KB1]" not in prompt.user
    runner.validate_no_leakage(prompt, "closed_book")


def test_same_evidence_contains_only_sanitized_export() -> None:
    question = runner.select_questions("same_evidence")[0]
    evidence = runner.evidence_by_id()[question["id"]]
    prompt = runner.build_prompt(question, "same_evidence", evidence)
    assert "[KB1]" in prompt.user
    lowered = prompt.user.lower()
    for forbidden in ("required_claims", "expected_answer", "ground_truth", "semantic_rubric"):
        assert forbidden not in lowered
    runner.validate_no_leakage(prompt, "same_evidence")


def test_api_key_redaction() -> None:
    key = "secret-key-should-never-appear"
    rendered = runner.redact_secrets(f"Bearer {key}; api_key={key}", [key])
    assert key not in rendered
    assert "[REDACTED]" in rendered


def test_cost_guard_budget_and_safety_stop() -> None:
    guard = runner.OpenAIBudgetGuard(budget=3.25, safety_stop=3.50)
    guard.check_projection(3.25)
    with pytest.raises(runner.BudgetExceeded):
        guard.check_projection(3.250001)
    guard.add(3.40)
    with pytest.raises(runner.BudgetExceeded):
        guard.check_next(0.10)


def test_retry_bound(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    def always_fail(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise urllib.error.URLError("temporary")

    monkeypatch.setattr(runner.urllib.request, "urlopen", always_fail)
    request = runner.urllib.request.Request("http://example.invalid")
    with pytest.raises(urllib.error.URLError):
        runner._request_json(request, timeout=0.01, max_retries=2, sleep=lambda _: None)
    assert calls == 3


def test_result_schema_in_dry_run() -> None:
    args = runner.parse_args(["--provider", "qwen", "--condition", "closed_book", "--dry-run", "--limit", "2"])
    payload = runner.run(args)
    assert payload["dry_run"] is True
    assert payload["metadata"]["question_count"] == 2
    assert payload["results"] == []


def test_anonymous_review_mapping_hides_model() -> None:
    rubric = runner.load_json(runner.RUBRIC_PATH)
    run = {
        "results": [
            {
                "question_id": "PH-WT-001",
                "provider": "qwen",
                "model": "qwen3:8b",
                "condition": "qwen_direct_closed_book",
                "answer": "A model-neutral answer.",
                "error": None,
            }
        ]
    }
    packet, key = runner.build_anonymous_review([run], rubric)
    serialized_packet = json.dumps(packet)
    assert "qwen" not in serialized_packet.lower()
    assert "qwen3:8b" not in serialized_packet
    anonymous_id = packet["items"][0]["anonymous_answer_id"]
    assert key["answers"][anonymous_id]["model"] == "qwen3:8b"
    assert packet["items"][0]["condition"] == "closed_book"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("qwen_direct_closed_book", "closed_book"),
        ("gpt6_sol_same_evidence", "same_evidence"),
        ("gemini38_flash_figure", "figure"),
    ],
)
def test_base_condition(value: str, expected: str) -> None:
    assert runner.base_condition(value) == expected


def test_model_neutral_scorer_accepts_expected_condition_names() -> None:
    from score_semantic_review import VALID_CONDITIONS

    assert {"closed_book", "same_evidence", "petroleum_agent"} <= VALID_CONDITIONS
