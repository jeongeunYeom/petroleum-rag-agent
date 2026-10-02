from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import random
import re
import statistics
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


PROJECT_ROOT = Path(__file__).resolve().parents[2]
QUESTIONS_PATH = PROJECT_ROOT / "evaluation" / "petroleum_agent_heldout_v1_questions.json"
EVIDENCE_PATH = PROJECT_ROOT / "evaluation" / "petroleum_agent_heldout_v1_retrieved_evidence.json"
RUBRIC_PATH = PROJECT_ROOT / "evaluation" / "petroleum_agent_heldout_v1_semantic_rubric.json"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "evaluation" / "external"
DEFAULT_FIGURE_ROOTS = (
    PROJECT_ROOT / "data" / "figures",
    Path(r"D:\petroleum-rag-agent\data\figures"),
)

TEXT_SYSTEM_PROMPT = """You are answering petroleum engineering benchmark questions.

Answer the user's question directly and concisely, while including all necessary engineering content.
If the premise of the question is technically incorrect, explicitly correct it.
Do not use web search or external tools.
Do not invent document citations or page numbers.
If you do not know something reliably, say so rather than fabricate it."""

EVIDENCE_SYSTEM_PROMPT = """You are answering petroleum engineering benchmark questions.

Answer the user's question directly and concisely, while including all necessary engineering content.
Use only the supplied evidence. If the evidence is insufficient, explicitly say so.
Do not use external knowledge to fill unsupported gaps.
Cite supporting evidence with its bracketed evidence ID, for example [KB1].
Do not use web search or external tools."""

FIGURE_SYSTEM_PROMPT = """You are answering petroleum engineering benchmark questions.

Answer the user's question directly and concisely using only the supplied scientific figure image.
Describe only elements that are visible in the image. If the image is insufficient, say so.
Do not use web search or external tools."""

MODEL_CONFIG = {
    "qwen": {"text_model": "qwen3:8b", "figure_model": "qwen2.5vl:7b"},
    "openai": {"text_model": "gpt-6.1-sol", "figure_model": "gpt-6.1-sol"},
    "gemini": {"text_model": "gemini-3.8-flash", "figure_model": "gemini-3.8-flash"},
}

PRICING = {
    "pricing_date": "2026-10-02",
    "service_tier": "standard",
    "openai": {"input_per_million": 2.00, "output_per_million": 10.00},
    "gemini": {"input_per_million": 0.75, "output_per_million": 3.75},
    "qwen": {"input_per_million": 0.0, "output_per_million": 0.0},
}

PILOT_IDS = ("PH-WT-001", "PH-WT-002", "PH-RE-005", "PH-RE-011", "PH-XD-001")
RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}
MAX_RETRIES = 2


class BudgetExceeded(RuntimeError):
    pass


class AuthenticationError(RuntimeError):
    pass


@dataclass(frozen=True)
class Prompt:
    system: str
    user: str
    image_paths: tuple[str, ...] = ()


@dataclass
class ProviderResponse:
    answer: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    reasoning_tokens: int | None = None


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def items(payload: Any) -> list[dict[str, Any]]:
    return payload["items"] if isinstance(payload, dict) else payload


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def redact_secrets(value: str, secrets: list[str] | tuple[str, ...]) -> str:
    cleaned = value
    for secret in secrets:
        if secret:
            cleaned = cleaned.replace(secret, "[REDACTED]")
    cleaned = re.sub(r"(?i)(api[_ -]?key[=:\s]+)[^\s,;]+", r"\1[REDACTED]", cleaned)
    cleaned = re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._~-]+", r"\1[REDACTED]", cleaned)
    return cleaned


def estimate_cost(provider: str, input_tokens: int | None, output_tokens: int | None) -> float | None:
    if input_tokens is None or output_tokens is None:
        return None
    prices = PRICING[provider]
    return round(
        input_tokens * prices["input_per_million"] / 1_000_000
        + output_tokens * prices["output_per_million"] / 1_000_000,
        8,
    )


class OpenAIBudgetGuard:
    def __init__(self, budget: float = 3.25, safety_stop: float = 3.50) -> None:
        self.budget = budget
        self.safety_stop = safety_stop
        self.spent = 0.0

    def check_next(self, estimated_next: float) -> None:
        if self.spent + estimated_next >= self.safety_stop:
            raise BudgetExceeded(
                f"OpenAI safety stop: projected cumulative ${self.spent + estimated_next:.4f} "
                f">= ${self.safety_stop:.2f}"
            )

    def check_projection(self, projected_total: float) -> None:
        if projected_total > self.budget:
            raise BudgetExceeded(
                f"OpenAI projected total ${projected_total:.4f} exceeds ${self.budget:.2f} budget"
            )

    def add(self, cost: float | None) -> None:
        self.spent += cost or 0.0


