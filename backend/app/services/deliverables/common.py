from __future__ import annotations

import re
from datetime import datetime, timezone

from app.models.goal_research_schemas import GoalResearchResponse


def safe_text(value: object) -> str:
    text = str(value or "")
    text = re.sub(r"[A-Za-z]:[\\/][^\s\]\[()]+", "[local path omitted]", text)
    text = re.sub(r"/(?:home|Users|etc)/[^\s\]\[()]+", "[local path omitted]", text)
    text = re.sub(r"(?i)(?:sk-[A-Za-z0-9_-]{16,}|AIza[A-Za-z0-9_-]{20,})", "[credential omitted]", text)
    return text[:10000]


def provenance(result: GoalResearchResponse) -> str:
    source_ids = [item.evidence_id for item in result.internal_sources]
    source_ids += [item.evidence_id for item in result.web_sources]
    source_ids += [item.evidence_id for item in result.figures]
    calc_ids = [item.computation_id for item in result.computations if item.validation_passed]
    return f"Source: {', '.join(source_ids) or 'none'} | Derived: {', '.join(calc_ids) or 'none'}"


def metadata_lines(result: GoalResearchResponse) -> list[str]:
    return [
        f"Run ID: {result.run_id}",
        f"Generated UTC: {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        f"Goal status: {result.status.value}",
        f"Coverage: {result.goal_coverage_percent:.0f}%",
        f"Hypothesis status: {result.expected_result_status.value}",
        f"Iterations: {result.iterations_completed}",
        provenance(result),
    ]
