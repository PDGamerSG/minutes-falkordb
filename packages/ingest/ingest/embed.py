"""Embeddings: EmbeddingGemma via ONNX Runtime (768-d, L2-normalized), with gemini and fake backends.

The :class:`Embedder` facade follows ``docs/contracts/llm.md``. Backend selection is by
``EMBED_BACKEND``. The library default is ``strict=True``: when the ONNX model cannot be loaded
the error is raised. Callers that prefer degraded service pass ``strict=False`` and get
:class:`FakeEmbedder` (hashed vectors) with a clear warning. ``Embedder.identity``
(``"<backend>:<model>"``) is what the pipeline records on the tenant so vectors from different
models are never mixed in one graph.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
from pathlib import Path
from typing import Any, Literal, Protocol

import numpy as np

log = logging.getLogger(__name__)

Kind = Literal["query", "document"]

DIM = 768
QUERY_PREFIX = "task: search result | query: {text}"
DOCUMENT_PREFIX = "title: none | text: {text}"
DEFAULT_ONNX_MODEL = "onnx-community/embeddinggemma-300m-ONNX"
DEFAULT_GEMINI_MODEL = "gemini-embedding-001"
DEFAULT_ONNX_FILES = (
    "onnx/model_quantized.onnx",
    "onnx/model_q8.onnx",
    "onnx/model_int8.onnx",
    "onnx/model_fp16.onnx",
    "onnx/model.onnx",
)

_TOKEN = re.compile(r"[a-z0-9]+")


def with_prefix(text: str, kind: Kind) -> str:
    """Apply the EmbeddingGemma prompt prefix for queries or documents."""
    template = QUERY_PREFIX if kind == "query" else DOCUMENT_PREFIX
    return template.format(text=text.strip())


def l2_normalize(matrix: np.ndarray) -> np.ndarray:
    """Row-wise L2 normalisation that leaves zero rows untouched."""
    arr = np.asarray(matrix, dtype=np.float32)
    if arr.ndim == 1:
        arr = arr[None, :]
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return arr / norms


class EmbedderBackend(Protocol):
    """What every backend provides."""

    name: str
    model: str
    source: str

    def embed(self, texts: list[str], kind: Kind = "document") -> list[list[float]]: ...


class FakeEmbedder:
    """Deterministic 768-d vectors: a hashed bag of words, L2-normalized.

    Texts sharing words land near each other, so recall over fake vectors is meaningful in
    demos. Queries and documents of identical text produce identical vectors.
    """

    name = "fake"
    model = "fake-hashed-bow-768"
    source = "in-process"
    dim = DIM

    def __init__(self) -> None:
        self._cache: dict[str, np.ndarray] = {}

    def _token_vector(self, token: str) -> np.ndarray:
        vec = self._cache.get(token)
        if vec is None:
            seed = int.from_bytes(hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest(), "little")
            vec = np.random.default_rng(seed).standard_normal(DIM).astype(np.float32)
            if len(self._cache) < 50_000:
                self._cache[token] = vec
        return vec

    def embed(self, texts: list[str], kind: Kind = "document") -> list[list[float]]:
        out: list[list[float]] = []
        for text in texts:
            tokens = set(_TOKEN.findall(text.lower())) or {"<empty>"}
            vec = np.zeros(DIM, dtype=np.float32)
            for token in tokens:
                vec += self._token_vector(token)
            out.append(l2_normalize(vec)[0].tolist())
        return out


class OnnxEmbedder:
    """EmbeddingGemma-300m through ONNX Runtime on CPU."""

    name = "onnx"
    dim = DIM

    def __init__(
        self,
        model: str = DEFAULT_ONNX_MODEL,
        hf_home: str | None = None,
        *,
        max_length: int = 1024,
        batch_size: int = 16,
        file_preference: tuple[str, ...] = DEFAULT_ONNX_FILES,
        local_dir: str | None = None,
    ) -> None:
        import onnxruntime as ort
        from tokenizers import Tokenizer

        self.model = model
        self.batch_size = batch_size
        cache_dir = Path(hf_home or os.environ.get("HF_HOME") or Path.home() / ".cache" / "huggingface") / "hub"
        cache_dir.mkdir(parents=True, exist_ok=True)

        if local_dir:
            root = Path(local_dir)
            onnx_path = next(iter(sorted(root.glob("**/*.onnx"))), None)
            if onnx_path is None:
                raise FileNotFoundError(f"no .onnx file under {root}")
            tokenizer_path = root / "tokenizer.json"
        else:
            onnx_path, tokenizer_path = resolve_model_files(model, cache_dir, file_preference)

        options = ort.SessionOptions()
        options.intra_op_num_threads = max(1, min(8, os.cpu_count() or 1))
        self.session = ort.InferenceSession(str(onnx_path), options, providers=["CPUExecutionProvider"])
        self.input_names = [i.name for i in self.session.get_inputs()]
        self.output_names = [o.name for o in self.session.get_outputs()]
        self.tokenizer = Tokenizer.from_file(str(tokenizer_path))
        pad_id = self.tokenizer.token_to_id("<pad>")
        self.tokenizer.enable_truncation(max_length)
        self.tokenizer.enable_padding(pad_id=pad_id if pad_id is not None else 0, pad_token="<pad>")
        self.source = str(onnx_path)
        log.info("ONNX embedder loaded from %s (inputs=%s outputs=%s)", onnx_path, self.input_names, self.output_names)

    def _run(self, texts: list[str]) -> np.ndarray:
        encodings = self.tokenizer.encode_batch(texts)
        ids = np.asarray([e.ids for e in encodings], dtype=np.int64)
        mask = np.asarray([e.attention_mask for e in encodings], dtype=np.int64)
        feeds: dict[str, Any] = {}
        for name in self.input_names:
            if name == "input_ids":
                feeds[name] = ids
            elif name == "attention_mask":
                feeds[name] = mask
            elif name == "token_type_ids":
                feeds[name] = np.zeros_like(ids)
            elif name == "position_ids":
                feeds[name] = np.tile(np.arange(ids.shape[1], dtype=np.int64), (ids.shape[0], 1))
        outputs = self.session.run(None, feeds)
        if "sentence_embedding" in self.output_names:
            arr = np.asarray(outputs[self.output_names.index("sentence_embedding")], dtype=np.float32)
        else:
            arr = np.asarray(outputs[0], dtype=np.float32)
        if arr.ndim == 3:
            weights = mask[..., None].astype(np.float32)
            arr = (arr * weights).sum(axis=1) / np.clip(weights.sum(axis=1), 1.0, None)
        if arr.shape[1] > DIM:
            arr = arr[:, :DIM]
        if arr.shape[1] != DIM:
            raise ValueError(f"embedding dim {arr.shape[1]} != {DIM}")
        return l2_normalize(arr)

    def embed(self, texts: list[str], kind: Kind = "document") -> list[list[float]]:
        prefixed = [with_prefix(t, kind) for t in texts]
        out: list[list[float]] = []
        for start in range(0, len(prefixed), self.batch_size):
            out.extend(self._run(prefixed[start : start + self.batch_size]).tolist())
        return out


def _cached(model: str, filename: str, cache_dir: Path) -> Path | None:
    """Path of ``filename`` in the local hub cache, or None (no network)."""
    from huggingface_hub import try_to_load_from_cache

    found = try_to_load_from_cache(model, filename, cache_dir=str(cache_dir))
    return Path(found) if isinstance(found, str) else None


def resolve_model_files(model: str, cache_dir: Path, file_preference: tuple[str, ...] = DEFAULT_ONNX_FILES) -> tuple[Path, Path]:
    """``(onnx_path, tokenizer_path)``: the warm cache first, the Hub only on a miss.

    A fully cached model loads with no network at all (``HF_HUB_OFFLINE=1`` works), which is
    what a container cold start on hackathon Wi-Fi needs. On a miss the repo is listed once and
    the model, its external-data sidecar and the tokenizer files are downloaded.
    """
    from huggingface_hub import hf_hub_download, list_repo_files

    tokenizer_path = _cached(model, "tokenizer.json", cache_dir)
    if tokenizer_path is not None:
        for candidate in file_preference:
            onnx_path = _cached(model, candidate, cache_dir)
            if onnx_path is None:
                continue
            # an external-data sidecar must sit next to the model when the repo ships one
            sidecars = [p for p in (f"{candidate}_data", f"{candidate}.data")]
            if any(_cached(model, s, cache_dir) is not None for s in sidecars) or _sidecar_not_needed(onnx_path):
                log.info("ONNX embedder: using cached %s (no network)", onnx_path)
                return onnx_path, tokenizer_path

    if os.environ.get("HF_HUB_OFFLINE", "").strip().lower() in {"1", "true", "yes"}:
        raise FileNotFoundError(f"{model} is not in the local cache {cache_dir} and HF_HUB_OFFLINE is set")
    files = set(list_repo_files(model))
    onnx_file = next((f for f in file_preference if f in files), None)
    if onnx_file is None:
        onnx_file = next((f for f in sorted(files) if f.endswith(".onnx")), None)
    if onnx_file is None:
        raise FileNotFoundError(f"{model} has no .onnx file")
    onnx_path = Path(hf_hub_download(model, onnx_file, cache_dir=str(cache_dir)))
    for sidecar in (f"{onnx_file}_data", f"{onnx_file}.data"):
        if sidecar in files:
            hf_hub_download(model, sidecar, cache_dir=str(cache_dir))
    tokenizer_path = Path(hf_hub_download(model, "tokenizer.json", cache_dir=str(cache_dir)))
    for optional in ("tokenizer_config.json", "special_tokens_map.json", "config.json"):
        if optional in files:
            hf_hub_download(model, optional, cache_dir=str(cache_dir))
    return onnx_path, tokenizer_path


def _sidecar_not_needed(onnx_path: Path) -> bool:
    """A model file that is large on its own carries its weights inline (no external-data sidecar)."""
    try:
        return onnx_path.stat().st_size > 50_000_000
    except OSError:
        return False


class GeminiEmbedder:
    """gemini-embedding-001 with ``output_dimensionality=768`` (normalised client-side)."""

    name = "gemini"
    dim = DIM
    source = "https://generativelanguage.googleapis.com"

    def __init__(self, api_key: str, model: str = DEFAULT_GEMINI_MODEL, *, batch_size: int = 100) -> None:
        from google import genai

        self.model = model
        self.batch_size = batch_size
        self._client = genai.Client(api_key=api_key)

    def embed(self, texts: list[str], kind: Kind = "document") -> list[list[float]]:
        from google.genai import types

        task = "RETRIEVAL_QUERY" if kind == "query" else "RETRIEVAL_DOCUMENT"
        out: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start : start + self.batch_size]
            response = self._client.models.embed_content(
                model=self.model,
                contents=batch,
                config=types.EmbedContentConfig(task_type=task, output_dimensionality=DIM),
            )
            vectors = np.asarray([e.values for e in response.embeddings], dtype=np.float32)
            out.extend(l2_normalize(vectors).tolist())
        return out


def make_backend(
    backend: str = "onnx",
    model: str | None = None,
    hf_home: str | None = None,
    api_key: str | None = None,
    *,
    strict: bool = True,
) -> EmbedderBackend:
    """Build the requested backend; raise on failure (default) or degrade to :class:`FakeEmbedder` with a warning."""
    backend = (backend or "onnx").lower()
    if backend == "fake":
        return FakeEmbedder()
    if backend == "onnx":
        try:
            return OnnxEmbedder(model or DEFAULT_ONNX_MODEL, hf_home)
        except Exception as exc:
            if strict:
                raise
            log.warning(
                "ONNX embedder unavailable (%s: %s). %s",
                type(exc).__name__,
                str(exc).splitlines()[0][:200],
                "Falling back to gemini-embedding-001." if api_key else "Falling back to FakeEmbedder (hashed vectors).",
            )
            if api_key:
                try:
                    return GeminiEmbedder(api_key)
                except Exception as gexc:  # noqa: BLE001
                    log.warning("Gemini embedder unavailable (%s); using FakeEmbedder.", gexc)
            return FakeEmbedder()
    if backend == "gemini":
        if not api_key:
            if strict:
                raise ValueError("EMBED_BACKEND=gemini requires GEMINI_API_KEY")
            log.warning("EMBED_BACKEND=gemini but GEMINI_API_KEY is empty; using FakeEmbedder.")
            return FakeEmbedder()
        return GeminiEmbedder(api_key, model or DEFAULT_GEMINI_MODEL)
    raise ValueError(f"unknown EMBED_BACKEND {backend!r} (expected onnx | gemini | fake)")


class Embedder:
    """Contract facade: ``Embedder(...).embed(texts, kind)`` returns 768-d L2-normalized vectors."""

    dim: int = DIM

    def __init__(
        self,
        backend: str = "onnx",
        model: str | None = None,
        hf_home: str | None = None,
        api_key: str | None = None,
        *,
        strict: bool = True,
    ) -> None:
        self._backend = make_backend(backend, model, hf_home, api_key, strict=strict)

    @property
    def identity(self) -> str:
        """``"<backend>:<model>"``: recorded per tenant so stored vectors are never mixed across models."""
        return f"{self._backend.name}:{self._backend.model}"

    @property
    def name(self) -> str:
        return self._backend.name

    @property
    def model(self) -> str:
        return self._backend.model

    @property
    def source(self) -> str:
        return self._backend.source

    @property
    def is_fake(self) -> bool:
        return isinstance(self._backend, FakeEmbedder)

    def embed(self, texts: list[str], kind: Kind = "document") -> list[list[float]]:
        if not texts:
            return []
        return self._backend.embed(list(texts), kind)

    def embed_one(self, text: str, kind: Kind = "document") -> list[float]:
        return self.embed([text], kind)[0]