def select_questions(condition: str) -> list[dict[str, Any]]:
    selected = items(load_json(QUESTIONS_PATH))
    wants_figure = condition == "figure"
    return [row for row in selected if (row["task_type"] == "figure") == wants_figure]


def evidence_by_id() -> dict[str, dict[str, Any]]:
    return {row["id"]: row for row in items(load_json(EVIDENCE_PATH))}


def render_text_evidence(row: dict[str, Any]) -> str:
    blocks = []
    for evidence in row.get("text_evidence", []):
        blocks.append(
            f"[{evidence['evidence_id']}]\n"
            f"Document: {evidence.get('document') or 'Unknown'}\n"
            f"Page: {evidence.get('page') or 'Unknown'}\n"
            f"Excerpt:\n{evidence.get('excerpt') or ''}"
        )
    return "\n\n".join(blocks)


def find_figure_path(filename: str | None, roots: tuple[Path, ...] = DEFAULT_FIGURE_ROOTS) -> Path | None:
    if not filename:
        return None
    for root in roots:
        direct = root / filename
        if direct.is_file():
            return direct
        if root.is_dir():
            match = next(root.rglob(filename), None)
            if match:
                return match
    return None


def figure_paths_for_question(question: dict[str, Any], evidence: dict[str, Any]) -> tuple[str, ...]:
    page_match = re.search(r"page\s+(\d+)", question["question"], re.IGNORECASE)
    target_page = int(page_match.group(1)) if page_match else None
    candidates = evidence.get("figure_evidence", [])
    if target_page is not None:
        exact = [row for row in candidates if row.get("page") == target_page]
        candidates = exact or candidates
    found: list[str] = []
    for row in candidates:
        path = find_figure_path(row.get("relative_filename"))
        if path and str(path) not in found:
            found.append(str(path))
    return tuple(found[:1])


def build_prompt(question: dict[str, Any], condition: str, evidence: dict[str, Any] | None = None) -> Prompt:
    if condition == "closed_book":
        return Prompt(TEXT_SYSTEM_PROMPT, question["question"])
    if condition == "same_evidence":
        if evidence is None:
            raise ValueError("same_evidence requires evidence")
        return Prompt(
            EVIDENCE_SYSTEM_PROMPT,
            f"Question:\n{question['question']}\n\nEvidence:\n{render_text_evidence(evidence)}",
        )
    if condition == "figure":
        if evidence is None:
            raise ValueError("figure requires evidence")
        return Prompt(
            FIGURE_SYSTEM_PROMPT,
            f"Question:\n{question['question']}",
            figure_paths_for_question(question, evidence),
        )
    raise ValueError(f"Unknown condition: {condition}")


