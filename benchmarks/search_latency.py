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
import statistics
import time
import traceback

try:
    import httpx
except ImportError:
    raise SystemExit("httpx required: pip install httpx")

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
) -> tuple[float, bool | None, str]:
    """Perform a search and return latency, ok flag, and detail.

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
        return latency_ms, None, "rate_limited"
    if r.status_code >= 400:
        return latency_ms, False, _parse_error(r)
    return latency_ms, True, ""


async def run_benchmark(
    base_url: str,
    num_queries: int,
    concurrency: int,
    api_key: str | None = None,
    debug: bool = False,
):
    print("==> Benchmark: search_latency")
    bench_start = time.perf_counter()
    tenant = "bench"
    collection = f"lat_{int(time.time())}"
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

    async with httpx.AsyncClient(
        base_url=base_url, timeout=30.0, headers=headers
    ) as client:
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
        semaphore = asyncio.Semaphore(concurrency)

        async def bounded_search(query: str) -> tuple[float, bool | None, str]:
            async with semaphore:
                return await search(client, tenant, collection, query)

        tasks = []
        for i in range(num_queries):
            query = QUERIES[i % len(QUERIES)]
            tasks.append(bounded_search(query))

        results = await asyncio.gather(*tasks)
        for latency_ms, ok, detail in results:
            if ok is True:
                latencies.append(latency_ms)
            elif ok is None:
                rate_limited += 1
            else:
                errors.append(detail)

        # Report results
        print("\n--- Results ---")
        elapsed = time.perf_counter() - bench_start
        print(f"Total queries: {len(results)}")
        print(f"Concurrency:   {concurrency}")
        print(f"Elapsed:       {elapsed:.1f}s")
        if rate_limited:
            print(
                f"Rate limited:  {rate_limited} "
                f"({100 * rate_limited / max(len(results), 1):.1f}%) "
                f"— raise tenants.default_max_concurrent or use auth.mode=none"
            )
        err_rate = 100 * len(errors) / max(len(results), 1)
        print(f"Errors:        {len(errors)} ({err_rate:.1f}%)")
        if latencies:
            print(f"Min:           {min(latencies):.2f} ms")
            print(f"Max:           {max(latencies):.2f} ms")
            print(f"Mean:          {statistics.mean(latencies):.2f} ms")
            print(f"Median (p50):  {percentile(latencies, 50):.2f} ms")
            print(f"p95:           {percentile(latencies, 95):.2f} ms")
            print(f"p99:           {percentile(latencies, 99):.2f} ms")
        else:
            print("No successful queries to report latencies.")
        if errors:
            print("Sample errors:")
            for detail in errors[:5]:
                print(f"  - {detail}")

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
