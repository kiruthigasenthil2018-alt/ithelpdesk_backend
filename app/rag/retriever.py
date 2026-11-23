"""Advanced retrieval: similarity search, metadata filter, MMR, reranking, citations."""

import numpy as np

from app.config import get_settings
from app.rag.embeddings import tokenize
from app.rag.store import KnowledgeStore, get_store


def mmr_select(query_emb: np.ndarray, doc_embs: np.ndarray, k: int, lam: float = 0.7) -> list[int]:
    """Maximal Marginal Relevance: balance relevance to the query vs. diversity."""
    if len(doc_embs) == 0:
        return []
    sims = doc_embs @ query_emb
    selected = [int(np.argmax(sims))]
    while len(selected) < min(k, len(doc_embs)):
        best_i, best_score = -1, -1e9
        for i in range(len(doc_embs)):
            if i in selected:
                continue
            redundancy = max(float(doc_embs[i] @ doc_embs[j]) for j in selected)
            score = lam * float(sims[i]) - (1 - lam) * redundancy
            if score > best_score:
                best_i, best_score = i, score
        selected.append(best_i)
    return selected


def lexical_coverage(query: str, text: str) -> float:
    """Share of query terms that appear in the chunk (0..1)."""
    q = set(tokenize(query))
    if not q:
        return 0.0
    return len(q & set(tokenize(text))) / len(q)


class Retriever:
    def __init__(self, store: KnowledgeStore | None = None):
        self.settings = get_settings()
        self.store = store or get_store()
        self._cross_encoder = None

    def _rerank_scores(self, query: str, texts: list[str], sims: list[float]) -> list[float]:
        if self.settings.reranker == "cross-encoder":
            if self._cross_encoder is None:
                from sentence_transformers import CrossEncoder

                self._cross_encoder = CrossEncoder(self.settings.cross_encoder_model)
            raw = self._cross_encoder.predict([(query, t) for t in texts])
            return [float(1 / (1 + np.exp(-r))) for r in raw]  # squash to 0..1
        return [0.5 * s + 0.5 * lexical_coverage(query, t) for s, t in zip(sims, texts)]

    def search(
        self,
        query: str,
        k: int | None = None,
        category: str | None = None,
        strategy: str = "mmr",
        rerank: bool = True,
    ) -> list[dict]:
        k = k or self.settings.retrieval_top_k
        if self.store.count() == 0:
            return []
        q_emb = np.array(self.store.embedder.embed([query])[0])
        res = self.store.query(q_emb.tolist(), n=max(k * 3, 10), category=category)

        docs, metas = res["documents"][0], res["metadatas"][0]
        sims = [max(0.0, 1.0 - d) for d in res["distances"][0]]  # cosine distance -> similarity
        embs = np.array(res["embeddings"][0])
        if not docs:
            return []

        idxs = mmr_select(q_emb, embs, k) if strategy == "mmr" else list(range(min(k, len(docs))))
        texts = [docs[i] for i in idxs]
        scores = (
            self._rerank_scores(query, texts, [sims[i] for i in idxs])
            if rerank
            else [sims[i] for i in idxs]
        )

        ranked = sorted(zip(idxs, scores), key=lambda p: p[1], reverse=True)
        results = []
        for n, (i, score) in enumerate(ranked, start=1):
            m = metas[i]
            results.append(
                {
                    "citation": f"[{n}] {m['source']} (p.{m['page']})",
                    "source": m["source"],
                    "page": m["page"],
                    "title": m.get("title", ""),
                    "category": m["category"],
                    "chunk_index": m["chunk_index"],
                    "score": round(float(score), 4),
                    "similarity": round(float(sims[i]), 4),
                    "text": docs[i],
                }
            )
        return results