def _request_json(
    request: urllib.request.Request,
    *,
    timeout: float,
    max_retries: int = MAX_RETRIES,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code in {401, 403}:
                raise AuthenticationError(f"provider authentication failed (HTTP {exc.code})") from exc
            last_error = exc
            if exc.code not in RETRYABLE_STATUS or attempt == max_retries:
                raise
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
            if attempt == max_retries:
                raise
        sleep(0.5 * 2**attempt)
    raise RuntimeError("request failed") from last_error


def _data_url(path: str) -> str:
    suffix = Path(path).suffix.lower()
    mime = "image/png" if suffix == ".png" else "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(Path(path).read_bytes()).decode('ascii')}"


def call_qwen(prompt: Prompt, model: str, max_output_tokens: int, timeout: float) -> ProviderResponse:
    message: dict[str, Any] = {"role": "user", "content": prompt.user}
    if prompt.image_paths:
        message["images"] = [base64.b64encode(Path(path).read_bytes()).decode("ascii") for path in prompt.image_paths]
    body = {
        "model": model,
        "messages": [{"role": "system", "content": prompt.system}, message],
        "stream": False,
        "think": False,
        "options": {"temperature": 0, "seed": 42, "num_predict": max_output_tokens},
    }
    request = urllib.request.Request(
        "http://127.0.0.1:11434/api/chat",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    payload = _request_json(request, timeout=timeout)
    return ProviderResponse(
        answer=payload["message"]["content"].strip(),
        input_tokens=payload.get("prompt_eval_count"),
        output_tokens=payload.get("eval_count"),
    )


def call_openai(prompt: Prompt, model: str, max_output_tokens: int, timeout: float) -> ProviderResponse:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise AuthenticationError("OPENAI_API_KEY is not set")
    content: list[dict[str, Any]] = [{"type": "input_text", "text": prompt.user}]
    content.extend({"type": "input_image", "image_url": _data_url(path)} for path in prompt.image_paths)
    body = {
        "model": model,
        "instructions": prompt.system,
        "input": [{"role": "user", "content": content}],
        "reasoning": {"effort": "low"},
        "max_output_tokens": max_output_tokens,
        "tools": [],
        "store": False,
    }
    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        method="POST",
    )
    payload = _request_json(request, timeout=timeout)
    answer = payload.get("output_text")
    if not answer:
        answer = "".join(
            part.get("text", "")
            for output in payload.get("output", [])
            for part in output.get("content", [])
            if part.get("type") in {"output_text", "text"}
        )
    usage = payload.get("usage", {})
    reasoning = usage.get("output_tokens_details", {}).get("reasoning_tokens")
    return ProviderResponse(answer.strip(), usage.get("input_tokens"), usage.get("output_tokens"), reasoning)


def call_gemini(prompt: Prompt, model: str, max_output_tokens: int, timeout: float) -> ProviderResponse:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise AuthenticationError("GEMINI_API_KEY is not set")
    parts: list[dict[str, Any]] = [{"text": prompt.user}]
    for path in prompt.image_paths:
        suffix = Path(path).suffix.lower()
        parts.append(
            {
                "inlineData": {
                    "mimeType": "image/png" if suffix == ".png" else "image/jpeg",
                    "data": base64.b64encode(Path(path).read_bytes()).decode("ascii"),
                }
            }
        )
    body = {
        "systemInstruction": {"parts": [{"text": prompt.system}]},
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "maxOutputTokens": max_output_tokens,
            "temperature": 0,
            "thinkingConfig": {"thinkingLevel": "LOW"},
        },
    }
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    payload = _request_json(request, timeout=timeout)
    answer = "".join(
        part.get("text", "")
        for candidate in payload.get("candidates", [])[:1]
        for part in candidate.get("content", {}).get("parts", [])
        if not part.get("thought")
    )
    usage = payload.get("usageMetadata", {})
    return ProviderResponse(
        answer.strip(),
        usage.get("promptTokenCount"),
        usage.get("candidatesTokenCount"),
        usage.get("thoughtsTokenCount"),
    )


CALLERS = {"qwen": call_qwen, "openai": call_openai, "gemini": call_gemini}


def percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int((len(ordered) - 1) * quantile + 0.999999)))
    return ordered[index]


def latency_summary(results: list[dict[str, Any]]) -> dict[str, float | None]:
    values = [row["latency_seconds"] for row in results if row.get("error") is None]
    return {
        "mean": statistics.fmean(values) if values else None,
        "median": statistics.median(values) if values else None,
        "p95": percentile(values, 0.95),
        "min": min(values) if values else None,
        "max": max(values) if values else None,
    }


def condition_name(provider: str, condition: str) -> str:
    prefix = {"qwen": "qwen_direct", "openai": "gpt61_sol", "gemini": "gemini38_flash"}[provider]
    return f"{prefix}_{condition}"


def base_condition(value: str) -> str:
    for condition in ("same_evidence", "closed_book", "figure"):
        if value.endswith(condition):
            return condition
    raise ValueError(f"Unknown result condition: {value}")


def default_output(provider: str, condition: str) -> Path:
    names = {
        ("qwen", "closed_book"): "qwen_closed_book.json",
        ("qwen", "same_evidence"): "qwen_same_evidence.json",
        ("qwen", "figure"): "figure_qwen25vl.json",
        ("openai", "closed_book"): "openai_gpt61_sol_closed_book.json",
        ("openai", "same_evidence"): "openai_gpt61_sol_same_evidence.json",
        ("openai", "figure"): "openai_gpt61_sol_figure.json",
        ("gemini", "closed_book"): "gemini38_flash_closed_book.json",
        ("gemini", "same_evidence"): "gemini38_flash_same_evidence.json",
        ("gemini", "figure"): "gemini38_flash_figure.json",
    }
    return DEFAULT_OUTPUT_DIR / names[(provider, condition)]


def validate_no_leakage(prompt: Prompt, condition: str) -> None:
    forbidden = ("required_claims", "forbidden_claims", "expected_answer", "ground_truth", "semantic_rubric")
    rendered = f"{prompt.system}\n{prompt.user}".lower()
    hit = next((token for token in forbidden if token in rendered), None)
    if hit:
        raise ValueError(f"ground-truth leakage detected: {hit}")
    if condition == "closed_book" and ("evidence:" in rendered or "[kb1]" in rendered):
        raise ValueError("closed-book evidence leakage detected")


