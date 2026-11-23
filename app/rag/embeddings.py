"""Embedding backends.

- sentence-transformers: real local semantic embeddings (default, downloads model once).
- hash: tiny deterministic bag-of-words embedder. Works offline; used by tests.
"""

import hashlib
import math
import re
from functools import lru_cache

from app.config import get_settings

STOPWORDS = {
    "the", "a", "an", "is", "are", "to", "of", "and", "or", "in", "on", "my", "i", "it", "for",
    "with", "that", "this", "be", "not", "can", "cant", "me", "we", "you", "your", "at", "as",
    "by", "from", "has", "have", "was", "were", "if", "do", "does", "how", "what", "when",
}


def tokenize(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    out = []
    for w in words:
        if w in STOPWORDS:
            continue
        for suffix in ("ing", "ed", "es", "s"):  # very light stemming
            if w.endswith(suffix) and len(w) - len(suffix) >= 3:
                w = w[: -len(suffix)]
                break
        out.append(w)
    return out


class HashEmbedder:
    dim = 384

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]

    def _embed_one(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for tok in tokenize(text):
            idx = int(hashlib.md5(tok.encode()).hexdigest(), 16) % self.dim
            vec[idx] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]


class SentenceTransformerEmbedder:
    def __init__(self, model_name: str):
        from sentence_transformers import SentenceTransformer  # heavy import, load lazily

        self.model = SentenceTransformer(model_name)

    def embed(self, texts: list[str]) -> list[list[float]]:
        return self.model.encode(texts, normalize_embeddings=True).tolist()


@lru_cache
def get_embedder():
    s = get_settings()
    if s.embedding_backend == "hash":
        return HashEmbedder()
    return SentenceTransformerEmbedder(s.embedding_model)
