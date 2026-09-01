# Places & Stories API

An open geospatial API for Malaysian landmarks **and the stories behind them**.

Ask *"what's near me?"* and get places back with their histories — not just a
name and a pin. Generic POI APIs (Google Places, Geoapify) return facts:
coordinates, opening hours, a category. This one returns why a place matters.

```
GET /v1/places/near?lat=5.4141&lon=100.3288&radius_m=2000
```

```json
{
  "query": { "lat": 5.4141, "lon": 100.3288, "radius_m": 2000, "limit": 20 },
  "count": 4,
  "results": [
    {
      "id": "khoo-kongsi",
      "name": "Khoo Kongsi",
      "category": "historic",
      "lat": 5.414265, "lon": 100.337592,
      "city": "George Town", "state": "Penang",
      "sources": { "osm_type": "node", "osm_id": 6832811985, "wikidata_id": "Q6402268" },
      "distance_m": 973.4,
      "story_count": 1,
      "stories": [
        {
          "title": "Khoo Kongsi",
          "body_md": "The Leong San Tong Khoo Kongsi … is the largest Hokkien clanhouse in Malaysia …",
          "attribution": {
            "source_name": "Wikipedia",
            "source_url": "https://en.wikipedia.org/wiki/Khoo_Kongsi",
            "license": "CC BY-SA 4.0",
            "retrieved_at": "2026-09-01"
          },
          "match": { "method": "wikidata", "confidence": 1.0 }
        }
      ]
    }
  ]
}
```

*(Response truncated — the full call returns all four places.)*

This is the backend seed of a self-paced tour-guide app. Right now it is the API
only, and it is deliberately built as a backend/infrastructure showcase:
geospatial querying, a real caching strategy, rate limiting, Docker, CI, and a
documented deploy path.

**Status:** v1 — 57 seed places across 15 Malaysian states and territories, every
one stitched from OpenStreetMap coordinates and a Wikipedia story.
**Live endpoint:** _not deployed yet — see [docs/deploy-aws.md](docs/deploy-aws.md)._

---

## Run it

One command. You need Docker, nothing else.

```bash
git clone https://github.com/myrrym/places-stories-api.git
cd places-stories-api
cp .env.example .env
docker compose up --build
```

That starts PostGIS, Redis and the API; runs the migration; loads every place in
`data/places/`; and serves on <http://localhost:8000>. Interactive docs at
<http://localhost:8000/docs>.

```bash
curl "http://localhost:8000/v1/places/near?lat=3.1478&lon=101.6953&radius_m=2000"
curl "http://localhost:8000/v1/places/stadthuys"
curl "http://localhost:8000/v1/stats"
```

Postgres and Redis are published on **55432** and **56379** rather than their
defaults, so this stack does not collide with anything already running on your
machine. If port 8000 is taken too, set `API_PORT` in `.env`.

## Endpoints

| Method | Path | What it does |
|---|---|---|
| `GET` | `/health` | Liveness probe. Never rate limited. |
| `GET` | `/v1/places/near` | Proximity search. `lat`, `lon`, `radius_m`, `limit`. |
| `GET` | `/v1/places` | Browse. Optional `category`, `limit`, `offset`. |
| `GET` | `/v1/places/{id}` | One place with all its stories. |
| `GET` | `/v1/places/{id}/stories` | Just the stories. |
| `GET` | `/v1/stats` | Live cache hit rate and dataset size. |

Categories: `historic`, `religious`, `museum`, `natural`, `market`, `landmark`.

---

## Architecture

