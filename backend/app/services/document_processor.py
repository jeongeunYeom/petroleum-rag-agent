from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from PIL import Image, ImageStat, UnidentifiedImageError

from app.core.config import Settings
from app.models.schemas import DocumentRecord
from app.services.chunking import chunk_pages
from app.services.ontology import write_relation_graph
from app.services.figure_analysis import FigureAnalysisResult, FigureAnalysisService

if TYPE_CHECKING:
    from fastapi import UploadFile

    from app.services.ollama import OllamaClient


SUPPORTED_EXTENSIONS = {".pdf", ".txt", ".png", ".jpg", ".jpeg", ".ppt", ".pptx"}
DOCUMENT_ID_PATTERN = re.compile(r"^[0-9a-f]{64}$")
INGESTION_VERSION = "kb-ingestion-v6"


def delete_document_files(settings: Settings, document_id: str) -> int:
    """Delete files produced for one indexed document."""
    if not DOCUMENT_ID_PATTERN.fullmatch(document_id):
        raise ValueError("Invalid document ID.")

    deleted_files = 0
    prefixed_directories = [
        settings.raw_dir,
        settings.figures_dir,
        settings.figure_notes_dir,
        settings.figure_analysis_inputs_dir,
        settings.data_dir / "figure_display_previews",
    ]
    exact_files = [
        settings.extracted_dir / f"{document_id}.json",
        settings.ontology_dir / f"{document_id}.jsonl",
    ]

    for directory in prefixed_directories:
        root = directory.resolve()
        if not root.is_dir():
            continue
        for path in root.glob(f"{document_id}_*"):
            resolved = path.resolve()
            if resolved.parent != root or not resolved.is_file():
                continue
            resolved.unlink()
            deleted_files += 1

    for path in exact_files:
        if path.is_file():
            path.unlink()
            deleted_files += 1

    candidates_root = settings.figure_candidates_dir.resolve()
    candidate_directory = (candidates_root / document_id).resolve()
    if (
        candidate_directory.parent == candidates_root
        and candidate_directory.is_dir()
    ):
        deleted_files += sum(
            1 for path in candidate_directory.rglob("*") if path.is_file()
        )
        shutil.rmtree(candidate_directory)

    metadata_path = settings.metadata_dir / f"{document_id}.json"
    if metadata_path.is_file():
        metadata_path.unlink()
        deleted_files += 1

    return deleted_files


def delete_document_derived_files(settings: Settings, document_id: str) -> int:
    """Delete generated artifacts for reprocessing while preserving the raw upload."""
    if not DOCUMENT_ID_PATTERN.fullmatch(document_id):
        raise ValueError("Invalid document ID.")

    deleted_files = 0
    prefixed_directories = [
        settings.figures_dir,
        settings.figure_notes_dir,
        settings.figure_analysis_inputs_dir,
        settings.data_dir / "figure_display_previews",
    ]
    exact_files = [
        settings.extracted_dir / f"{document_id}.json",
        settings.ontology_dir / f"{document_id}.jsonl",
        settings.metadata_dir / f"{document_id}.json",
    ]

    for directory in prefixed_directories:
        root = directory.resolve()
        if not root.is_dir():
            continue
        for path in root.glob(f"{document_id}_*"):
            resolved = path.resolve()
            if resolved.parent != root or not resolved.is_file():
                continue
            resolved.unlink()
            deleted_files += 1

    for path in exact_files:
        if path.is_file():
            path.unlink()
            deleted_files += 1

    candidates_root = settings.figure_candidates_dir.resolve()
    candidate_directory = (candidates_root / document_id).resolve()
    if (
        candidate_directory.parent == candidates_root
        and candidate_directory.is_dir()
    ):
        deleted_files += sum(
            1 for path in candidate_directory.rglob("*") if path.is_file()
        )
        shutil.rmtree(candidate_directory)

    return deleted_files


