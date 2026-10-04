from __future__ import annotations

from pathlib import Path

from app.core.config import Settings
from app.models.goal_research_schemas import GeneratedArtifact, GoalResearchResponse
from app.services.deliverables.artifact_validator import validate_artifact
from app.services.deliverables.docx_generator import generate_docx
from app.services.deliverables.pptx_generator import generate_pptx


class DeliverableService:
    def __init__(self, settings: Settings):
        self.settings = settings

    def create(self, frozen: GoalResearchResponse, kind: str, include_charts: bool = True) -> GeneratedArtifact:
        if kind not in {"docx", "pptx"}:
            raise ValueError("Unsupported deliverable type")
        workspace = self.settings.agent_workspace_dir.resolve()
        run_dir = (workspace / "results" / "goal-research" / frozen.run_id).resolve()
        run_dir.relative_to(workspace)
        output_dir = run_dir / "deliverables"
        output_dir.mkdir(parents=True, exist_ok=True)
        stem = "research_report" if kind == "docx" else "research_presentation"
        path = output_dir / f"{stem}.{kind}"
        number = 2
        while path.exists():
            path = output_dir / f"{stem}_{number}.{kind}"
            number += 1
        chart_paths: list[Path] = []
        if include_charts:
            for item in frozen.computations:
                if not item.validation_passed:
                    continue
                for relative in item.output_files:
                    candidate = (workspace / relative).resolve()
                    try:
                        candidate.relative_to(run_dir / "analysis")
                    except ValueError:
                        continue
                    if candidate.suffix.lower() == ".png" and candidate.is_file():
                        chart_paths.append(candidate)
        generator = generate_docx if kind == "docx" else generate_pptx
        for attempt in range(2):
            try:
                generator(frozen, path, chart_paths)
                validate_artifact(path, kind)
                break
            except Exception:
                if attempt:
                    raise
                path = output_dir / f"{stem}_{number}.{kind}"
                number += 1
        return GeneratedArtifact(
            artifact_id=f"ART-{kind.upper()}",
            artifact_type=kind,
            path=path.relative_to(workspace).as_posix(),
            size_bytes=path.stat().st_size,
            validation_passed=True,
            source_computations=[item.computation_id for item in frozen.computations if item.validation_passed],
        )
