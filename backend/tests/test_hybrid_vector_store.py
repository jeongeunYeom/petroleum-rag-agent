from types import SimpleNamespace

from app.services.hybrid_vector_store import HybridVectorStore


class FakeCollection:
    def __init__(self, rows):
        self.rows = rows

    def count(self):
        return len(self.rows)

    def get(self, include=None):
        del include
        return {
            "ids": [row["id"] for row in self.rows],
            "documents": [row["text"] for row in self.rows],
            "metadatas": [row.get("metadata", {}) for row in self.rows],
        }


def make_store(rows):
    store = HybridVectorStore.__new__(HybridVectorStore)
    store.settings = SimpleNamespace(
        hybrid_rrf_k=60,
        reranker_enabled=False,
    )
    store.collection = FakeCollection(rows)
    store._bm25 = None
    store._bm25_rows = []
    store._bm25_collection_count = -1
    store._reranker = None
    store._reranker_error = None
    return store


def test_bm25_prefers_exact_petroleum_terms():
    store = make_store(
        [
            {
                "id": "radial",
                "text": "During radial flow the pressure derivative forms a plateau.",
                "metadata": {"document": "Well_Test.pdf", "page": 10},
            },
            {
                "id": "storage",
                "text": "Wellbore storage shows a unit-slope diagonal at early time.",
                "metadata": {"document": "Well_Test.pdf", "page": 8},
            },
            {
                "id": "unrelated",
                "text": "Reservoir porosity is measured from core samples.",
                "metadata": {"document": "Petrophysics.pdf", "page": 2},
            },
        ]
    )

    hits = store.bm25_search(
        "radial flow pressure derivative plateau",
        top_k=3,
    )

    assert hits
    assert hits[0]["id"] == "radial"
    assert hits[0]["bm25_score"] == 1.0


def test_rrf_rewards_chunks_found_by_both_retrievers():
    store = make_store([])
    vector_hits = [
        {
            "id": "both",
            "text": "radial flow derivative plateau",
            "metadata": {},
            "distance": 0.3,
        },
        {
            "id": "dense-only",
            "text": "pressure transient analysis",
            "metadata": {},
            "distance": 0.2,
        },
    ]
    bm25_hits = [
        {
            "id": "both",
            "text": "radial flow derivative plateau",
            "metadata": {},
            "bm25_score": 0.9,
            "score": 0.9,
        },
        {
            "id": "keyword-only",
            "text": "radial flow",
            "metadata": {},
            "bm25_score": 0.8,
            "score": 0.8,
        },
    ]

    fused = store._reciprocal_rank_fusion(
        vector_hits,
        bm25_hits,
        prefer_metadata=None,
    )

    assert fused[0]["id"] == "both"
    assert fused[0]["vector_score"] > 0
    assert fused[0]["bm25_score"] > 0


def test_query_tokens_include_technical_expansion():
    store = make_store([])

    tokens = store._query_tokens("BHP를 설명해줘")

    assert "bhp" in tokens
    assert "bottomhole" in tokens or "bottom-hole" in tokens
    assert "pressure" in tokens
