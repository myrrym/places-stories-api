"""Measure the proximity cache hit rate under a realistic query pattern.

Real users do not query uniformly random coordinates -- they cluster in
cities, and consecutive queries from a walking user land metres apart. This
script reproduces that: pick a city, jitter the point by a few hundred
metres, ask for what is nearby. That is exactly the pattern the geohash
quantisation is designed for, and it is the pattern the README's hit-rate
figure is measured under.

    python scripts/loadtest.py --requests 500 --base-url http://localhost:8080

A uniform-random comparison run is printed alongside, because quoting only
the flattering number would be dishonest.
"""

from __future__ import annotations

import argparse
import random
import statistics
import time

import httpx

# Where people actually are. Roughly the town centres in the seed dataset.
CITIES = [
    ("George Town", 5.4141, 100.3288),
    ("Kuala Lumpur", 3.1478, 101.6953),
    ("Melaka", 2.1944, 102.2486),
    ("Ipoh", 4.5975, 101.0901),
    ("Kuching", 1.5573, 110.3450),
    ("Kota Kinabalu", 5.9804, 116.0735),
    ("Johor Bahru", 1.4655, 103.7578),
    ("Kota Bharu", 6.1248, 102.2381),
]

METRES_PER_DEGREE_LAT = 111_195.0


def jitter(lat: float, lon: float, metres: float) -> tuple[float, float]:
    d_lat = random.uniform(-metres, metres) / METRES_PER_DEGREE_LAT
    d_lon = random.uniform(-metres, metres) / (METRES_PER_DEGREE_LAT * 0.996)
    return lat + d_lat, lon + d_lon


def run(client: httpx.Client, base_url: str, count: int, spread_m: float, uniform: bool):
    latencies = []
    for _ in range(count):
        if uniform:
            lat = random.uniform(1.0, 7.0)
            lon = random.uniform(99.5, 119.5)
        else:
            _, city_lat, city_lon = random.choice(CITIES)
            lat, lon = jitter(city_lat, city_lon, spread_m)

        started = time.perf_counter()
        response = client.get(
            f"{base_url}/v1/places/near",
            params={"lat": lat, "lon": lon, "radius_m": 2000, "limit": 20},
        )
        response.raise_for_status()
        latencies.append((time.perf_counter() - started) * 1000)
    return latencies


def stats(client: httpx.Client, base_url: str) -> dict:
    return client.get(f"{base_url}/v1/stats").json()["cache"]


def report(label: str, latencies: list[float], before: dict, after: dict) -> None:
    def delta(tier: str, kind: str) -> int:
        return after["tiers"][tier][kind] - before["tiers"][tier][kind]

    hits, misses = delta("near", "hits"), delta("near", "misses")
    total = hits + misses
    place_hits, place_misses = delta("place", "hits"), delta("place", "misses")
    place_total = place_hits + place_misses

    print(f"\n{label}")
    print(f"  requests        {len(latencies)}")
    print(f"  proximity tier  {hits} hits / {total} = {hits / total:.1%}" if total else "")
    print(
        f"  place tier      {place_hits} hits / {place_total} = {place_hits / place_total:.1%}"
        if place_total
        else ""
    )
    print(f"  latency p50     {statistics.median(latencies):.1f} ms")
    print(f"  latency p95     {sorted(latencies)[int(len(latencies) * 0.95) - 1]:.1f} ms")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8080")
    parser.add_argument("--requests", type=int, default=500)
    parser.add_argument(
        "--spread-m",
        type=float,
        default=1500,
        help="How far from a city centre a simulated user may be.",
    )
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    random.seed(args.seed)
    with httpx.Client(timeout=30.0) as client:
        for label, uniform in (("clustered (realistic)", False), ("uniform random", True)):
            before = stats(client, args.base_url)
            latencies = run(client, args.base_url, args.requests, args.spread_m, uniform)
            after = stats(client, args.base_url)
            report(label, latencies, before, after)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