class DocumentProcessor:
    def __init__(self, settings: Settings, ollama: OllamaClient):
        self.settings = settings
        self.ollama = ollama
        self.figure_analyzer = FigureAnalysisService(settings, ollama)
        self._figure_stats = self._empty_figure_stats()
        self._equation_stats = self._empty_equation_stats()

    @staticmethod
    def _empty_figure_stats() -> dict[str, int]:
        return {
            "analyzed": 0,
            "valid": 0,
            "review_required": 0,
            "failed": 0,
            "ignored": 0,
            "vision_calls": 0,
        }

    def _record_figure_result(self, result: FigureAnalysisResult) -> None:
        self._figure_stats["vision_calls"] += result.vision_calls
        if result.status in self._figure_stats:
            self._figure_stats[result.status] += 1
        if result.status != "ignored":
            self._figure_stats["analyzed"] += 1


    @staticmethod
    def _empty_equation_stats() -> dict[str, int]:
        return {
            "detected": 0,
            "analyzed": 0,
            "valid": 0,
            "review_required": 0,
            "failed": 0,
            "vision_calls": 0,
        }

    def _record_equation_result(self, result: FigureAnalysisResult) -> None:
        self._equation_stats["vision_calls"] += result.vision_calls
        if result.status in {"valid", "review_required", "failed"}:
            self._equation_stats[result.status] += 1
        if result.vision_calls > 0:
            self._equation_stats["analyzed"] += 1

    @staticmethod
    def _display_filename(file_path: Path, digest: str) -> str:
        prefix = f"{digest}_"
        return (
            file_path.name[len(prefix):]
            if file_path.name.startswith(prefix)
            else file_path.name
        )

    async def save_upload(self, upload: UploadFile) -> tuple[Path, str]:
        suffix = Path(upload.filename or "uploaded").suffix.lower()
        if suffix not in SUPPORTED_EXTENSIONS:
            raise ValueError(f"Unsupported file type: {suffix}")

        content = await upload.read()
        digest = hashlib.sha256(content).hexdigest()
        safe_name = Path(upload.filename or f"{digest}{suffix}").name
        target = self.settings.raw_dir / f"{digest}_{safe_name}"

        if not target.exists():
            target.write_bytes(content)

        return target, digest

    def metadata_path(self, digest: str) -> Path:
        return self.settings.metadata_dir / f"{digest}.json"

    def load_existing(self, digest: str) -> DocumentRecord | None:
        path = self.metadata_path(digest)
        if not path.exists():
            return None
        return DocumentRecord(**json.loads(path.read_text(encoding="utf-8")))

    @staticmethod
    def is_current_record(
        record: DocumentRecord,
        *,
        analyze_figures: bool = True,
    ) -> bool:
        if record.ingestion_version != INGESTION_VERSION:
            return False
        if analyze_figures and record.figure_analysis_enabled is not True:
            return False
        return True

    @staticmethod
    def text_extraction_quality(text: str) -> dict[str, int | float]:
        """Cheap diagnostics for deciding whether an extracted page is obviously damaged."""
        value = str(text or "")
        alnum = sum(ch.isalnum() for ch in value)
        replacements = value.count("\ufffd")
        controls = sum(
            ord(ch) < 32 and ch not in {"\n", "\r", "\t"}
            for ch in value
        )
        lines = sum(1 for line in value.splitlines() if line.strip())
        tokens = len(re.findall(r"\b\w+\b", value, flags=re.UNICODE))
        score = (
            alnum
            + min(tokens, 1000) * 2
            + min(lines, 200) * 2
            - replacements * 80
            - controls * 80
        )
        return {
            "score": float(score),
            "characters": len(value),
            "alnum": alnum,
            "tokens": tokens,
            "lines": lines,
            "replacement_chars": replacements,
            "control_chars": controls,
        }

    @classmethod
    def select_page_text(
        cls,
        pymupdf_text: str,
        pdfplumber_text: str,
    ) -> tuple[str, str, dict[str, object]]:
        """Prefer compact reading-order text unless the fallback is clearly better.

        pdfplumber layout text is useful when PyMuPDF extraction is damaged,
        but it can split subscripts such as Rwa into separate spatial tokens and
        inflate the simple quality score with extra lines. That hurts retrieval
        even when the raw score is higher.
        """
        candidates = [
            ("pymupdf_sorted", str(pymupdf_text or "")),
            ("pdfplumber_layout", str(pdfplumber_text or "")),
        ]
        diagnostics = {
            name: cls.text_extraction_quality(text)
            for name, text in candidates
        }

        pymupdf = candidates[0][1]
        plumber = candidates[1][1]
        pymupdf_quality = diagnostics["pymupdf_sorted"]
        plumber_quality = diagnostics["pdfplumber_layout"]

        if not pymupdf.strip():
            return plumber.strip(), "pdfplumber_layout", diagnostics
        if not plumber.strip():
            return pymupdf.strip(), "pymupdf_sorted", diagnostics

        pymupdf_damage = int(pymupdf_quality["replacement_chars"]) + int(
            pymupdf_quality["control_chars"]
        )
        plumber_damage = int(plumber_quality["replacement_chars"]) + int(
            plumber_quality["control_chars"]
        )
        if (
            plumber_damage < pymupdf_damage
            and float(plumber_quality["score"]) > float(pymupdf_quality["score"])
        ):
            return plumber.strip(), "pdfplumber_layout", diagnostics

        pymupdf_alnum = int(pymupdf_quality["alnum"])
        plumber_alnum = int(plumber_quality["alnum"])
        pymupdf_tokens = int(pymupdf_quality["tokens"])
        plumber_tokens = int(plumber_quality["tokens"])
        materially_more_content = (
            plumber_alnum
            >= max(pymupdf_alnum + 80, int(pymupdf_alnum * 1.08))
            and plumber_tokens
            >= max(pymupdf_tokens + 12, int(pymupdf_tokens * 1.05))
        )

        if (
            materially_more_content
            and float(plumber_quality["score"]) > float(pymupdf_quality["score"])
        ):
            return plumber.strip(), "pdfplumber_layout", diagnostics

        return pymupdf.strip(), "pymupdf_sorted", diagnostics
    def persist_record(self, record: DocumentRecord) -> None:
        self.metadata_path(record.sha256).write_text(
            record.model_dump_json(indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def classify_image_candidate(image_path: Path) -> dict[str, object]:
        """Classify obvious non-figure images before spending a vision call."""
        try:
            file_size = image_path.stat().st_size

            with Image.open(image_path) as image:
                width, height = image.size
                rgb_image = image.convert("RGB").resize((64, 64))
                stat = ImageStat.Stat(rgb_image)

            area = width * height
            aspect_ratio = width / max(height, 1)
            contrast = sum(stat.stddev) / max(len(stat.stddev), 1)

            result: dict[str, object] = {
                "image_type": "unknown",
                "confidence": 0.6,
                "should_analyze": True,
                "width": width,
                "height": height,
                "file_size": file_size,
                "contrast": round(float(contrast), 2),
                "reason": "",
            }

            if file_size < 20_000 or width < 350 or height < 250 or area < 150_000:
                result.update(
                    {
                        "image_type": "decorative",
                        "confidence": 0.1,
                        "should_analyze": False,
                        "reason": "too small or low resolution",
                    }
                )
                return result

            if contrast < 8:
                result.update(
                    {
                        "image_type": "decorative",
                        "confidence": 0.1,
                        "should_analyze": False,
                        "reason": "nearly monochrome",
                    }
                )
                return result

            if aspect_ratio > 8 or aspect_ratio < 0.125:
                result.update(
                    {
                        "image_type": "decorative",
                        "confidence": 0.2,
                        "should_analyze": False,
                        "reason": "extreme aspect ratio",
                    }
                )
                return result

            if height < 320 and width < 900:
                result.update(
                    {
                        "image_type": "logo",
                        "confidence": 0.35,
                        "should_analyze": False,
                        "reason": "small banner/logo-like image",
                    }
                )
                return result

            return result

        except (OSError, ValueError, UnidentifiedImageError):
            return {
                "image_type": "unknown",
                "confidence": 0.0,
                "should_analyze": False,
                "reason": "unreadable image",
            }

    @staticmethod
    def should_analyze_image(image_path: Path) -> bool:
        """Return True only for images large enough to contain a useful figure."""
        return bool(DocumentProcessor.classify_image_candidate(image_path).get("should_analyze"))

    def build_figure_note(
        self,
        *,
        document_name: str,
        page_number: int,
        image_index: int,
        image_path: Path,
        note: str,
        page_text: str,
        candidate: dict[str, object],
    ) -> str:
        metadata = self._classify_figure_note(note, candidate)
        related_text = re.sub(r"\s+", " ", page_text).strip()[:800]
        return "\n".join(
            [
                "[Figure Note Metadata]",
                f"Document: {document_name}",
                f"Page: {page_number}",
                f"Image Path: {image_path}",
                f"image_path: {image_path}",
                f"Image Number: {image_index}",
                f"Image Type: {metadata['image_type']}",
                f"image_type: {metadata['image_type']}",
                f"Confidence: {metadata['confidence']}",
                f"confidence: {metadata['confidence']}",
                f"X Axis Confirmed: {metadata['x_axis_confirmed']}",
                f"x_axis_verified: {metadata['x_axis_confirmed']}",
                f"Y Axis Confirmed: {metadata['y_axis_confirmed']}",
                f"y_axis_verified: {metadata['y_axis_confirmed']}",
                f"Units Confirmed: {metadata['units_confirmed']}",
                f"units_verified: {metadata['units_confirmed']}",
                f"Analysis Model: {self.settings.vision_model}",
                f"Created At: {datetime.now(timezone.utc).isoformat()}",
                f"Related Page Text: {related_text}",
                "",
                "[Analysis]",
                note,
            ]
        )

    def _classify_figure_note(self, note: str, candidate: dict[str, object]) -> dict[str, object]:
        lower = note.lower()
        image_type = str(candidate.get("image_type") or "unknown")
        if image_type in {"logo", "decorative"}:
            base_confidence = float(candidate.get("confidence") or 0.0)
        else:
            base_confidence = 0.55

        if any(term in lower for term in ["x-axis", "y-axis", "axis", "legend", "trend", "plot", "graph", "x축", "y축"]):
            image_type = "graph"
            base_confidence = 0.75
        elif any(term in lower for term in ["chart", "bar chart", "line chart"]):
            image_type = "chart"
            base_confidence = 0.7
        elif "table" in lower or "표" in note:
            image_type = "table"
            base_confidence = 0.65
        elif any(term in lower for term in ["equation", "formula", "수식"]):
            image_type = "equation"
            base_confidence = 0.65
        elif any(term in lower for term in ["logo", "decorative", "장식"]):
            image_type = "logo"
            base_confidence = 0.2
        elif any(term in lower for term in ["photograph", "photo", "image shows"]):
            image_type = "photograph"
            base_confidence = 0.45

        uncertainty_penalty = lower.count("확인할 수 없음") * 0.08 + lower.count("cannot determine") * 0.08
        x_axis = any(term in lower for term in ["x-axis", "x axis", "x축"])
        y_axis = any(term in lower for term in ["y-axis", "y axis", "y축"])
        units = any(term in lower for term in ["unit", "units", "단위", "psi", "ft", "ppg", "sg"])
        confidence = max(0.0, min(1.0, base_confidence - uncertainty_penalty))

        return {
            "image_type": image_type,
            "confidence": round(confidence, 2),
            "x_axis_confirmed": x_axis,
            "y_axis_confirmed": y_axis,
            "units_confirmed": units,
        }

    @staticmethod
    def _figure_note_confidence(note: str) -> float:
        match = re.search(r"^Confidence:\s*([0-9.]+)", note, flags=re.MULTILINE)
        if not match:
            return 0.5
        try:
            return float(match.group(1))
        except ValueError:
            return 0.0

    async def extract(
        self,
        file_path: Path,
        digest: str,
        analyze_figures: bool = True,
    ) -> tuple[DocumentRecord, list[dict[str, object]]]:
        self._figure_stats = self._empty_figure_stats()
        self._equation_stats = self._empty_equation_stats()
        suffix = file_path.suffix.lower()

        # 실제 저장 파일명에서 SHA-256 접두사 제거
        display_filename = self._display_filename(file_path, digest)

        if suffix == ".pdf":
            pages, figure_count = await self._extract_pdf(
                file_path,
                digest,
                analyze_figures,
            )
        elif suffix == ".txt":
            pages, figure_count = self._extract_text(file_path, digest), 0
        elif suffix in {".png", ".jpg", ".jpeg"}:
            pages, figure_count = await self._extract_image(file_path, digest), 1
        else:
            pages, figure_count = [
                {
                    "page": 1,
                    "text": (
                        f"Uploaded {suffix} document. "
                        "PPT text extraction is reserved for the Phase 2 parser."
                    ),
                }
            ], 0

        document_info = self.detect_document_info(pages, display_filename,)
        for page in pages:
            page["document_type"] = document_info.get("document_type", "")

        chunks = self.chunk_pages(pages, display_filename, digest)
        write_relation_graph(
            self.settings.ontology_dir / f"{digest}.jsonl",
            chunks,
        )
        record = DocumentRecord(
            document_id=digest,
            filename=display_filename,
            sha256=digest,
            status="processed",
            ingestion_version=INGESTION_VERSION,
            pages=len(pages),
            chunks=len(chunks),
            figures=figure_count,
            figures_analyzed=self._figure_stats["analyzed"],
            figures_valid=self._figure_stats["valid"],
            figures_review_required=self._figure_stats["review_required"],
            figures_failed=self._figure_stats["failed"],
            figures_ignored=self._figure_stats["ignored"],
            figure_vision_calls=self._figure_stats["vision_calls"],
            figure_analysis_enabled=analyze_figures,
            equations_detected=self._equation_stats["detected"],
            equations_analyzed=self._equation_stats["analyzed"],
            equations_valid=self._equation_stats["valid"],
            equations_review_required=self._equation_stats["review_required"],
            equations_failed=self._equation_stats["failed"],
            equation_vision_calls=self._equation_stats["vision_calls"],
            title=document_info.get("title"),
            document_type=document_info.get("document_type"),
            contents_pages=document_info.get("contents_pages", []),
            title_pages=document_info.get("title_pages", []),
        )

        (self.settings.extracted_dir / f"{digest}.json").write_text(
            json.dumps(
                {"pages": pages, "chunks": chunks},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        self.persist_record(record)
        return record, chunks

    def _extract_text(
        self,
        file_path: Path,
        digest: str,
    ) -> list[dict[str, object]]:
        return [
            {
                "page": 1,
                "text": file_path.read_text(encoding="utf-8", errors="ignore"),
                "document_id": digest,
            }
        ]

    async def _extract_image(
        self,
        file_path: Path,
        digest: str,
    ) -> list[dict[str, object]]:
        display_filename = self._display_filename(file_path, digest)
        target = self.settings.figures_dir / f"{digest}_{display_filename}"
        if not target.exists():
            shutil.copyfile(file_path, target)

        result = await self.figure_analyzer.analyze_figure(
            document_name=display_filename,
            document_id=digest,
            page_number=1,
            image_index=1,
            image_path=target,
            remaining_vision_calls=self.settings.figure_analysis_max_vision_calls,
        )
        self._record_figure_result(result)

        if result.should_index and result.note_text:
            text = f"Image analysis for {display_filename}:\n{result.note_text}"
        else:
            text = (
                f"Image analysis status for {display_filename}: {result.status}. "
                "The image note was not included in retrieval because it was not fully grounded."
            )

        return [
            {
                "page": 1,
                "text": text,
                "document_id": digest,
            }
        ]

    def _render_page_image_crop(
        self,
        page: object,
        xref: int,
        figure_path: Path,
    ) -> Path | None:
        if not self.settings.figure_page_render_fallback:
            return None
        try:
            import fitz

            rects = list(page.get_image_rects(xref))
            if not rects:
                return None
            rect = max(rects, key=lambda item: float(item.width * item.height))
            if rect.width <= 1 or rect.height <= 1:
                return None

            target = (
                self.settings.figure_analysis_inputs_dir
                / f"{figure_path.stem}_page_render.png"
            )
            if not target.exists():
                scale = max(1.0, self.settings.figure_page_render_scale)
                pixmap = page.get_pixmap(
                    matrix=fitz.Matrix(scale, scale),
                    clip=rect,
                    alpha=False,
                )
                pixmap.save(str(target))
            return target if target.is_file() else None
        except Exception as exc:  # one bad crop must not stop PDF ingestion
            print(
                f"[페이지 렌더링 fallback 건너뜀] {figure_path.name}: "
                f"{type(exc).__name__}: {exc}"
            )
            return None

    @staticmethod
    def _source_figure_caption(
        page: object,
        xref: int,
    ) -> dict[str, object] | None:
        """Match an embedded image to the nearest literal Figure caption."""
        try:
            import fitz

            rects = list(page.get_image_rects(xref))
            if not rects:
                return None
            image_rect = max(
                rects,
                key=lambda item: float(item.width * item.height),
            )
            image_center = (float(image_rect.x0) + float(image_rect.x1)) / 2.0

            candidates: list[tuple[float, dict[str, object]]] = []
            for block in page.get_text("blocks", sort=True):
                x0, y0, x1, y1, block_text = block[:5]
                caption = re.sub(r"\s+", " ", str(block_text or "")).strip()
                match = re.match(
                    r"(?i)^figure\s+([0-9]+[A-Za-z]?)\b\s*[:.\-]?\s*(.*)$",
                    caption,
                )
                if not match:
                    continue

                block_rect = fitz.Rect(x0, y0, x1, y1)
                if block_rect.y0 >= image_rect.y1 - 3:
                    vertical_gap = max(0.0, float(block_rect.y0 - image_rect.y1))
                    if vertical_gap > 150:
                        continue
                    position_penalty = 0.0
                elif block_rect.y1 <= image_rect.y0 + 3:
                    vertical_gap = max(0.0, float(image_rect.y0 - block_rect.y1))
                    if vertical_gap > 90:
                        continue
                    position_penalty = 35.0
                else:
                    vertical_gap = 0.0
                    position_penalty = 20.0

                block_center = (float(block_rect.x0) + float(block_rect.x1)) / 2.0
                center_delta = abs(block_center - image_center)
                score = vertical_gap + position_penalty + center_delta * 0.20

                candidates.append(
                    (
                        score,
                        {
                            "figure_number": match.group(1),
                            "source_caption": caption,
                            "caption_position": (
                                "below"
                                if block_rect.y0 >= image_rect.y1 - 3
                                else "above"
                                if block_rect.y1 <= image_rect.y0 + 3
                                else "overlap"
                            ),
                            "caption_distance": round(vertical_gap, 3),
                            "caption_match_score": round(score, 3),
                        },
                    )
                )

            if not candidates:
                return None
            return min(candidates, key=lambda item: item[0])[1]
        except Exception as exc:
            print(
                f"[Figure 캡션 연결 건너뜀] xref={xref}: "
                f"{type(exc).__name__}: {exc}"
            )
            return None

    @staticmethod
    def _enrich_figure_note_with_source_caption(
        note_text: str,
        caption_info: dict[str, object] | None,
    ) -> str:
        if not caption_info:
            return note_text
        number = str(caption_info.get("figure_number") or "").strip()
        caption = re.sub(
            r"\s+",
            " ",
            str(caption_info.get("source_caption") or ""),
        ).strip()
        if not number or not caption:
            return note_text

        lines = note_text.splitlines()
        try:
            marker_index = next(
                index
                for index, line in enumerate(lines)
                if line.strip().casefold() == "[figure note metadata]"
            )
        except StopIteration:
            return note_text

        fields = [
            f"figure_number: {number}",
            f"source_caption: {caption}",
            "source_caption_verified: true",
        ]
        lines[marker_index + 1 : marker_index + 1] = fields
        return "\n".join(lines).rstrip() + "\n"

    @staticmethod
    def _is_equation_block_candidate(
        text: str,
        *,
        rect_width: float,
        page_width: float,
    ) -> bool:
        value = re.sub(r"\s+", " ", str(text or "")).strip()
        if "=" not in value or not value:
            return False
        if len(value) > 180 or value.count("=") > 2:
            return False
        if rect_width > page_width * 0.78:
            return False
        word_count = len(re.findall(r"[A-Za-z]{2,}", value))
        if word_count > 20:
            return False

        lhs = bool(
            re.search(
                r"^[A-Za-zΑ-ωΔ∆φρµ][A-Za-z0-9_Α-ωΔ∆φρµ]{0,12}\s*=",
                value,
            )
        )
        numbered = bool(re.search(r"\(\s*\d{1,3}[A-Za-z]?\s*\)", value))
        math_signal = any(
            symbol in value
            for symbol in ("∆", "Δ", "φ", "ρ", "µ", "√", "≈", "≤", "≥", "^", "/")
        )
        return lhs or numbered or math_signal

    def _equation_regions(self, page: object) -> list[dict[str, object]]:
        """Find equations whose visual math contains non-text vector geometry."""
        try:
            import fitz

            candidates: list[dict[str, object]] = []
            page_width = float(page.rect.width)
            for block in page.get_text("blocks", sort=True):
                x0, y0, x1, y1, block_text = block[:5]
                if not self._is_equation_block_candidate(
                    str(block_text),
                    rect_width=float(x1 - x0),
                    page_width=page_width,
                ):
                    continue
                candidates.append(
                    {
                        "rect": fitz.Rect(x0, y0, x1, y1),
                        "raw_text": re.sub(r"\s+", " ", str(block_text)).strip(),
                    }
                )

            merged: list[dict[str, object]] = []
            for item in candidates:
                rect = fitz.Rect(item["rect"])
                attached = False
                for existing in merged:
                    current = fitz.Rect(existing["rect"])
                    vertical_gap = max(
                        0.0,
                        rect.y0 - current.y1,
                        current.y0 - rect.y1,
                    )
                    horizontal_overlap = min(rect.x1, current.x1) - max(
                        rect.x0,
                        current.x0,
                    )
                    horizontal_gap = max(
                        0.0,
                        rect.x0 - current.x1,
                        current.x0 - rect.x1,
                    )
                    if vertical_gap <= 8 and (
                        horizontal_overlap > 0 or horizontal_gap <= 60
                    ):
                        existing["rect"] = fitz.Rect(
                            min(current.x0, rect.x0),
                            min(current.y0, rect.y0),
                            max(current.x1, rect.x1),
                            max(current.y1, rect.y1),
                        )
                        existing["raw_text"] = (
                            f"{existing['raw_text']} {item['raw_text']}"
                        ).strip()
                        attached = True
                        break
                if not attached:
                    merged.append(item)

            drawings = list(page.get_drawings())
            risky: list[dict[str, object]] = []
            for item in merged:
                rect = fitz.Rect(item["rect"])
                probe = fitz.Rect(
                    max(0.0, rect.x0 - 12),
                    max(0.0, rect.y0 - 12),
                    min(float(page.rect.width), rect.x1 + 12),
                    min(float(page.rect.height), rect.y1 + 12),
                )
                related_drawings = []
                for drawing in drawings:
                    drawing_rect = fitz.Rect(drawing.get("rect"))
                    if drawing_rect.width > page_width * 0.70:
                        continue
                    expanded = fitz.Rect(
                        drawing_rect.x0 - 1,
                        drawing_rect.y0 - 1,
                        drawing_rect.x1 + 1,
                        drawing_rect.y1 + 1,
                    )
                    if expanded.intersects(probe):
                        related_drawings.append(drawing_rect)

                if not related_drawings:
                    continue

                x0, y0, x1, y1 = rect.x0, rect.y0, rect.x1, rect.y1
                for drawing_rect in related_drawings:
                    x0 = min(x0, drawing_rect.x0)
                    y0 = min(y0, drawing_rect.y0)
                    x1 = max(x1, drawing_rect.x1)
                    y1 = max(y1, drawing_rect.y1)

                crop = fitz.Rect(
                    max(0.0, x0 - 18),
                    max(0.0, y0 - 18),
                    min(float(page.rect.width), x1 + 18),
                    min(float(page.rect.height), y1 + 18),
                )
                risky.append(
                    {
                        "rect": (crop.x0, crop.y0, crop.x1, crop.y1),
                        "raw_text": item["raw_text"],
                        "vector_element_count": len(related_drawings),
                    }
                )
            return risky
        except Exception as exc:
            print(
                f"[수식 후보 감지 건너뜀] {type(exc).__name__}: {exc}"
            )
            return []

    def _render_equation_crop(
        self,
        page: object,
        rect_values: tuple[float, float, float, float],
        target: Path,
    ) -> Path | None:
        try:
            import fitz

            rect = fitz.Rect(*rect_values)
            if rect.width <= 1 or rect.height <= 1:
                return None
            if not target.exists():
                scale = max(2.0, self.settings.figure_page_render_scale)
                pixmap = page.get_pixmap(
                    matrix=fitz.Matrix(scale, scale),
                    clip=rect,
                    alpha=False,
                )
                pixmap.save(str(target))
            return target if target.is_file() else None
        except Exception as exc:
            print(
                f"[수식 crop 렌더링 건너뜀] {target.name}: "
                f"{type(exc).__name__}: {exc}"
            )
            return None

    async def _extract_pdf(
        self,
        file_path: Path,
        digest: str,
        analyze_figures: bool,
    ) -> tuple[list[dict[str, object]], int]:
        import fitz
        import pdfplumber

        pages: list[dict[str, object]] = []
        figure_jobs: list[dict[str, object]] = []
        equation_jobs: list[dict[str, object]] = []
        figure_count = 0
        vision_calls = 0
        equation_vision_calls = 0
        plumber_pdf = None
        display_filename = self._display_filename(file_path, digest)

        doc = fitz.open(file_path)

        try:
            plumber_pdf = pdfplumber.open(file_path)
        except Exception as exc:
            print(
                f"[pdfplumber 비활성화] {file_path.name}: "
                f"{type(exc).__name__}: {exc}"
            )
            plumber_pdf = None

        try:
            total_pages = len(doc)

            # Pass 1: extract every page and image without spending Vision calls.
            # This prevents front-matter decorations from consuming the entire
            # per-document Vision budget before later technical graphs are seen.
            for index, page in enumerate(doc):
                page_number = index + 1

                if page_number == 1 or page_number % 25 == 0:
                    print(f"[PDF 텍스트 추출] {page_number}/{total_pages}페이지")

                try:
                    text = page.get_text("text", sort=True).strip()
                except Exception as exc:
                    print(
                        f"[PyMuPDF 텍스트 추출 실패] {page_number}페이지: "
                        f"{type(exc).__name__}: {exc}"
                    )
                    text = ""

                plumber_text = ""
                if plumber_pdf is not None and index < len(plumber_pdf.pages):
                    try:
                        plumber_text = (
                            plumber_pdf.pages[index].extract_text(layout=True) or ""
                        ).strip()
                    except Exception as exc:
                        print(
                            f"[pdfplumber 건너뜀] {page_number}페이지: "
                            f"{type(exc).__name__}: {exc}"
                        )

                combined, text_extractor, extraction_diagnostics = (
                    self.select_page_text(text, plumber_text)
                )
                pages.append(
                    {
                        "page": page_number,
                        "text": combined,
                        "document_id": digest,
                        "text_extractor": text_extractor,
                        "text_extraction_diagnostics": extraction_diagnostics,
                    }
                )

                if analyze_figures:
                    equation_regions = self._equation_regions(page)
                    for equation_index, region in enumerate(equation_regions, start=1):
                        equation_path = (
                            self.settings.figure_analysis_inputs_dir
                            / f"{digest}_p{page_number}_eq{equation_index}.png"
                        )
                        rendered = self._render_equation_crop(
                            page,
                            tuple(region["rect"]),
                            equation_path,
                        )
                        if rendered is None:
                            continue
                        self._equation_stats["detected"] += 1
                        equation_jobs.append(
                            {
                                "page_index": index,
                                "page_number": page_number,
                                "equation_index": equation_index,
                                "image_path": rendered,
                                "raw_text": str(region.get("raw_text") or ""),
                                "vector_element_count": int(
                                    region.get("vector_element_count") or 0
                                ),
                            }
                        )

                try:
                    page_images = page.get_images(full=True)
                except Exception as exc:
                    print(
                        f"[페이지 이미지 목록 건너뜀] {page_number}페이지: "
                        f"{type(exc).__name__}: {exc}"
                    )
                    page_images = []

                for image_index, image_info in enumerate(page_images, start=1):
                    xref = image_info[0]
                    try:
                        extracted_image = doc.extract_image(xref)
                        image_bytes = extracted_image.get("image")
                        if not image_bytes:
                            continue

                        extension = extracted_image.get("ext", "png")
                        figure_path = (
                            self.settings.figures_dir
                            / f"{digest}_p{page_number}_fig{image_index}.{extension}"
                        )
                        if not figure_path.exists():
                            figure_path.write_bytes(image_bytes)
                        figure_count += 1
                    except Exception as exc:
                        print(
                            f"[PDF 이미지 추출 건너뜀] "
                            f"{page_number}페이지 Figure {image_index}: "
                            f"{type(exc).__name__}: {exc}"
                        )
                        continue

                    if not analyze_figures:
                        continue

                    caption_info = self._source_figure_caption(page, xref)
                    priority = self.figure_analyzer.priority_for_image(
                        figure_path,
                        combined,
                    )
                    figure_jobs.append(
                        {
                            "page_index": index,
                            "page_number": page_number,
                            "image_index": image_index,
                            "xref": xref,
                            "image_path": figure_path,
                            "page_text": combined,
                            "source_caption": caption_info,
                            "priority_score": float(priority.get("score") or 0.0),
                            "forced_classification": priority.get(
                                "forced_classification"
                            ),
                            "priority_reason": str(
                                priority.get("reason") or ""
                            ),
                        }
                    )

            if analyze_figures and equation_jobs:
                # Pass 2a: verify equations whose fraction bars, radicals, or
                # other vector geometry cannot be trusted in plain PDF text.
                page_equation_notes: dict[int, list[tuple[int, str]]] = {}
                page_equation_assets: dict[int, list[dict[str, object]]] = {}

                for job in equation_jobs:
                    page_number = int(job["page_number"])
                    equation_index = int(job["equation_index"])
                    equation_path = Path(str(job["image_path"]))
                    remaining_calls = max(
                        0,
                        self.settings.equation_analysis_max_vision_calls
                        - equation_vision_calls,
                    )
                    try:
                        result = await self.figure_analyzer.analyze_figure(
                            document_name=display_filename,
                            document_id=digest,
                            page_number=page_number,
                            image_index=equation_index,
                            image_path=equation_path,
                            remaining_vision_calls=remaining_calls,
                            forced_classification="equation",
                        )
                    except Exception as exc:
                        print(
                            f"[PDF 수식 분석 실패] {equation_path.name}: "
                            f"{type(exc).__name__}: {exc}"
                        )
                        continue

                    equation_vision_calls += result.vision_calls
                    self._record_equation_result(result)
                    page_equation_assets.setdefault(page_number, []).append(
                        {
                            "equation_index": equation_index,
                            "image_path": str(equation_path),
                            "status": result.status,
                            "confidence": result.confidence,
                            "raw_text": str(job.get("raw_text") or ""),
                            "vector_element_count": int(
                                job.get("vector_element_count") or 0
                            ),
                        }
                    )
                    if result.should_index and result.note_text:
                        page_equation_notes.setdefault(page_number, []).append(
                            (equation_index, result.note_text)
                        )

                for page_record in pages:
                    page_number = int(page_record.get("page") or 0)
                    assets = sorted(
                        page_equation_assets.get(page_number, []),
                        key=lambda item: int(item["equation_index"]),
                    )
                    if assets:
                        page_record["equation_assets"] = assets
                    notes = sorted(
                        page_equation_notes.get(page_number, []),
                        key=lambda item: item[0],
                    )
                    if notes:
                        page_record["text"] = (
                            str(page_record.get("text") or "")
                            + "\n\n[Extracted equation notes]\n"
                            + "\n".join(
                                f"Equation {equation_index}: {note_text}"
                                for equation_index, note_text in notes
                            )
                        )

            if analyze_figures and figure_jobs:
                # Pass 2b: analyze likely graphs/technical figures first.
                # Stable page/figure ordering is used as a tie breaker.
                figure_jobs.sort(
                    key=lambda job: (
                        -float(job.get("priority_score") or 0.0),
                        int(job.get("page_number") or 0),
                        int(job.get("image_index") or 0),
                    )
                )
                page_notes: dict[int, list[tuple[int, str]]] = {}

                for job in figure_jobs:
                    page_number = int(job["page_number"])
                    image_index = int(job["image_index"])
                    figure_path = Path(str(job["image_path"]))
                    forced_classification = (
                        str(job.get("forced_classification") or "").strip()
                        or None
                    )
                    remaining_calls = max(
                        0,
                        self.settings.figure_analysis_max_vision_calls
                        - vision_calls,
                    )

                    fallback_path = None
                    if (
                        remaining_calls > 0
                        and self.figure_analyzer.source_is_dark(figure_path)
                    ):
                        analysis_page = doc[int(job["page_index"])]
                        fallback_path = self._render_page_image_crop(
                            analysis_page,
                            int(job["xref"]),
                            figure_path,
                        )

                    print(
                        f"[PDF Figure 분석] page={page_number} "
                        f"figure={image_index} "
                        f"priority={float(job.get('priority_score') or 0.0):.1f} "
                        f"hint={forced_classification or 'vision_classify'} "
                        f"remaining_calls={remaining_calls}"
                    )

                    try:
                        result = await self.figure_analyzer.analyze_figure(
                            document_name=display_filename,
                            document_id=digest,
                            page_number=page_number,
                            image_index=image_index,
                            image_path=figure_path,
                            fallback_image_path=fallback_path,
                            remaining_vision_calls=remaining_calls,
                            forced_classification=forced_classification,
                        )
                    except Exception as exc:
                        print(
                            f"[PDF Figure 분석 실패] {figure_path.name}: "
                            f"{type(exc).__name__}: {exc}"
                        )
                        continue

                    vision_calls += result.vision_calls
                    self._record_figure_result(result)
                    print(
                        f"[PDF Figure 결과] {figure_path.name}: "
                        f"status={result.status}, "
                        f"type={result.classification}, "
                        f"vision_calls={result.vision_calls}"
                    )

                    if result.should_index and result.note_text:
                        indexed_note = self._enrich_figure_note_with_source_caption(
                            result.note_text,
                            job.get("source_caption")
                            if isinstance(job.get("source_caption"), dict)
                            else None,
                        )
                        if result.note_path is not None:
                            result.note_path.write_text(
                                indexed_note,
                                encoding="utf-8",
                            )
                        page_notes.setdefault(page_number, []).append(
                            (image_index, indexed_note)
                        )

                for page_record in pages:
                    page_number = int(page_record.get("page") or 0)
                    notes = sorted(
                        page_notes.get(page_number, []),
                        key=lambda item: item[0],
                    )
                    if notes:
                        page_record["text"] = (
                            str(page_record.get("text") or "")
                            + "\n\n[Extracted figure notes]\n"
                            + "\n".join(
                                f"Figure {image_index}: {note_text}"
                                for image_index, note_text in notes
                            )
                        )
        finally:
            if plumber_pdf is not None:
                try:
                    plumber_pdf.close()
                except Exception:
                    pass
            doc.close()

        print(
            f"[PDF 처리 완료] 추출 이미지 {figure_count}개, "
            f"Figure Vision 호출 {vision_calls}개, "
            f"수식 후보 {self._equation_stats['detected']}개, "
            f"Equation Vision 호출 {equation_vision_calls}개, "
            f"figure_valid={self._figure_stats['valid']}, "
            f"equation_valid={self._equation_stats['valid']}, "
            f"equation_review={self._equation_stats['review_required']}"
        )
        return pages, figure_count

    def detect_document_info(
        self,
        pages: list[dict[str, object]],
        filename: str,
    ) -> dict[str, object]:
        contents_pages: list[int] = []
        title_pages: list[int] = []
        title = Path(filename).stem
        document_type = "unknown"
        contents_terms = [
            "master author index",
            "master subject index",
            "spe symbols standard",
            "si metric conversion factors",
            "alphabetical list of units",
            "tables of recommended si units",
            "contents",
            "table of contents",
        ]

        for page in pages:
            page_num = int(page.get("page", 0))
            text = str(page.get("text", ""))
            lower = text.lower()
            hits = sum(1 for term in contents_terms if term in lower)
            is_contents = (
                ("contents" in lower and hits >= 2)
                or hits >= 4
            )

            if is_contents:
                page["is_contents"] = True
                page["heading"] = "Contents"
                contents_pages.append(page_num)

            if page_num <= 3:
                page["is_title_page"] = True
                title_pages.append(page_num)
                lines = [
                    line.strip()
                    for line in text.splitlines()
                    if len(line.strip()) > 5
                ]

                for line in lines[:8]:
                    if (
                        "petroleum engineering handbook" in line.lower()
                        or "indexes and standards" in line.lower()
                    ):
                        title = line
                        break

            if (
                "master author index" in lower
                or "master subject index" in lower
                or "spe symbols standard" in lower
            ):
                document_type = "indexes_and_standards"

        return {
            "title": title,
            "document_type": document_type,
            "contents_pages": sorted(set(contents_pages)),
            "title_pages": sorted(set(title_pages)),
        }

    def chunk_pages(
        self,
        pages: list[dict[str, object]],
        filename: str,
        digest: str,
    ) -> list[dict[str, object]]:
        return chunk_pages(
            pages,
            filename,
            digest,
            self.settings.chunk_size,
            self.settings.chunk_overlap,
        )
