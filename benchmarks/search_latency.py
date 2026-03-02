#!/usr/bin/env python3
# (C) 2026 Rodrigo Rodrigues da Silva <rodrigopitanga@posteo.net>
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Search latency benchmark for PatchVec.

Usage:
    python benchmarks/search_latency.py [--url URL] [--queries N] [--concurrency C]

Indexes sample data, fires concurrent searches, and reports latency percentiles.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
import traceback

try:
    import httpx
except ImportError:
    raise SystemExit("httpx required: pip install httpx")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import print_run_header  # type: ignore[import]  # noqa: E402

SAMPLE_DOCS = [
    ("doc1", "Machine learning is a subset of artificial intelligence that "
     "enables systems to learn from data."),
    ("doc2", "Natural language processing helps computers understand human "
     "language and text."),
    ("doc3", "Deep learning uses neural networks with many layers to model "
     "complex patterns."),
    ("doc4", "Vector databases store embeddings for efficient similarity "
     "search operations."),
    ("doc5", "Semantic search finds results based on meaning rather than "
     "exact keyword matches."),
    ("doc6", "Transformers revolutionized NLP with attention mechanisms and "
     "parallel processing."),
    ("doc7", "Embeddings represent text as dense vectors in high-dimensional "
     "space."),
    ("doc8", "Retrieval augmented generation combines search with language "
     "model outputs."),
    ("doc9", "Cosine similarity measures the angle between two vectors for "
     "comparison."),
    ("doc10", "Fine-tuning adapts pre-trained models to specific domains and "
     "tasks."),
]

QUERIES = [
    "machine learning artificial intelligence",
    "natural language understanding",
    "neural networks deep learning",
    "vector similarity search",
    "semantic meaning search",
    "transformer attention mechanism",
    "text embeddings representation",
    "retrieval generation",
    "similarity comparison",
    "model fine-tuning",
]


def percentile(data: list[float], p: float) -> float:
    if not data:
        return 0.0
    sorted_data = sorted(data)
    k = (len(sorted_data) - 1) * p / 100
    f = int(k)
    c = f + 1 if f + 1 < len(sorted_data) else f
    return sorted_data[f] + (k - f) * (sorted_data[c] - sorted_data[f])


async def _post_with_retries(
    client: httpx.AsyncClient,
    url: str,
    attempts: int = 3,
    sleep_s: float = 0.5,
    **kwargs,
) -> httpx.Response:
    last_resp: httpx.Response | None = None
    for i in range(attempts):
        resp = await client.post(url, **kwargs)
        last_resp = resp
        if resp.status_code < 400:
            return resp
        if i < attempts - 1:
            await asyncio.sleep(sleep_s * (i + 1))
    assert last_resp is not None
    return last_resp


async def setup_collection(
    client: httpx.AsyncClient,
    tenant: str,
    collection: str,
    attempts: int = 3,
):
    """Create collection and index sample documents."""
    resp = await _post_with_retries(
        client,
        f"/collections/{tenant}/{collection}",
        attempts=attempts,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"create collection failed: {_parse_error(resp)}")
    for docid, text in SAMPLE_DOCS:
        resp = await _post_with_retries(
            client,
            f"/collections/{tenant}/{collection}/documents",
            attempts=attempts,
            files={"file": (f"{docid}.txt", text.encode(), "text/plain")},
            data={"docid": docid},
        )
        if resp.status_code >= 400:
            raise RuntimeError(f"seed ingest failed: {_parse_error(resp)}")


def _parse_error(resp: httpx.Response) -> str:
    try:
        payload = resp.json()
    except Exception:
        payload = None
    if isinstance(payload, dict):
        code = payload.get("code")
        error = payload.get("error")
        if code or error:
            return f"{code or 'error'}: {error or 'request failed'}"
    return f"http_{resp.status_code}"


async def search(
    client: httpx.AsyncClient,
    tenant: str,
    collection: str,
    query: str,
) -> tuple[float, bool | None, str, list[dict]]:
    """Perform a search and return latency, ok flag, detail, and hits.

    Returns ok=None for 429 rate-limited responses so callers can track them
    separately from genuine errors.
    """
    start = time.perf_counter()
    r = await client.post(
        f"/collections/{tenant}/{collection}/search",
        json={"q": query, "k": 5},
    )
    latency_ms = (time.perf_counter() - start) * 1000
    if r.status_code == 429:
        return latency_ms, None, "rate_limited", []
    if r.status_code >= 400:
        return latency_ms, False, _parse_error(r), []
    return latency_ms, True, "", r.json().get("matches", [])