def build_dry_run(provider: str, condition: str, selected: list[dict[str, Any]]) -> dict[str, Any]:
    evidences = evidence_by_id()
    prompts = [build_prompt(row, condition, evidences.get(row["id"])) for row in selected]
    for prompt in prompts:
        validate_no_leakage(prompt, condition)
    return {
        "provider": provider,
        "model": MODEL_CONFIG[provider]["figure_model" if condition == "figure" else "text_model"],
        "condition": condition_name(provider, condition),
        "question_count": len(selected),
        "web_used": False,
        "tools_used": False,
        "prompts_sha256": hashlib.sha256(
            json.dumps([asdict(prompt) for prompt in prompts], ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest(),
        "image_available_count": sum(bool(prompt.image_paths) for prompt in prompts),
        "question_sha256": sha256(QUESTIONS_PATH),
        "evidence_sha256": sha256(EVIDENCE_PATH) if condition == "same_evidence" else None,
        "image_sha256_by_question": {
            question["id"]: [hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in prompt.image_paths]
            for question, prompt in zip(selected, prompts)
            if prompt.image_paths
        },
    }


def build_anonymous_review(
    runs: list[dict[str, Any]], rubric: dict[str, Any], *, seed: int = 20261002,
    answer_id_prefix: str = "EXT",
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build a blind packet and a separate answer-to-model key."""
    rubric_by_id = {row["id"]: row for row in rubric["items"]}
    candidates: list[dict[str, Any]] = []
    for run in runs:
        for result in run.get("results", []):
            if result.get("error") is None and result.get("answer") and result["question_id"] in rubric_by_id:
                candidates.append({"run": run, "result": result})
    random.Random(seed).shuffle(candidates)
    packet_items: list[dict[str, Any]] = []
    answer_key: dict[str, Any] = {}
    for index, candidate in enumerate(candidates, start=1):
        result = candidate["result"]
        rubric_item = rubric_by_id[result["question_id"]]
        anonymous_id = f"{answer_id_prefix}-{index:04d}"
        packet_items.append(
            {
                "anonymous_answer_id": anonymous_id,
                "question_id": result["question_id"],
                "question": rubric_item["question"],
                "answer": result["answer"],
                "condition": base_condition(result["condition"]),
                "atomic_rubric": {
                    "required_claims": rubric_item["required_claims"],
                    "false_premise_required": rubric_item["false_premise_required"],
                    "contradictions": rubric_item["contradictions"],
                    "numeric_criterion": rubric_item["numeric_criterion"],
                    "citation_criterion": rubric_item["citation_criterion"],
                    "figure_criterion": rubric_item["figure_criterion"],
                },
            }
        )
        answer_key[anonymous_id] = {
            "question_id": result["question_id"],
            "provider": result["provider"],
            "model": result["model"],
            "condition": result["condition"],
        }
    return (
        {"schema_version": "1.0", "reviewer": "single AI-assisted semantic reviewer", "items": packet_items},
        {"schema_version": "1.0", "answers": answer_key},
    )


def run(args: argparse.Namespace) -> dict[str, Any]:
    selected = select_questions(args.condition)
    if args.pilot:
        selected = [row for row in selected if row["id"] in PILOT_IDS]
    if args.question_ids:
        requested = set(args.question_ids.split(","))
        selected = [row for row in selected if row["id"] in requested]
    if args.limit:
        selected = selected[: args.limit]
    if args.dry_run:
        return {"schema_version": "1.0", "dry_run": True, "metadata": build_dry_run(args.provider, args.condition, selected), "results": []}

    evidences = evidence_by_id()
    model = MODEL_CONFIG[args.provider]["figure_model" if args.condition == "figure" else "text_model"]
    guard = OpenAIBudgetGuard(args.openai_budget_usd, args.openai_safety_stop_usd)
    caller = CALLERS[args.provider]
    results: list[dict[str, Any]] = []
    budget_stop_reason: str | None = None
    secrets = [os.environ.get("OPENAI_API_KEY", ""), os.environ.get("GEMINI_API_KEY", "")]
    for question in selected:
        prompt = build_prompt(question, args.condition, evidences.get(question["id"]))
        validate_no_leakage(prompt, args.condition)
        if args.condition == "figure" and not prompt.image_paths:
            results.append(
                {
                    "question_id": question["id"], "provider": args.provider, "model": model,
                    "condition": condition_name(args.provider, args.condition), "answer": "", "latency_seconds": 0.0,
                    "input_tokens": None, "output_tokens": None, "reasoning_tokens": None, "estimated_cost_usd": None,
                    "web_used": False, "tools_used": False, "figure_image_available": False,
                    "error": "figure image unavailable",
                }
            )
            continue
        if args.provider == "openai":
            observed = [row["estimated_cost_usd"] for row in results if row.get("estimated_cost_usd") is not None]
            try:
                guard.check_next(statistics.fmean(observed) if observed else 0.05)
            except BudgetExceeded as exc:
                budget_stop_reason = str(exc)
                break
        started = time.perf_counter()
        error = None
        response = ProviderResponse("")
        try:
            response = caller(prompt, model, args.max_output_tokens, args.timeout)
            if not response.answer:
                raise ValueError("provider returned an empty answer")
        except AuthenticationError:
            raise
        except Exception as exc:  # Preserve per-question provider failures.
            error = redact_secrets(f"{type(exc).__name__}: {exc}", secrets)
        latency = time.perf_counter() - started
        cost = estimate_cost(args.provider, response.input_tokens, response.output_tokens)
        if args.provider == "openai":
            guard.add(cost)
        results.append(
            {
                "question_id": question["id"], "provider": args.provider, "model": model,
                "condition": condition_name(args.provider, args.condition), "answer": response.answer,
                "latency_seconds": round(latency, 6), "input_tokens": response.input_tokens,
                "output_tokens": response.output_tokens, "reasoning_tokens": response.reasoning_tokens,
                "estimated_cost_usd": cost, "web_used": False, "tools_used": False,
                "figure_image_available": bool(prompt.image_paths) if args.condition == "figure" else None,
                "error": error,
            }
        )
    total_cost = sum(row["estimated_cost_usd"] or 0.0 for row in results)
    successful = [row for row in results if row["error"] is None]
    average_cost = total_cost / len(successful) if successful else None
    planned_requests = sum(len(select_questions(condition)) for condition in ("closed_book", "same_evidence"))
    planned_requests += sum(
        bool(build_prompt(row, "figure", evidences.get(row["id"])).image_paths)
        for row in select_questions("figure")
    )
    projected_cost = average_cost * planned_requests if average_cost is not None else None
    if args.provider == "openai" and args.pilot and projected_cost is not None:
        try:
            guard.check_projection(projected_cost)
        except BudgetExceeded as exc:
            budget_stop_reason = str(exc)
    return {
        "schema_version": "1.0",
        "dry_run": False,
        "metadata": {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "provider": args.provider,
            "model": model,
            "condition": condition_name(args.provider, args.condition),
            "question_count": len(selected),
            "web_used": False,
            "tools_used": False,
            "parameters": {
                "max_output_tokens": args.max_output_tokens,
                "temperature": 0 if args.provider in {"qwen", "gemini"} else None,
                "reasoning_effort": "low" if args.provider == "openai" else None,
                "thinking_level": "low" if args.provider == "gemini" else None,
                "qwen_think": False if args.provider == "qwen" else None,
                "max_retries": MAX_RETRIES,
            },
            "pricing": PRICING,
            "estimated_cost_usd": round(total_cost, 8),
            "projected_full_cost_usd": round(projected_cost, 8) if projected_cost is not None else None,
            "planned_request_count": planned_requests,
            "budget_approved_for_full_run": budget_stop_reason is None if args.provider == "openai" and args.pilot else None,
            "budget_stop_reason": budget_stop_reason,
            "latency_seconds": latency_summary(results),
            "question_sha256": sha256(QUESTIONS_PATH),
            "evidence_sha256": sha256(EVIDENCE_PATH),
        },
        "results": results,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run model-only petroleum benchmark baselines.")
    parser.add_argument("--provider", required=True, choices=sorted(MODEL_CONFIG))
    parser.add_argument("--condition", required=True, choices=("closed_book", "same_evidence", "figure"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--pilot", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--question-ids", help="Comma-separated benchmark IDs")
    parser.add_argument("--output")
    parser.add_argument("--max-output-tokens", type=int, default=1200)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--openai-budget-usd", type=float, default=3.25)
    parser.add_argument("--openai-safety-stop-usd", type=float, default=3.50)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        payload = run(args)
    except (AuthenticationError, BudgetExceeded, ValueError) as exc:
        print(f"STOP: {redact_secrets(str(exc), [os.environ.get('OPENAI_API_KEY', ''), os.environ.get('GEMINI_API_KEY', '')])}")
        return 2
    output = Path(args.output) if args.output else default_output(args.provider, args.condition)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"output={output.resolve()}")
    print(f"questions={payload['metadata']['question_count']}")
    if not args.dry_run:
        print(f"estimated_cost_usd={payload['metadata']['estimated_cost_usd']:.8f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
