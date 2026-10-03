"""Embedder: dimension, normalisation, determinism, prefixes and the fallback path."""

from __future__ import annotations

import math

import pytest
from ingest import embed as embed_mod
from ingest.embed import DIM, Embedder, FakeEmbedder, l2_normalize, make_backend, with_prefix


def _norm(vec):
    return math.sqrt(sum(x * x for x in vec))


def test_fake_embedder_dim_and_norm():
    vectors = FakeEmbedder().embed(["Payments go first.", "The UPI flow is due on the 24th."])
    assert len(vectors) == 2
    assert all(len(v) == DIM for v in vectors)
    assert all(abs(_norm(v) - 1.0) < 1e-5 for v in vectors)


def test_fake_embedder_is_deterministic_and_kind_invariant():
    a = FakeEmbedder().embed(["UPI flow due"], "document")[0]
    b = FakeEmbedder().embed(["UPI flow due"], "query")[0]
    assert a == b


def test_fake_embedder_related_texts_are_closer():
    emb = FakeEmbedder()
    q, near, far = emb.embed(["UPI flow deadline", "the UPI flow is due Friday", "quarterly budget review"])
    dot_near = sum(x * y for x, y in zip(q, near))
    dot_far = sum(x * y for x, y in zip(q, far))
    assert dot_near > dot_far


def test_prefixes_follow_model_card():
    assert with_prefix("hello", "query") == "task: search result | query: hello"
    assert with_prefix("hello", "document") == "title: none | text: hello"


def test_l2_normalize_leaves_zero_rows():
    out = l2_normalize([[0.0, 0.0], [3.0, 4.0]])
    assert out[0].tolist() == [0.0, 0.0]
    assert pytest.approx(out[1].tolist()) == [0.6, 0.8]


def test_facade_fake_backend():
    emb = Embedder(backend="fake")
    assert emb.dim == 768 and emb.name == "fake" and emb.is_fake
    assert emb.embed([]) == []
    assert len(emb.embed_one("x")) == 768


def test_onnx_failure_falls_back_to_fake(monkeypatch, caplog):
    def boom(self, *args, **kwargs):
        raise OSError("gated repo: token required")

    monkeypatch.setattr(embed_mod.OnnxEmbedder, "__init__", boom)
    with caplog.at_level("WARNING"):
        backend = make_backend("onnx", hf_home=None)
    assert isinstance(backend, FakeEmbedder)
    assert "ONNX embedder unavailable" in caplog.text


def test_onnx_failure_is_raised_in_strict_mode(monkeypatch):
    def boom(self, *args, **kwargs):
        raise OSError("offline")

    monkeypatch.setattr(embed_mod.OnnxEmbedder, "__init__", boom)
    with pytest.raises(OSError):
        make_backend("onnx", strict=True)


def test_gemini_without_key_falls_back(caplog):
    with caplog.at_level("WARNING"):
        assert isinstance(make_backend("gemini", api_key=None), FakeEmbedder)
    with pytest.raises(ValueError):
        make_backend("gemini", api_key=None, strict=True)


def test_unknown_backend_rejected():
    with pytest.raises(ValueError):
        make_backend("quantum")
