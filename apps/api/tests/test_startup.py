"""Startup must preserve the explicitly selected embedding space."""

import pytest

from apps.api.config import Settings
from apps.api.main import build_context


def test_unavailable_real_embedder_does_not_start_with_test_vectors(monkeypatch):
    def unavailable(*args, **kwargs):
        raise RuntimeError("embedding model unavailable")

    monkeypatch.setenv("HIVE_BACKEND", "fake")
    monkeypatch.setattr("ingest.embed.OnnxEmbedder", unavailable)
    settings = Settings(_env_file=None, llm_backend="fake", embed_backend="onnx")
    with pytest.raises(RuntimeError, match="embedding model unavailable"):
        build_context(settings)


def test_explicit_test_embeddings_are_allowed(monkeypatch):
    monkeypatch.setenv("HIVE_BACKEND", "fake")
    settings = Settings(_env_file=None, llm_backend="fake", embed_backend="fake")
    assert build_context(settings).embedder.is_fake
