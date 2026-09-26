from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


RetrievalMode = Literal["legacy", "hybrid", "hybrid_rerank"]


class ResearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    internal_top_k: int = Field(default=5, ge=1, le=20)
    external_top_k: int = Field(default=5, ge=1, le=20)
    use_internal: bool = True
    use_external: bool = True
    model: str = Field(default="qwen3:8b", min_length=1, max_length=100)

    @field_validator("query", "model")
    @classmethod
    def reject_blank_strings(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value

    @model_validator(mode="after")
    def require_evidence_source(self) -> "ResearchRequest":
        if not self.use_internal and not self.use_external:
            raise ValueError("at least one evidence source must be enabled")
        return self


class InternalEvidence(BaseModel):
    evidence_id: str
    document: str
    page: int | None = None
    chunk_id: str
    score: float
    excerpt: str


class WebEvidence(BaseModel):
    evidence_id: str
    title: str
    url: str
    domain: str
    snippet: str
    rank: int


class FigureEvidence(BaseModel):
    evidence_id: str
    document: str
    page: int | None = None
    figure_number: str | None = None
    title: str | None = None
    image_index: int | None = None
    filename: str | None = None
    image_path: str | None = None
    url: str | None = None
    excerpt: str
    source_note: str = ""
    related_page_text: str = ""
    x_axis: str | None = None
    x_axis_unit: str | None = None
    y_axis: str | None = None
    y_axis_unit: str | None = None
    series_count: int | None = None
    series_descriptions: list[str] = Field(default_factory=list)
    legend: list[str] = Field(default_factory=list)
    quantities: list[dict[str, str]] = Field(default_factory=list)


class ProvenanceRecord(BaseModel):
    evidence_id: str
    source_type: Literal["knowledge_base", "web", "figure"]
    locator: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvidenceCounts(BaseModel):
    internal: int
    external: int


class ResearchTiming(BaseModel):
    retrieval_seconds: float
    reasoning_seconds: float
    elapsed_seconds: float


class ResearchResponse(BaseModel):
    query: str
    answer: str
    internal_sources: list[InternalEvidence]
    web_sources: list[WebEvidence]
    figures: list[FigureEvidence]
    provenance: list[ProvenanceRecord]
    model: str
    inference_used: bool
    evidence_counts: EvidenceCounts
    routing_mode: Literal["internal_only", "external_only", "hybrid_research"]
    retrieval_mode: RetrievalMode
    timing: ResearchTiming
    conflicts: list[dict[str, str]] = Field(default_factory=list)
    validation: dict[str, Any] = Field(default_factory=dict)
