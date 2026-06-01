import httpx
import structlog
from app.config import settings

logger = structlog.get_logger()

_PLACEHOLDER_JAVA_HOSTS = frozenset({
    "your-java-service.com",
    "localhost",
    "127.0.0.1",
})


def _java_api_configured() -> bool:
    base = (settings.java_api_base_url or "").strip().rstrip("/")
    if not base or base.startswith("https://your-java"):
        return False
    try:
        from urllib.parse import urlparse
        host = (urlparse(base).hostname or "").lower()
    except Exception:
        return False
    if not host or host in _PLACEHOLDER_JAVA_HOSTS:
        return False
    if (settings.java_api_key or "").strip() in ("", "your_key_here"):
        return False
    return True


def push_winners(domain_names: list[str]) -> bool:
    """
    POST winners to Java endpoint
    """
    if settings.data_source != "prod":
        logger.info("java_api_client skipped in temp mode: push_winners", mode=settings.data_source, count=len(domain_names))
        return True
    
    if not domain_names:
        return True

    if not _java_api_configured():
        logger.warning(
            "java_api_client skipped: JAVA_API_BASE_URL / JAVA_API_KEY not configured",
            count=len(domain_names),
            hint="Set real values in .env or leave prod push disabled",
        )
        return True

    url = f"{settings.java_api_base_url.rstrip('/')}/api/winners"
    headers = {"Authorization": f"Bearer {settings.java_api_key}"}
    
    try:
        response = httpx.post(url, json={"domains": domain_names}, headers=headers, timeout=10.0)
        response.raise_for_status()
        logger.info("java_api_client success: push_winners", count=len(domain_names))
        return True
    except Exception as e:
        logger.error("java_api_client error: push_winners", error=str(e))
        return False

def get_ai_queue_status() -> dict:
    """
    GET status from Java endpoint
    """
    if settings.data_source != "prod":
        logger.info("java_api_client skipped in temp mode: get_ai_queue_status", mode=settings.data_source)
        return {"status": "skipped_temp_mode", "queue_length": 0}
        
    url = f"{settings.java_api_base_url.rstrip('/')}/api/queue_status"
    headers = {"Authorization": f"Bearer {settings.java_api_key}"}
    
    try:
        response = httpx.get(url, headers=headers, timeout=5.0)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error("java_api_client error: get_ai_queue_status", error=str(e))
        return {"status": "error", "error": str(e)}
