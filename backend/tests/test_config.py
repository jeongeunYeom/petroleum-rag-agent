from pathlib import Path

import pytest

from app.core.config import PROJECT_ROOT, resolve_data_dir, resolve_retrieval_mode


def test_default_data_dir_resolves_to_project_root_data(monkeypatch):
    monkeypatch.delenv("DATA_DIR", raising=False)

    assert resolve_data_dir() == (PROJECT_ROOT / "data").resolve()


def test_relative_data_dir_resolves_from_project_root():
    assert resolve_data_dir("custom_data") == (PROJECT_ROOT / "custom_data").resolve()


def test_absolute_data_dir_is_preserved(tmp_path: Path):
    assert resolve_data_dir(str(tmp_path)) == tmp_path.resolve()


def test_retrieval_mode_defaults_to_legacy_and_validates(monkeypatch):
    monkeypatch.delenv("RETRIEVAL_MODE", raising=False)
    assert resolve_retrieval_mode() == "legacy"
    assert resolve_retrieval_mode("HYBRID_RERANK") == "hybrid_rerank"
    with pytest.raises(ValueError, match="RETRIEVAL_MODE"):
        resolve_retrieval_mode("unknown")
