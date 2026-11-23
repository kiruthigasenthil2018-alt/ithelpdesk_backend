from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All settings come from environment variables or the .env file."""

    app_name: str = "IT Helpdesk Agent"
    app_env: str = "development"  # set to "production" to enforce strict security checks
    debug: bool = False
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    # --- Security ---
    secret_key: str = ""  # JWT signing key. Generate: python -c "import secrets;print(secrets.token_urlsafe(48))"
    access_token_minutes: int = 120
    admin_email: str = ""  # an admin account is created at startup if both are set
    admin_password: str = ""
    login_max_attempts: int = 5
    lockout_minutes: int = 15
    rate_limit_login_per_min: int = 10
    rate_limit_register_per_min: int = 5
    rate_limit_chat_per_min: int = 20

    # --- LLM providers (free tiers). Tried in LLM_PROVIDER_ORDER; if one hits a limit, the next is used.
    llm_provider_order: str = "gemini,groq,openrouter"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    groq_base_url: str = "https://api.groq.com/openai/v1"
    openrouter_api_key: str = ""
    openrouter_model: str = "meta-llama/llama-3.3-70b-instruct:free"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    llm_timeout_seconds: float = 30.0
    llm_max_retries: int = 1  # per provider; failover to the next provider is the main safety net
    llm_backoff_seconds: float = 1.0
    provider_cooldown_seconds: int = 60  # how long a rate-limited provider is skipped

    # --- Database / cache ---
    database_url: str = "sqlite:///./helpdesk.db"
    auto_create_tables: bool = True  # dev convenience; Docker uses Alembic instead
    redis_url: str = ""  # empty -> in-memory fallback cache
    cache_ttl_seconds: int = 300

    # --- RAG ---
    chroma_path: str = "./chroma_db"
    chroma_collection: str = "it_knowledge"
    knowledge_base_dir: str = "./knowledge_base"
    upload_dir: str = "./uploads"
    max_upload_mb: int = 10
    max_files_per_request: int = 5
    embedding_backend: str = "sentence-transformers"  # or "hash" (offline/tests)
    embedding_model: str = "all-MiniLM-L6-v2"
    reranker: str = "lexical"  # or "cross-encoder"
    cross_encoder_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    chunk_size: int = 800
    chunk_overlap: int = 120
    retrieval_top_k: int = 4
    min_relevance: float = 0.30

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
