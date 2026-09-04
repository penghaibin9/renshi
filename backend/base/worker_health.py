"""Shared Redis heartbeat for non-HTTP runtime processes."""

import logging
import os
import time

import redis


logger = logging.getLogger(__name__)
HEARTBEAT_PREFIX = "renshi:worker"


def heartbeat_key(worker_name: str) -> str:
    normalized = str(worker_name).strip().lower()
    if not normalized or any(character not in "abcdefghijklmnopqrstuvwxyz0123456789-" for character in normalized):
        raise ValueError("worker heartbeat name must use lowercase letters, digits and hyphens")
    return f"{HEARTBEAT_PREFIX}:{normalized}:heartbeat"


def write_worker_heartbeat(worker_name: str) -> bool:
    """Publish process progress; failures are visible through health checks."""
    redis_url = os.environ.get("REDIS_URL", "")
    if not redis_url:
        logger.error("worker heartbeat unavailable because REDIS_URL is empty")
        return False
    try:
        client = redis.Redis.from_url(redis_url, socket_connect_timeout=3, socket_timeout=3)
        client.set(heartbeat_key(worker_name), str(time.time()), ex=300)
        return True
    except Exception:
        logger.exception("worker heartbeat write failed worker=%s", worker_name)
        return False
