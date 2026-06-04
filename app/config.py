import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = PROJECT_ROOT / ".env"

# Pydantic reads .env values into Settings, but libraries like LangSmith read
# directly from os.environ. Loading it here makes both paths see the same config.
load_dotenv(ENV_FILE)

class Settings(BaseSettings):
    openrouter_api_key: str
    openrouter_base_url: str = "https://openrouter.ai/api/v1"

    # Model IDs — all agents read from here, never hardcoded
    model_fast: str                  # bulk classifier + linguistic agent
    model_pro: str                   # market research + valuation agent

    tavily_api_key: str

    # DATA_SOURCE controls input origin — "file" | "temp" | "prod"
    data_source: str = "file"

    # Prod/temp MySQL: which process_date to load (YYYY-MM-DD). Empty = yesterday.
    pipeline_process_date: str = "2026-05-20"

    # When False, pipeline writes only to data/results_output.csv (no MySQL results table).
    save_results_to_db: bool = False

    db_url_temp: str = ""
    db_url_prod: str = ""
    java_api_base_url: str = ""
    java_api_key: str = ""

    langsmith_tracing: bool = False
    langsmith_endpoint: str = "https://api.smith.langchain.com"
    langsmith_api_key: str = ""
    langsmith_project: str = "namekart-ai-agents"
    
    # Pipeline throttling (tune for your OpenRouter tier)
    max_concurrent_domains: int = 5       # max parallel market-search workers
    request_delay_seconds: float = 0.25   # pause between LLM batches, not every domain
    max_api_retries: int = 5              # retries on 429 / server errors
    pipeline_batch_size: int = 500        # domains per pipeline chunk after bulk filtering
    bulk_llm_batch_size: int = 500        # domains per bulk LLM call (when enabled)

    # ── Bulk classifier (stage 1 — eliminate junk early) ───────────────────
    bulk_filter_pass_score: int = 6           # lowered to allow PASS_MID domains into linguistic gate
    bulk_min_stem_length: int = 4
    bulk_max_stem_length: int = 14            # brandable names are short; was effectively unlimited
    bulk_reject_digits: bool = True
    bulk_reject_dashes: bool = True
    bulk_reject_hyper_keywords: bool = True   # long SEO-style names (e.g. *insurance, *marketing)
    bulk_reject_geo_keywords: bool = True     # city-prefixed keyword domains
    bulk_block_weak_tlds: bool = True         # reject .info, .biz, .online, etc. at bulk stage
    bulk_allowed_tlds: str = ""               # comma-separated allowlist; empty = use tier rules

    # ── Linguistic gate (stage 2 — quality over quantity) ──────────────────
    linguistic_gate_threshold: float = 6.4    # calibrated to realistic 4/6/8 linguistic scoring distribution
    linguistic_min_pronounceability: int = 6
    linguistic_min_memorability: int = 6
    linguistic_min_spelling_ease: int = 4
    linguistic_min_dimension_score: int = 5
    linguistic_min_brand_signal: int = 5        # relaxed to recover good auction domains with one weaker sub-dimension
    linguistic_min_industry_fit: int = 5
    linguistic_block_weak_tlds: bool = True
    max_market_candidates_per_run: int = 100  # cap expensive APR/market work; 0 = no cap

    # Determinism guard: force repeatable outputs for same domain inputs.
    # When true, bulk + linguistic ignore LLM paths even if use_llm_* is true.
    enforce_deterministic_pipeline: bool = True

    # Cost controls
    use_llm_bulk_classifier: bool = False   # deterministic bulk scoring by default
    use_llm_linguistic: bool = False        # local score is enough for first-pass gating
    use_llm_market: bool = True             # synthesize only domains with relevant search evidence
    use_llm_valuation: bool = False         # deterministic scorer avoids empty LLM decisions

    # Batch sizes (domains per LLM call)
    linguistic_batch_size: int = 10         # linguistic agent: pure text, can batch more
    market_batch_size: int = 10             # market agent: includes compact search results
    market_search_results: int = 2          # Tavily results per query
    max_search_content_chars: int = 120     # truncate search content to save tokens in batch

    cron_hour: int = 12
    cron_minute: int = 30

    # ── APR-Prediction-Agent Integration (disabled — two-agent pipeline only) ─
    use_apr_agent: bool = False
    apr_agent_path: str = "C:/dev/Namekart/APR-Prediction-Agent"
    apr_chroma_db_path: str = ""  # empty = APR agent auto-resolves from its own folder
    apr_agent_provider: str = "openrouter"   # "nvidia" | "openrouter" | "gemini"
    apr_agent_fallback_to_market: bool = True  # Fall back to Tavily if APR agent fails

    model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore")

settings = Settings()


def configure_langsmith_environment() -> None:
    """Keep LangSmith's SDK environment in sync with Settings."""
    os.environ["LANGSMITH_TRACING"] = "true" if settings.langsmith_tracing else "false"
    os.environ["LANGSMITH_ENDPOINT"] = settings.langsmith_endpoint
    os.environ["LANGSMITH_PROJECT"] = settings.langsmith_project

    if settings.langsmith_api_key:
        os.environ["LANGSMITH_API_KEY"] = settings.langsmith_api_key


configure_langsmith_environment()
