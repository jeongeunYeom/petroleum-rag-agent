"""Exercise PDF ingestion, persistent search, citations and ontology together."""

from __future__ import annotations

import json

import fitz
from fastapi.testclient import TestClient

from app.api.routes import get_ollama, get_vector_store
from app.core.config import Settings, get_settings
from app.main import app
from app.services.vector_store import VectorStore


class StubOllama:
    async def list_models(self) -> list[str]:
        return ["qwen3:8b", "qwen2.5vl:7b"]

    async def chat(self, messages: list[dict], model: str) -> str:
        assert model == "qwen3:8b"
        assert "BHP means bottomhole pressure" in messages[-1]["content"]
        return (
            "BHP means bottomhole pressure "
            "[porosity_permeability_smoke.pdf, p.1]."
        )


def test_pdf_upload_ontology_chroma_and_cited_chat(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    settings = Settings(data_dir=data_dir, agent_workspace_dir=tmp_path / "workspace")
    for directory in (
        settings.raw_dir,
        settings.extracted_dir,
        settings.metadata_dir,
        settings.ontology_dir,
        settings.vector_db_dir,
        settings.figures_dir,
        settings.agent_runs_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)

    # Use real Chroma persistence and search while keeping the test offline.
    monkeypatch.setattr(
        VectorStore,
        "embed",
        lambda self, texts: [[1.0, 0.0] for _ in texts],
    )
    store = VectorStore(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_ollama] = lambda: StubOllama()
    app.dependency_overrides[get_vector_store] = lambda: store

    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text(
        (72, 72),
        "Reservoir porosity and permeability are measured together.\n"
        "BHP means bottomhole pressure in this example.",
    )
    pdf_bytes = pdf.tobytes()
    pdf.close()
    filename = "porosity_permeability_smoke.pdf"

    try:
        with TestClient(app) as client:
            before = client.get("/api/system/checklist").json()["knowledge_base"]
            assert before == {"documents": 0, "chunks": 0}

            response = client.post(
                "/api/documents/upload?analyze_figures=false",
                files={"file": (filename, pdf_bytes, "application/pdf")},
            )
            assert response.status_code == 200, response.text
            upload = response.json()
            assert upload["skipped"] is False
            record = upload["document"]
            assert record["pages"] == 1
            assert record["chunks"] >= 1
            digest = record["sha256"]

            docs = client.get("/api/documents").json()
            assert len(docs) == 1 and docs[0]["sha256"] == digest
            after = client.get("/api/system/checklist").json()["knowledge_base"]
            assert after == {"documents": 1, "chunks": record["chunks"]}

            saved = store.collection.get(include=["documents", "metadatas"])
            assert len(saved["ids"]) == record["chunks"]
            metadata = saved["metadatas"][0]
            assert metadata["document"] == filename
            assert metadata["page"] == 1
            assert metadata["ontology_version"] == "v0.2"
            assert {"porosity", "absolute_permeability", "bottomhole_pressure"} <= set(
                metadata["concepts"].split("|")
            )
            graph = data_dir / "ontology" / f"{digest}.jsonl"
            edges = [json.loads(line) for line in graph.read_text().splitlines()]
            assert any(
                edge["relation"] == "alias_of"
                and edge["source"] == "bhp"
                and edge["target"] == "bottomhole_pressure"
                for edge in edges
            )
            assert any(edge["relation"] == "co_occurs_with" for edge in edges)

            # Reopen the persisted DB as a new service instance before asking.
            reopened = VectorStore(settings)
            app.dependency_overrides[get_vector_store] = lambda: reopened
            answer = client.post(
                "/api/chat",
                json={"question": "What does BHP mean in the uploaded PDF?"},
            )
            assert answer.status_code == 200, answer.text
            result = answer.json()
            assert "bottomhole pressure" in result["answer"]
            assert result["sources"]
            assert result["sources"][0]["document"] == filename
            assert result["sources"][0]["page"] == 1

            again = client.post(
                "/api/documents/upload?analyze_figures=false",
                files={"file": (filename, pdf_bytes, "application/pdf")},
            )
            assert again.status_code == 200, again.text
            assert again.json()["skipped"] is True
            assert client.get("/api/system/checklist").json()["knowledge_base"] == after
    finally:
        app.dependency_overrides.clear()
