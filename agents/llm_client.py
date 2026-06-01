import instructor
from langsmith.wrappers import wrap_openai
from openai import OpenAI

from app.config import settings


def make_instructor_client():
    """Create the shared OpenRouter client used by all LLM agents.

    The OpenAI SDK retries 429 / 5xx errors automatically with exponential
    backoff when ``max_retries`` is set.
    """
    openai_client = OpenAI(
        api_key=settings.openrouter_api_key,
        base_url=settings.openrouter_base_url,
        max_retries=settings.max_api_retries,
        timeout=60.0,
    )

    if settings.langsmith_tracing:
        openai_client = wrap_openai(openai_client)

    return instructor.from_openai(openai_client)