async def run_benchmark(
    base_url: str,
    num_queries: int,
    concurrency: int,
    api_key: str | None = None,
    debug: bool = False,
):
    bench_start = time.perf_counter()
    tenant = "bench"
    collection = f"lat_{int(time.time())}"
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

    async with httpx.AsyncClient(
        base_url=base_url, timeout=30.0, headers=headers
    ) as client:
        await print_run_header(client, base_url, "search_latency")
        print(f"Setting up collection {tenant}/{collection}...")
        try:
            await setup_collection(client, tenant, collection)
        except RuntimeError as exc:
            print(f"Setup failed: {exc}")
            if debug:
                print(traceback.format_exc())
            return []
        print(f"Indexed {len(SAMPLE_DOCS)} documents.")

        print(f"Running {num_queries} queries with concurrency={concurrency}...")
        latencies: list[float] = []
        errors: list[str] = []
        rate_limited: int = 0
        samples: dict[str, list[dict]] = {}  # query → hits, up to 3 unique
        semaphore = asyncio.Semaphore(concurrency)

        async def bounded_search(query: str) -> tuple[float, bool | None, str, list[dict]]:
            async with semaphore:
                return await search(client, tenant, collection, query)

        query_list = [QUERIES[i % len(QUERIES)] for i in range(num_queries)]
        tasks = [bounded_search(q) for q in query_list]

        results = await asyncio.gather(*tasks)
        for (latency_ms, ok, detail, hits), query in zip(results, query_list):
            if ok is True:
                latencies.append(latency_ms)
                if len(samples) < 3 and query not in samples and hits:
                    samples[query] = hits
            elif ok is None:
                rate_limited += 1
            else:
                errors.append(detail)

        # Report results
        elapsed = time.perf_counter() - bench_start
        total = len(results)
        ok_count = len(latencies)
        err_count = len(errors)

        print()
        print("=" * 94)
        print(f"  SEARCH LATENCY RESULTS  ({elapsed:.1f}s elapsed)")
        print("=" * 94)
        print(f"  Total queries  : {total}")
        print(f"  Throughput     : {total / elapsed:.1f} ops/s")
        print(f"  Concurrency    : {concurrency}")
        if rate_limited:
            print(
                f"  Rate limited   : {rate_limited} "
                f"({100 * rate_limited / max(total, 1):.1f}%) "
                f"— raise tenants.default_max_concurrent or use auth.mode=none"
            )
        print(f"  Errors         : {err_count} ({100 * err_count / max(total, 1):.1f}%)")
        print()

        header = (
            f"{'Operation':<22} {'Count':>6} {'OK':>6} {'Err (%)':>11} "
            f"{'Min':>9} {'p50':>9} {'p95':>9} {'p99':>9} {'Max':>9}"
        )
        print(header)
        print("-" * len(header))
        if latencies:
            row_count = ok_count + err_count
            err_str = f"{err_count} ({100 * err_count / max(row_count, 1):.1f}%)"
            print(
                f"{'search':<22} {row_count:>6} {ok_count:>6} {err_str:>11} "
                f"{min(latencies):>8.1f}ms "
                f"{percentile(latencies, 50):>8.1f}ms "
                f"{percentile(latencies, 95):>8.1f}ms "
                f"{percentile(latencies, 99):>8.1f}ms "
                f"{max(latencies):>8.1f}ms"
            )
        else:
            print("  No successful queries to report latencies.")
        print("-" * len(header))
        print()

        if samples:
            print("Sample results:")
            for query, hits in samples.items():
                print(f"  q: \"{query}\"")
                for hit in hits[:2]:
                    text = hit.get("text") or ""
                    excerpt = text[:90] + "…" if len(text) > 90 else text
                    print(f"     [{hit.get('id','?')}  {hit.get('score', 0):.3f}]  {excerpt}")
            print()

        if errors:
            print("Sample errors:")
            for detail in errors[:5]:
                print(f"  - {detail}")
            print()

        # Cleanup
        await client.delete(f"/collections/{tenant}/{collection}")
        print(f"\nCleaned up collection {tenant}/{collection}")

        return latencies


def main():
    parser = argparse.ArgumentParser(
        description="PatchVec search latency benchmark"
    )
    parser.add_argument(
        "--url",
        default="http://localhost:8086",
        help="PatchVec base URL",
    )
    parser.add_argument(
        "--queries",
        type=int,
        default=100,
        help="Number of queries to run",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=10,
        help="Concurrent requests",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help=(
            "Bearer token for the 'bench' tenant "
            "(omit when server uses auth.mode=none)"
        ),
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Print stack traces for setup failures",
    )
    args = parser.parse_args()

    asyncio.run(run_benchmark(
        args.url,
        args.queries,
        args.concurrency,
        api_key=args.api_key,
        debug=args.debug,
    ))


if __name__ == "__main__":
    main()
