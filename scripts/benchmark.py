"""Measure concurrent dashboard requests against a running OLAP instance."""

import argparse
import getpass
import json
import os
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from http.cookiejar import CookieJar
from threading import Barrier
from urllib.parse import urlencode
from urllib.request import Request, HTTPCookieProcessor, build_opener


def call(opener, url, body=None, *, post=False):
    request = Request(
        url,
        method="POST" if body is not None or post else "GET",
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json"} if body is not None else {},
    )
    with opener.open(request, timeout=15) as response:
        response.read()


def measure(sessions, url):
    start = Barrier(len(sessions) + 1)

    def request(session):
        start.wait(timeout=15)
        before = time.perf_counter()
        try:
            call(session, url)
        except Exception as exc:
            return None, str(exc)
        return time.perf_counter() - before, None

    with ThreadPoolExecutor(max_workers=len(sessions)) as executor:
        results = [executor.submit(request, session) for session in sessions]
        start.wait(timeout=15)
        pairs = [result.result() for result in results]
    times = sorted(elapsed for elapsed, error in pairs if error is None)
    errors = [error for _, error in pairs if error is not None]
    return times, errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8014")
    parser.add_argument("--username", default="manager")
    parser.add_argument("--users", type=int, default=100, choices=range(1, 201), metavar="1–200")
    parser.add_argument("--start", default="2025-11-01")
    parser.add_argument("--end", default="2026-11-01")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    password = os.environ.get("OLAP_BENCH_PASSWORD") or getpass.getpass("Dashboard password: ")
    filters = {"start": args.start, "end": args.end}
    sessions = []
    passed = True
    try:
        for _ in range(args.users):
            opener = build_opener(HTTPCookieProcessor(CookieJar()))
            call(opener, base + "/api/login", {"username": args.username, "password": password})
            sessions.append(opener)
        for name, options in (
            ("sales", filters),
            ("inventory", filters),
            ("cube", {**filters, "rows": "month", "columns": "region"}),
        ):
            elapsed, errors = measure(sessions, base + f"/api/{name}?" + urlencode(options))
            if elapsed:
                p95 = statistics.quantiles(elapsed, n=100, method="inclusive")[94] if len(elapsed) > 1 else elapsed[0]
                print(f"{name:>9}  {len(elapsed)}/{args.users} HTTP OK · p95 {p95:.3f}s · max {max(elapsed):.3f}s")
            if errors:
                print(f"{name:>9}  {len(errors)} errors · first: {errors[0]}", file=sys.stderr)
            passed &= not errors and max(elapsed, default=float("inf")) <= 5
    finally:
        for session in sessions:
            try:
                call(session, base + "/api/logout", post=True)
            except OSError:
                pass
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
