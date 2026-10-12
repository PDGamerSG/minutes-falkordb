"""A deterministic hashed bag-of-words embedder (768-d, unit norm) so tests, the bench and the MCP server
run without a model. Texts sharing tokens land close together; it is not semantic.

`validate_embedding` is the single gate every write path uses: the vector indexes are declared with
`dimension:768`, and FalkorDB stores a vector of another length happily but never returns it from KNN
(finding 10), so a wrong length is rejected here with a ValueError."""

from __future__ import annotations

import hashlib
import math
import re
from itertools import pairwise

DIM = 768
_TOKEN = re.compile(r"[a-z0-9]+")


def validate_embedding(embedding: list[float] | None, dim: int = DIM) -> list[float] | None:
    """Return the vector as a list of floats, or None; raise ValueError when its length is not `dim`."""
    if embedding is None:
        return None
    vec = [float(x) for x in embedding]
    if len(vec) != dim:
        raise ValueError(f"embedding must have {dim} dimensions, got {len(vec)}")
    return vec


def fake_embedding(text: str, dim: int = DIM) -> list[float]:
    """Hash each token (and each adjacent bigram) into a signed bucket, then L2-normalise."""
    vec = [0.0] * dim
    tokens = _TOKEN.findall(text.lower())
    features = tokens + [f"{a} {b}" for a, b in pairwise(tokens)]
    if not features:
        features = ["<empty>"]
    for feature in features:
        digest = hashlib.blake2b(feature.encode(), digest_size=8).digest()
        bucket = int.from_bytes(digest[:4], "big") % dim
        sign = 1.0 if digest[4] & 1 else -1.0
        vec[bucket] += sign
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]
