from functools import lru_cache

from app.rag.retriever import Retriever
from app.services.llm_service import GeminiClient, get_llm


@lru_cache
def get_retriever() -> Retriever:
    return Retriever()


def get_llm_client() -> GeminiClient:
    return get_llm()