```
                       ┌──────────────────────────────────────────┐
   client              │            SERVING PATH                  │
   (mobile / web)      │                                          │
        │              │  ┌────────────────────────────────────┐  │
        └─── HTTP ────────▶│ FastAPI                            │  │
                       │  │  rate limit (Redis, per IP)        │  │
                       │  │  api/v1  ──▶ services  ──▶ repo    │  │
                       │  └──────┬───────────────┬─────────────┘  │
                       │         │               │                │
                       │    ┌────▼─────┐    ┌────▼──────────────┐ │
                       │    │  Redis   │    │ Postgres + PostGIS│ │
                       │    │ tier A   │    │  places(geom)     │ │
                       │    │  place   │    │   GiST index      │ │
                       │    │ tier B   │    │  stories          │ │
                       │    │  near    │    │   + attribution   │ │
                       │    └──────────┘    └────────▲──────────┘ │
                       └─────────────────────────────┼────────────┘
                                                     │ batch write
   ┌─────────────────────────────────────────────────┼────────────┐
   │        INGESTION (offline, never in a request)  │            │
   │                                                 │            │
   │  OpenStreetMap ─┐                               │            │
   │   (Overpass)    ├──▶ match.py ──▶ data/places/*.yaml ────────┤
   │  Wikidata P625 ─┤    fail-closed      (reviewed, committed)  │
   │  Wikipedia ─────┘    confidence                              │
   └──────────────────────────────────────────────────────────────┘
```

The boundaries are enforced, not aspirational:

- `app/` never imports `ingestion/`, and `ingestion/` never imports `app/api/`.
- **Every** line of PostGIS SQL lives in `app/db/repositories/places.py`.
- **Every** cache key is built in `app/cache/keys.py`.

```
app/
├── api/v1/          HTTP layer: validation, status codes, response models
├── services/        cache-aside orchestration
├── db/repositories/ the only place ST_DWithin appears
├── cache/           Redis client, key quantisation, hit/miss counters
├── middleware/      per-IP rate limiting
└── geo.py           geohash + haversine (pure functions, no I/O)
ingestion/
├── sources/         OpenStreetMap, Wikidata, Wikipedia clients
├── match.py         POI ↔ article matching, fail-closed
├── build_seed.py    one-off stitch → data/places/*.yaml
└── load.py          data/places/*.yaml → database (idempotent)
data/places/         the contribution surface: one YAML file per place
```

---

## Geospatial: why PostGIS, not geohashing

Proximity search runs on a `geography(Point, 4326)` column with a GiST index:

```sql
SELECT id FROM places
WHERE ST_DWithin(geom, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography, :radius)
ORDER BY ST_Distance(geom, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography);
```

Geohashing was the obvious alternative. It lost on three counts:

**Correctness.** A `geography` column gives true spherical distance in metres.
No projection choice, no bounding-box approximation, no "close enough near the
equator". Geohash cells are rectangles in an unprojected space, so a fixed
prefix length means a different real-world radius at different latitudes.

**Boundary handling.** A geohash lookup is not one lookup. Two points 10 m apart
can sit in different cells, so a correct radius query must expand to the cell
*and its eight neighbours*, union the results, then re-filter by exact distance
anyway — reimplementing in application code what `ST_DWithin` does in one
index-assisted operator. More code, more places to be subtly wrong.

**Ranking.** "Nearest first" is free with PostGIS and is not expressible in a
geohash prefix at all; you get an unordered candidate set and sort it yourself.

Honest caveat: at 57 places, **any** approach is fast — a sequential scan would
be sub-millisecond. The GiST index is not doing meaningful work at this scale.
The choice is about correctness and headroom, not about current throughput, and
the README would be lying if it claimed a benchmark win here.

**When geohashing becomes the right answer:** when there is no relational
database in the path (a pure Redis `GEOSEARCH` or DynamoDB design), or at a scale
where you shard by geographic prefix across nodes. Redis' own geo commands are
geohash-backed — which is fine for a *cache*, and wrong for a source of truth.

---

## Caching: two tiers, and the continuous-coordinate problem

The hard part of caching a proximity API is that coordinates are continuous.
Hashing raw floats means a user who walks ten metres generates a brand-new cache
key, and the hit rate is permanently zero. Quantisation fixes that — but naive
quantisation makes results wrong, because it silently answers a question the
caller did not ask.

### Tier A — per place

