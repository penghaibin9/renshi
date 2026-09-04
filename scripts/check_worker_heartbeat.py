"""Tiny Docker healthcheck that intentionally avoids Django startup."""

import os
import sys
import time

import redis


def main():
    if len(sys.argv) != 3:
        raise SystemExit("usage: check_worker_heartbeat.py WORKER_NAME MAX_AGE_SECONDS")
    name = sys.argv[1]
    max_age = float(sys.argv[2])
    redis_url = os.environ.get("REDIS_URL", "")
    if not redis_url:
        raise SystemExit("REDIS_URL is required")
    client = redis.Redis.from_url(redis_url, socket_connect_timeout=3, socket_timeout=3)
    value = client.get(f"renshi:worker:{name}:heartbeat")
    if value is None:
        raise SystemExit(f"heartbeat missing for {name}")
    age = time.time() - float(value)
    if age < 0 or age > max_age:
        raise SystemExit(f"heartbeat stale for {name}: age={age:.1f}s")
    print(f"heartbeat ok worker={name} age={age:.1f}s")


if __name__ == "__main__":
    main()
