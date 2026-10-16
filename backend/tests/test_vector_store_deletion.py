from app.services.vector_store import VectorStore


class FakeCollection:
    def __init__(self) -> None:
        self.deleted_ids: list[str] = []

    def get(self, *, where: dict[str, str]) -> dict[str, list[str]]:
        assert where == {"document_id": "a" * 64}
        return {"ids": ["chunk-1", "chunk-2"]}

    def delete(self, *, ids: list[str]) -> None:
        self.deleted_ids = ids


def test_delete_document_removes_matching_chroma_ids() -> None:
    store = VectorStore.__new__(VectorStore)
    store.collection = FakeCollection()

    deleted = store.delete_document("a" * 64)

    assert deleted == 2
    assert store.collection.deleted_ids == ["chunk-1", "chunk-2"]


def test_equation_image_index_is_not_treated_as_book_index() -> None:
    store = VectorStore.__new__(VectorStore)
    text = "[Equation Note Metadata]\nimage_index: 2\nequation_text: S_w = sqrt(R_w/R_wa)"
    score = store._keyword_score(text, ["sqrt", "Rwa"], {}, None)

    assert score >= 0.65