`place:v1:{id}` → the full serialised place with its stories. TTL 24 h, deleted
explicitly whenever ingestion writes that place. Place records change rarely and
are read constantly, so this tier does most of the work.

### Tier B — per proximity query

`near:v1:{geohash}:{radius_bucket}` → **place IDs and coordinates only**, TTL 10
minutes. Two quantisations build the key:

1. The query point is snapped to a **geohash cell** (precision 6, roughly
   1.2 km × 0.6 km).
2. The radius is snapped **up** to the next bucket: 500 / 1000 / 2000 / 5000 /
   10 000 / 25 000 m.

### Keeping quantised results exact

Snapping the query point moves it, by up to half a cell diagonal. Returning the
cell centre's neighbours as if they were the caller's would be quietly wrong. So:

- The database is queried **from the cell centre** with
  `radius_bucket + cell_half_diagonal` metres.
- For any real point *p* inside the cell, `distance(p, centre) ≤ half_diagonal`.
  So any place within `radius_bucket` of *p* is within
  `radius_bucket + half_diagonal` of the centre. **The cached set is provably a
  superset.**
- The service layer then re-filters that superset with an exact haversine
  distance from the caller's true coordinates and their true radius, sorts, and
  applies the limit.

The cache is approximate. **The answer is not.** `tests/test_cache.py` pins this
down: a place 900 m away is inside the padded superset of a 500 m query and must
still be excluded from the response.

Storing only IDs in Tier B is the other half of the design. Story text lives in
exactly one tier, so a place edit invalidates one key instead of an unknowable
set of geo keys, and geo keys can be left to expire.

### Measured hit rate

`scripts/loadtest.py` against the 57-place seed set, 500 requests per run:

| Pattern | Proximity tier | Place tier | p50 | p95 |
|---|---|---|---|---|
| Clustered (users near city centres, ±1.5 km jitter) | **73.8 %** | **98.0 %** | 1.9 ms | 3.7 ms |
| Uniform random across Malaysia | 0.0 % | — | 2.0 ms | 3.1 ms |

Both numbers are in the table on purpose. Real users cluster in cities, which is
exactly the pattern quantisation is built for. Uniformly random coordinates
across the whole country almost never revisit a cell, so the hit rate collapses
to zero — quoting only the 73.8 % would be marketing, not measurement.

Reproduce it yourself:

```bash
docker compose up -d
python scripts/loadtest.py --base-url http://localhost:8000 --requests 500
curl http://localhost:8000/v1/stats
```

Counters live in Redis (`metrics:cache`), so `/v1/stats` reports real traffic,
not a synthetic benchmark.

### Invalidation

- Tier A: explicit `DEL` after ingestion writes a place.
- Tier B: TTL only. The keys hold IDs, so a stale one costs one extra hydration
  and can never serve stale story text.
- Everything: bump `CACHE_VERSION` to invalidate every key at once.

---

## Rate limiting

Public API, so per-IP limits are on by default: **60 requests/minute, 1000/day**.
Fixed-window counters in Redis, incremented by a Lua script so the increment and
its expiry are atomic across replicas.

- Over the limit → `429` with `Retry-After` and `X-RateLimit-*` headers.
- `X-Forwarded-For` is believed **only** when the immediate peer is inside a
  configured trusted CIDR (`TRUSTED_PROXY_CIDRS`). Otherwise anyone could spoof
  the header and walk past the limiter.
- The limiter **fails open**: if Redis is unreachable the request is served. A
  cache outage should not take the public API down with it.
- `/health` is never limited.

Fixed windows allow up to a 2× burst across a window boundary. That is an
accepted v1 trade; a sliding-window log is the documented upgrade.

---

## Content ingestion: coordinates from OSM, stories from Wikipedia

Coordinates for Malaysia are already open data — hand-authoring them would be
wasted work, and scraping them would be rude. The value added here is the
**story layer**. So the dataset is a two-source stitch:

