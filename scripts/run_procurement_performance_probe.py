#!/usr/bin/env python3
"""Read-only procurement performance/concurrency probe for QA environments.

This script intentionally performs GET requests only. It is designed for a
staging/QA environment with desensitized realistic data and converts the Round10
procurement reference into executable acceptance evidence:

- normal business pages: <= 3000 ms by default
- complex analytics pages: <= 5000 ms by default
- 100 concurrent users by default

It refuses to run until --allow-load is supplied. Redirects are not followed so
an unauthenticated 302->login cannot be mistaken for a successful business page.
Header values and URL query strings are never written to the evidence JSON.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import math
import ssl
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: N802
        return None


@dataclass(frozen=True)
class ProbeTarget:
    category: str
    url: str
    threshold_ms: float


def safe_url(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def percentile(values: list[float], percent: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil((percent / 100.0) * len(ordered)))
    return ordered[rank - 1]


def parse_headers(items: list[str]) -> dict[str, str]:
    headers: dict[str, str] = {}
    for item in items:
        if ":" not in item:
            raise ValueError("each --header must use 'Name: value'")
        name, value = item.split(":", 1)
        name = name.strip()
        value = value.strip()
        if not name or not value:
            raise ValueError("header name and value are required")
        headers[name] = value
    headers.setdefault("User-Agent", "Yueke-HR-Procurement-QA-Probe/1.0")
    headers.setdefault("Cache-Control", "no-cache")
    return headers


def build_opener() -> urllib.request.OpenerDirector:
    context = ssl.create_default_context()
    return urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=context),
        NoRedirect(),
    )


def one_request(
    opener: urllib.request.OpenerDirector,
    target: ProbeTarget,
    headers: dict[str, str],
    timeout: float,
    expected_status: int,
) -> dict:
    started = time.perf_counter()
    request = urllib.request.Request(target.url, headers=headers, method="GET")
    try:
        with opener.open(request, timeout=timeout) as response:
            payload = response.read()
            status = int(response.getcode())
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return {
            "ok": status == expected_status,
            "status": status,
            "elapsedMs": elapsed_ms,
            "bytes": len(payload),
            "error": None if status == expected_status else f"HTTP_{status}",
        }
    except urllib.error.HTTPError as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return {
            "ok": False,
            "status": int(exc.code),
            "elapsedMs": elapsed_ms,
            "bytes": 0,
            "error": f"HTTP_{exc.code}",
        }
    except Exception as exc:  # evidence records type only; no secret-bearing message
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return {
            "ok": False,
            "status": None,
            "elapsedMs": elapsed_ms,
            "bytes": 0,
            "error": type(exc).__name__,
        }


def summarize(target: ProbeTarget, results: list[dict]) -> dict:
    successful = [item for item in results if item["ok"]]
    times = [float(item["elapsedMs"]) for item in successful]
    failures: dict[str, int] = {}
    for item in results:
        if not item["ok"]:
            key = str(item.get("error") or "UNKNOWN")
            failures[key] = failures.get(key, 0) + 1
    max_ms = max(times) if times else None
    return {
        "category": target.category,
        "url": safe_url(target.url),
        "thresholdMs": target.threshold_ms,
        "requests": len(results),
        "successes": len(successful),
        "failures": len(results) - len(successful),
        "failureKinds": failures,
        "minMs": min(times) if times else None,
        "medianMs": statistics.median(times) if times else None,
        "p95Ms": percentile(times, 95),
        "p99Ms": percentile(times, 99),
        "maxMs": max_ms,
        "bytesTotal": sum(int(item["bytes"]) for item in successful),
        "pass": bool(times)
        and len(successful) == len(results)
        and max_ms is not None
        and max_ms <= target.threshold_ms,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--normal-url", action="append", default=[])
    parser.add_argument("--analytics-url", action="append", default=[])
    parser.add_argument("--header", action="append", default=[], help="e.g. 'Cookie: sessionid=...' (value is never logged)")
    parser.add_argument("--concurrency", type=int, default=100)
    parser.add_argument("--requests-per-url", type=int, default=100)
    parser.add_argument("--normal-threshold-ms", type=float, default=3000.0)
    parser.add_argument("--analytics-threshold-ms", type=float, default=5000.0)
    parser.add_argument("--timeout-seconds", type=float, default=10.0)
    parser.add_argument("--expected-status", type=int, default=200)
    parser.add_argument("--output-json", default="procurement-performance-evidence.json")
    parser.add_argument("--allow-load", action="store_true")
    args = parser.parse_args()

    if not args.allow_load:
        print("REFUSED: pass --allow-load after confirming the target is an authorized QA/staging system.", file=sys.stderr)
        return 2
    if not args.normal_url and not args.analytics_url:
        print("REFUSED: provide at least one --normal-url or --analytics-url.", file=sys.stderr)
        return 2
    if not 1 <= args.concurrency <= 200:
        print("REFUSED: --concurrency must be 1..200.", file=sys.stderr)
        return 2
    if not 1 <= args.requests_per_url <= 5000:
        print("REFUSED: --requests-per-url must be 1..5000.", file=sys.stderr)
        return 2
    if args.normal_threshold_ms <= 0 or args.analytics_threshold_ms <= 0 or args.timeout_seconds <= 0:
        print("REFUSED: thresholds and timeout must be positive.", file=sys.stderr)
        return 2

    try:
        headers = parse_headers(args.header)
    except ValueError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2

    targets = [
        *(ProbeTarget("NORMAL", url, args.normal_threshold_ms) for url in args.normal_url),
        *(ProbeTarget("ANALYTICS", url, args.analytics_threshold_ms) for url in args.analytics_url),
    ]
    for target in targets:
        parts = urllib.parse.urlsplit(target.url)
        if parts.scheme not in {"http", "https"} or not parts.netloc:
            print(f"REFUSED: invalid URL {safe_url(target.url)!r}", file=sys.stderr)
            return 2

    opener = build_opener()
    started_at = time.time()
    target_summaries = []
    for target in targets:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as pool:
            futures = [
                pool.submit(
                    one_request,
                    opener,
                    target,
                    headers,
                    args.timeout_seconds,
                    args.expected_status,
                )
                for _ in range(args.requests_per_url)
            ]
            results = [future.result() for future in futures]
        target_summaries.append(summarize(target, results))

    evidence = {
        "gate": "UNIVERSITY_HR_PROCUREMENT_PERFORMANCE_QA",
        "status": "PASS" if all(item["pass"] for item in target_summaries) else "FAIL",
        "startedAtEpoch": started_at,
        "finishedAtEpoch": time.time(),
        "concurrency": args.concurrency,
        "requestsPerUrl": args.requests_per_url,
        "expectedStatus": args.expected_status,
        "headerNames": sorted(headers.keys()),
        "thresholds": {
            "normalMs": args.normal_threshold_ms,
            "analyticsMs": args.analytics_threshold_ms,
        },
        "targets": target_summaries,
        "interpretation": (
            "Read-only HTTP evidence only. Run with desensitized realistic QA data and representative authenticated roles; "
            "database saturation, worker queues and browser rendering should be reviewed alongside this result."
        ),
    }
    output = Path(args.output_json)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
