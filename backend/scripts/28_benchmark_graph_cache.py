import asyncio
import time
import numpy as np
from nexafreight.database import get_db_session
from nexafreight.services.planner import MultimodalPlanner, GraphCache

async def main():
    async for session in get_db_session():
        # Dry run to warm up
        planner = MultimodalPlanner()
        await planner.plan(session, "ship-warmup", "INJNP", "NLRTM", persist=False)

        N = 200
        
        # Cache OFF (fresh instance forces DB load every time)
        print(f"Benchmarking Cache OFF (N={N})...")
        t_off = []
        for i in range(N):
            cache = GraphCache()
            planner = MultimodalPlanner(cache=cache)
            t0 = time.monotonic()
            await planner.plan(session, f"ship-off-{i}", "INJNP", "NLRTM", persist=False)
            t_off.append(time.monotonic() - t0)
            
        # Cache ON
        print(f"Benchmarking Cache ON (N={N})...")
        shared_cache = GraphCache()
        planner_on = MultimodalPlanner(cache=shared_cache)
        await planner_on.plan(session, "ship-warmup2", "INJNP", "NLRTM", persist=False)
        
        t_on = []
        for i in range(N):
            t0 = time.monotonic()
            await planner_on.plan(session, f"ship-on-{i}", "INJNP", "NLRTM", persist=False)
            t_on.append(time.monotonic() - t0)

        p50_off = np.percentile(t_off, 50)
        p95_off = np.percentile(t_off, 95)
        p50_on = np.percentile(t_on, 50)
        p95_on = np.percentile(t_on, 95)
        
        print("\n=== Benchmark Results ===")
        print(f"Cache OFF: p50={p50_off*1000:.1f}ms, p95={p95_off*1000:.1f}ms")
        print(f"Cache ON:  p50={p50_on*1000:.1f}ms, p95={p95_on*1000:.1f}ms")
        print(f"Delta: {p95_off/p95_on:.1f}x p95 improvement")
        break

if __name__ == "__main__":
    asyncio.run(main())
