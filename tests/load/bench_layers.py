# Copyright (c) 2026 Aashish Ravindran. All rights reserved.
# Use of this software is governed by the Elastic License 2.0
# found in the LICENSE file.

"""Latency Sentinel itself adds, per adapter and per layer.

Identity and knowledge stores are in-memory fakes with zero latency, so the
numbers isolate Sentinel's own work: token verification, scope resolution,
filter building, argument rewriting and the post-filter. Add your store's
round trips on top.

    uv run python -m tests.load.bench_layers --n 2000
"""

import argparse
import asyncio
import statistics
import time
from collections import defaultdict
from collections.abc import Awaitable, Callable

from sentinel_engine.engine import SentinelEngine
from sentinel_engine.telemetry import collect_timings

from sentinel.adapters.agentcore.request_interceptor import intercept_request
from sentinel.adapters.agentcore.response_interceptor import intercept_response
from sentinel.adapters.agentcore.target import secure_search
from tests.support.fakes import DictIdentity, StubBedrockKB
from tests.support.gateway import (
    LAMBDA_TOOL,
    forwarded,
    request_event,
    response_event,
    runtime,
    tool_call,
    tool_result,
)
from tests.support.tokens import bearer

QUERY = "budget opex roadmap overview"
Samples = dict[str, list[float]]


async def bench_engine(n: int) -> Samples:
    engine = SentinelEngine(DictIdentity(), StubBedrockKB.seeded())
    samples: Samples = defaultdict(list)
    for _ in range(n):
        start = time.perf_counter()
        with collect_timings() as timings:
            await engine.secure_search(QUERY, "alice")
        samples["total"].append(time.perf_counter() - start)
        for layer, seconds in timings.items():
            samples[layer].append(seconds)
    return samples


async def bench_gateway(n: int) -> Samples:
    rt = runtime()
    authorization = bearer("alice")
    samples: Samples = defaultdict(list)

    async def timed(layer: str, step: Callable[[], Awaitable[dict]]) -> dict:
        start = time.perf_counter()
        result = await step()
        samples[layer].append(time.perf_counter() - start)
        return result

    for _ in range(n):
        start = time.perf_counter()
        request = tool_call(LAMBDA_TOOL, {"query": QUERY, "n_results": 5})
        out = await timed(
            "request interceptor",
            lambda r=request: intercept_request(request_event(r, authorization), rt),
        )
        rewritten = forwarded(out)
        payload = await timed(
            "lambda target",
            lambda w=rewritten: secure_search(LAMBDA_TOOL, w["params"]["arguments"], rt),
        )
        response = tool_result(request["id"], payload)
        await timed(
            "response interceptor",
            lambda w=rewritten, r=response: intercept_response(
                response_event(w, r, authorization), rt
            ),
        )
        samples["total"].append(time.perf_counter() - start)
    return samples


def report(title: str, samples: Samples) -> None:
    print(f"\n{title}\n| layer | p50 (ms) | p99 (ms) |\n|---|---:|---:|")
    for layer, values in samples.items():
        cuts = statistics.quantiles(values, n=100)
        print(f"| {layer} | {cuts[49] * 1000:.3f} | {cuts[98] * 1000:.3f} |")


async def main(n: int) -> None:
    report("Engine (MCP adapters call this directly)", await bench_engine(n))
    report("AgentCore Gateway path (Lambda target)", await bench_gateway(n))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--n", type=int, default=2000)
    asyncio.run(main(parser.parse_args().n))
