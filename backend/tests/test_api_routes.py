from fastapi.testclient import TestClient

from app.api.routes import get_vector_store
from app.core.config import Settings, get_settings
from app.main import app


client = TestClient(app)


def test_refactored_routes_are_registered() -> None:
    paths = {route.path for route in app.routes}

    assert "/api/figures/{filename}" in paths
    assert "/api/figure-previews/{filename}" in paths
    assert "/api/evaluation/runs" in paths
    assert "/api/evaluation/latest" in paths
    assert "/api/evaluation/runs/{run_id}" in paths
    assert "/api/review/summary" in paths
    assert "/api/review/candidates" in paths
    assert "/api/review/candidates/{candidate_id}" in paths
    assert "/api/review/candidates/{candidate_id}/rotation" in paths
    assert "/api/review/candidates/{candidate_id}/preview" in paths
    assert "/api/review/candidates/{candidate_id}/preview-image" in paths
    assert "/api/review/audit" in paths
    assert "/api/research/evidence" in paths
    assert "/api/documents/{document_id}" in paths


def test_invalid_evaluation_run_id_returns_404() -> None:
    response = client.get("/api/evaluation/runs/not-a-valid-run-id")

    assert response.status_code == 404
    assert "유효하지 않은 benchmark run ID" in response.json()["detail"]


def test_unsupported_figure_extension_returns_404() -> None:
    response = client.get("/api/figures/not-an-image.txt")

    assert response.status_code == 404


def test_delete_document_removes_chunks_and_owned_files(tmp_path) -> None:
    document_id = "a" * 64
    other_id = "b" * 64
    settings = Settings(data_dir=tmp_path)
    directories = [
        settings.raw_dir,
        settings.extracted_dir,
        settings.figures_dir,
        settings.figure_notes_dir,
        settings.figure_candidates_dir,
        settings.figure_analysis_inputs_dir,
        settings.metadata_dir,
        settings.ontology_dir,
        settings.data_dir / "figure_display_previews",
    ]
    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)

    owned_files = [
        settings.raw_dir / f"{document_id}_manual.pdf",
        settings.extracted_dir / f"{document_id}.json",
        settings.figures_dir / f"{document_id}_p1_fig1.png",
        settings.figure_notes_dir / f"{document_id}_p1_fig1.md",
        settings.figure_analysis_inputs_dir / f"{document_id}_p1_fig1.png",
        settings.metadata_dir / f"{document_id}.json",
        settings.ontology_dir / f"{document_id}.jsonl",
        settings.data_dir
        / "figure_display_previews"
        / f"{document_id}_p1_fig1_display.png",
    ]
    for path in owned_files:
        path.write_text("test", encoding="utf-8")
    candidate_file = (
        settings.figure_candidates_dir
        / document_id
        / "candidate.json"
    )
    candidate_file.parent.mkdir()
    candidate_file.write_text("{}", encoding="utf-8")
    unrelated = settings.raw_dir / f"{other_id}_manual.pdf"
    unrelated.write_text("keep", encoding="utf-8")

    class FakeVectorStore:
        deleted: list[str] = []

        def delete_document(self, target: str) -> int:
            self.deleted.append(target)
            return 3

    vector_store = FakeVectorStore()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_vector_store] = lambda: vector_store
    try:
        response = client.delete(f"/api/documents/{document_id}")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {
        "document_id": document_id,
        "deleted_chunks": 3,
        "deleted_files": len(owned_files) + 1,
    }
    assert vector_store.deleted == [document_id]
    assert all(not path.exists() for path in owned_files)
    assert not candidate_file.parent.exists()
    assert unrelated.read_text(encoding="utf-8") == "keep"


def test_delete_document_rejects_invalid_id() -> None:
    response = client.delete("/api/documents/not-a-document-id")

    assert response.status_code == 400
