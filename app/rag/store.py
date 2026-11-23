"""ChromaDB vector store (local, persistent)."""

from functools import lru_cache
from pathlib import Path

import chromadb
from chromadb.config import Settings as ChromaSettings

from app.config import get_settings
from app.rag.embeddings import get_embedder
from app.rag.ingestion import SUPPORTED, IngestionError, build_chunks


class KnowledgeStore:
    def __init__(self, path: str, collection: str, embedder):
        self.embedder = embedder
        self.client = chromadb.PersistentClient(
            path=path, settings=ChromaSettings(anonymized_telemetry=False)
        )
        self.collection = self.client.get_or_create_collection(
            name=collection, metadata={"hnsw:space": "cosine"}
        )

    def count(self) -> int:
        return self.collection.count()

    def ingest_file(self, path: Path) -> int:
        chunks = build_chunks(path)
        self.collection.delete(where={"source": path.name})  # re-ingesting replaces old chunks
        self.collection.add(
            ids=[c["id"] for c in chunks],
            documents=[c["text"] for c in chunks],
            metadatas=[c["metadata"] for c in chunks],
            embeddings=self.embedder.embed([c["text"] for c in chunks]),
        )
        return len(chunks)

    def ingest_folder(self, folder: Path) -> dict:
        report = {"files": 0, "chunks": 0, "errors": []}
        for path in sorted(folder.glob("*")):
            if path.suffix.lower() not in SUPPORTED:
                continue
            try:
                report["chunks"] += self.ingest_file(path)
                report["files"] += 1
            except IngestionError as exc:
                report["errors"].append(str(exc))
        return report

    def query(self, embedding: list[float], n: int, category: str | None = None) -> dict:
        n = max(1, min(n, self.count() or 1))
        kwargs = {"where": {"category": category}} if category else {}
        return self.collection.query(
            query_embeddings=[embedding],
            n_results=n,
            include=["documents", "metadatas", "distances", "embeddings"],
            **kwargs,
        )


@lru_cache
def get_store() -> KnowledgeStore:
    s = get_settings()
    return KnowledgeStore(s.chroma_path, s.chroma_collection, get_embedder())
