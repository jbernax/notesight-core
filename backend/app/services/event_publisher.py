import json
import logging
from typing import Any
import redis

from app.config import settings

logger = logging.getLogger(__name__)

_redis_client: redis.Redis | None = None


def get_redis_client() -> redis.Redis:
    """Return a cached Redis client instance connected to settings.REDIS_URL."""
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis_client


def publish_job_event(job_id: str, data: dict[str, Any]) -> None:
    """Publish a real-time job status event to Redis channel `job:{job_id}`."""
    channel = f"job:{job_id}"
    try:
        payload = json.dumps(data)
        client = get_redis_client()
        client.publish(channel, payload)
        logger.debug("Published event to %s: %s", channel, payload)
    except Exception as exc:
        logger.warning("Failed to publish job event to Redis channel %s: %s", channel, exc)