**Base layer (where).** OpenStreetMap via Overpass, asking specifically for
elements that carry a `wikidata` tag. Falls back to Wikidata's `P625` coordinate
property when Overpass has no matching element. 55 of the 57 seed places are
OSM-backed; the rest carry Wikidata coordinates and a null `osm_id`.

**Story layer (why it matters).** The Wikipedia lead-section extract, stored with
its article URL, licence and retrieval date.

**Ingestion is a batch job and never touches the request path.** The stitched
result is committed to `data/places/*.yaml` and loaded into our own database.
The API never calls OpenStreetMap or Wikipedia.

### Matching, and why it is allowed to fail

An OSM point and a Wikipedia article are not the same object. Forcing a link is
worse than having none — a wrong story attached to a real landmark destroys the
only thing this API is for. So matching is **fail-closed**, in order:

1. **Explicit link, confidence 1.0.** The OSM element carries a `wikidata` or
   `wikipedia` tag, or the curated seed entry names the article. An editor
   already asserted the link; no guessing involved. All 57 seed places matched
   at this tier.
2. **Geosearch + name similarity, confidence = similarity.** Ask Wikipedia for
   articles with coordinates within 500 m, then compare normalised names
   (order-insensitive, disambiguators stripped, generic words like *masjid* and
   *muzium* discounted so two unrelated mosques in one town cannot match on the
   shared word). Accepted only at similarity **≥ 0.85** *and* distance ≤ 500 m.
3. **No match → no story.** The place ships with an empty `stories` list and the
   API serves it as a place with no story yet. That is a valid state, and a good
   first contribution for someone.

Four curated entries were dropped during the seed build because no English
Wikipedia article exists for them. The pipeline reported them and moved on;
nothing was invented to fill the gap.

Every story row stores `source_name`, `source_url`, `license`, `retrieved_at`,
`match_method` and `match_confidence`, and all of it is in the API response.
Attribution is a column, not a footnote — see [DATA_LICENSE.md](DATA_LICENSE.md).

### Rebuilding the seed

```bash
python -m ingestion.build_seed              # re-fetch and rewrite data/places/
python -m ingestion.load --dry-run          # validate without writing
python -m ingestion.load                    # upsert into the database
```

---

## Contributing

**Add a place by opening a pull request against `data/places/`.** One YAML file
per place, validated in CI against `data/schema/place.schema.json`. No account,
no submission endpoint, no moderation queue — GitHub review *is* the moderation.
See [CONTRIBUTING.md](CONTRIBUTING.md).

---

## Tests

```bash
docker compose up -d db cache
make test
```

The geospatial and cache behaviour under test *is* the behaviour of PostGIS and
Redis, so these are integration tests against real services — mocking them would
only test the mocks. The data-file validation tests need neither, so a
contributor gets an answer in seconds.

CI runs four jobs on every push and pull request: lint (ruff), place-data
validation, tests against live PostGIS + Redis (including `alembic check`, which
fails if the migrations and the ORM models have drifted apart), and a Docker
image build.

---

## Deploying

[docs/deploy-aws.md](docs/deploy-aws.md) covers both the v1 deploy (a single
EC2 instance running the same compose file, ~US$12/month) and the managed
production architecture it grows into (ECS Fargate + RDS PostGIS +
ElastiCache), with an honest note on why v1 is not on the second one yet.

## Roadmap

- **v1 (here).** 57 seed places, full API, cache, rate limiting, CI, one-command
  local run.
- **Next.** Automated bulk ingestion from the HDX *Malaysia Points of Interest*
  OSM export with incremental refresh; Wikivoyage as a second story source;
  Malay-language stories.
- **Later.** A moderated submission endpoint (needs auth, spam defence and a
  review queue — a separate product from this one); sliding-window rate limits.

## Licence

Code: Apache-2.0 (`LICENSE`). Data: **not** Apache-2.0 — OpenStreetMap is ODbL,
Wikipedia is CC BY-SA 4.0, Wikidata is CC0. Read
[DATA_LICENSE.md](DATA_LICENSE.md) before redistributing anything from
`data/places/`.
