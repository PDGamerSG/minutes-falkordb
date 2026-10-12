"""Embedder: dimension, normalisation, determinism, prefixes, strictness, identity and offline loading."""

from __future__ import annotations

import math
import os
from pathlib import Path

import pytest
from ingest import embed as embed_mod
from ingest.embed import DEFAULT_ONNX_MODEL, DIM, Embedder, FakeEmbedder, l2_normalize, make_backend, resolve_model_files, with_prefix


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


def test_facade_fake_backend_and_identity():
    emb = Embedder(backend="fake")
    assert emb.dim == 768 and emb.name == "fake" and emb.is_fake
    assert emb.identity == "fake:fake-hashed-bow-768"
    assert emb.embed([]) == []
    assert len(emb.embed_one("x")) == 768


def test_onnx_failure_falls_back_to_fake_only_when_not_strict(monkeypatch, caplog):
    def boom(self, *args, **kwargs):
        raise OSError("gated repo: token required")

    monkeypatch.setattr(embed_mod.OnnxEmbedder, "__init__", boom)
    with caplog.at_level("WARNING"):
        backend = make_backend("onnx", hf_home=None, strict=False)
    assert isinstance(backend, FakeEmbedder)
    assert "ONNX embedder unavailable" in caplog.text


def test_strict_is_the_default(monkeypatch):
    def boom(self, *args, **kwargs):
        raise OSError("offline")

    monkeypatch.setattr(embed_mod.OnnxEmbedder, "__init__", boom)
    with pytest.raises(OSError):
        make_backend("onnx")
    with pytest.raises(OSError):
        Embedder("onnx")


def test_gemini_without_key_falls_back_only_when_not_strict(caplog):
    with caplog.at_level("WARNING"):
        assert isinstance(make_backend("gemini", api_key=None, strict=False), FakeEmbedder)
    with pytest.raises(ValueError):
        make_backend("gemini", api_key=None)


def test_unknown_backend_rejected():
    with pytest.raises(ValueError):
        make_backend("quantum")


def _warm_cache() -> Path | None:
    hf_home = os.environ.get("HF_HOME")
    if not hf_home:
        return None
    cache = Path(hf_home) / "hub"
    snapshots = cache / ("models--" + DEFAULT_ONNX_MODEL.replace("/", "--")) / "snapshots"
    if snapshots.is_dir() and any(snapshots.glob("*/tokenizer.json")) and any(snapshots.glob("*/onnx/*.onnx")):
        return cache
    return None


@pytest.mark.skipif(_warm_cache() is None, reason="needs the EmbeddingGemma ONNX model in HF_HOME")
def test_onnx_resolves_from_the_warm_cache_without_network(monkeypatch):
    import huggingface_hub

    def no_network(*args, **kwargs):
        raise AssertionError("list_repo_files must not be called when the model is cached")

    monkeypatch.setattr(huggingface_hub, "list_repo_files", no_network)
    monkeypatch.setattr(embed_mod, "list_repo_files", no_network, raising=False)
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    onnx_path, tokenizer_path = resolve_model_files(DEFAULT_ONNX_MODEL, _warm_cache())
    assert onnx_path.is_file() and tokenizer_path.is_file()


@pytest.mark.skipif(_warm_cache() is None, reason="needs the EmbeddingGemma ONNX model in HF_HOME")
def test_onnx_embedder_loads_offline(monkeypatch):
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    emb = Embedder("onnx", hf_home=os.environ["HF_HOME"])
    assert emb.name == "onnx" and emb.identity == f"onnx:{DEFAULT_ONNX_MODEL}" and not emb.is_fake
    q, doc, other = emb.embed(["When is the UPI flow due?", "The UPI flow lands on the 24th.", "The newsletter goes out on Thursdays."], "document")
    assert len(q) == 768 and abs(_norm(q) - 1.0) < 1e-4
    assert sum(a * b for a, b in zip(q, doc)) > sum(a * b for a, b in zip(q, other))


def test_offline_miss_is_a_clear_error(tmp_path, monkeypatch):
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    with pytest.raises(FileNotFoundError, match="HF_HUB_OFFLINE"):
        resolve_model_files("nobody/no-such-model", tmp_path)
