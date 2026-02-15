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

try:
    import httpx
except ImportError:
    raise SystemExit("httpx required: pip install httpx")

SAMPLE_DOCS = [
    ("doc1", "Machine learning is a subset of artificial intelligence that enables systems to learn from data."),
    ("doc2", "Natural language processing helps computers understand human language and text."),
    ("doc3", "Deep learning uses neural networks with many layers to model complex patterns."),
    ("doc4", "Vector databases store embeddings for efficient similarity search operations."),
    ("doc5", "Semantic search finds results based on meaning rather than exact keyword matches."),
    ("doc6", "Transformers revolutionized NLP with attention mechanisms and parallel processing."),
    ("doc7", "Embeddings represent text as dense vectors in high-dimensional space."),
    ("doc8", "Retrieval augmented generation combines search with language model outputs."),
    ("doc9", "Cosine similarity measures the angle between two vectors for comparison."),
    ("doc10", "Fine-tuning adapts pre-trained models to specific domains and tasks."),
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


async def setup_collection(client: httpx.AsyncClient, tenant: str, collection: str):
    """Create collection and index sample documents."""
    await client.post(f"/collections/{tenant}/{collection}")
    for docid, text in SAMPLE_DOCS:
        await client.post(
            f"/collections/{tenant}/{collection}/documents",
            files={"file": (f"{docid}.txt", text.encode(), "text/plain")},
            data={"docid": docid},
        )


async def search(client: httpx.AsyncClient, tenant: str, collection: str, query: str) -> float:
    """Perform a search and return latency in ms."""
    start = time.perf_counter()
    r = await client.post(
        f"/collections/{tenant}/{collection}/search",
        json={"q": query, "k": 5},
    )
    latency_ms = (time.perf_counter() - start) * 1000
    r.raise_for_status()
    return latency_ms


async def run_benchmark(base_url: str, num_queries: int, concurrency: int):
    tenant = "bench"
    collection = f"lat_{int(time.time())}"

    async with httpx.AsyncClient(base_url=base_url, timeout=30.0) as client:
        print(f"Setting up collection {tenant}/{collection}...")
        await setup_collection(client, tenant, collection)
        print(f"Indexed {len(SAMPLE_DOCS)} documents.")

        print(f"Running {num_queries} queries with concurrency={concurrency}...")
        latencies: list[float] = []
        semaphore = asyncio.Semaphore(concurrency)

        async def bounded_search(query: str) -> float:
            async with semaphore:
                return await search(client, tenant, collection, query)

        tasks = []
        for i in range(num_queries):
            query = QUERIES[i % len(QUERIES)]
            tasks.append(bounded_search(query))

        latencies = await asyncio.gather(*tasks)

        # Report results
        print("\n--- Results ---")
        print(f"Total queries: {len(latencies)}")
        print(f"Concurrency:   {concurrency}")
        print(f"Min:           {min(latencies):.2f} ms")
        print(f"Max:           {max(latencies):.2f} ms")
        print(f"Mean:          {statistics.mean(latencies):.2f} ms")
        print(f"Median (p50):  {percentile(latencies, 50):.2f} ms")
        print(f"p95:           {percentile(latencies, 95):.2f} ms")
        print(f"p99:           {percentile(latencies, 99):.2f} ms")

        # Cleanup
        await client.delete(f"/collections/{tenant}/{collection}")
        print(f"\nCleaned up collection {tenant}/{collection}")

        return latencies


def main():
    parser = argparse.ArgumentParser(description="PatchVec search latency benchmark")
    parser.add_argument("--url", default="http://localhost:8086", help="PatchVec base URL")
    parser.add_argument("--queries", type=int, default=100, help="Number of queries to run")
    parser.add_argument("--concurrency", type=int, default=10, help="Concurrent requests")
    args = parser.parse_args()

    asyncio.run(run_benchmark(args.url, args.queries, args.concurrency))


if __name__ == "__main__":
    main()
