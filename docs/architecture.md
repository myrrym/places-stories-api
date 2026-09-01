# Architecture notes

Detail that would bloat the README. The short version is there; this is the
reasoning underneath it.

## Layering

```
api/v1      HTTP concerns only: query validation, status codes, response models.
            Knows nothing about Redis or SQL.
services    Cache-aside orchestration. Decides what is cached, in which tier,
            and re-filters quantised results back to exactness.
db/repos    The only module allowed to write PostGIS SQL.
cache       Redis client, key construction, hit/miss counters.
geo.py      Pure functions: geohash encode/decode, haversine. No I/O, so the
            quantisation guarantees are testable without any service running.
```

`ingestion/` is a sibling, not a layer. It imports `app.db.models` and
`app.config` to write to the same database, and nothing else from `app/`. It is
never imported *by* `app/`. That is what keeps a slow, network-bound, rate-limited
batch job out of a request path that must answer in milliseconds.

## The data model

Two tables.

```sql
places(
  id            text primary key,       -- slug: readable URLs, natural upsert key
  name, name_local, category,
  geom          geography(Point, 4326), -- GiST indexed
  address, city, state,
  osm_type, osm_id bigint, wikidata_id, -- provenance of the coordinates
  created_at, updated_at
)

stories(
  id, place_id references places on delete cascade, position,
  title, body_md, lang,
  source_name, source_url, license, retrieved_at,   -- attribution, per row
  match_method, match_confidence                     -- how we linked it
)
```

Three decisions worth defending:

**A slug primary key, not a UUID.** Contributors author a YAML file by hand; a
UUID would be one more thing to invent and get wrong. The slug is also the
natural upsert key for a re-runnable loader, and it makes `/v1/places/stadthuys`
readable.

**`geography`, not `geometry`.** `ST_DWithin` on a geography column takes metres
and returns a true spherical distance. On a geometry column in EPSG:4326 the
same call takes *degrees*, which is a distance that changes meaning with
latitude — a classic and silent source of wrong answers.

**`osm_id` is `bigint`.** OpenStreetMap node IDs passed 2³¹ years ago. This was
caught by a real overflow during the seed build, not by foresight.

## Cache tiering, in full

| | Tier A | Tier B |
|---|---|---|
| Key | `place:{ver}:{id}` | `near:{ver}:{geohash}:{bucket}` |
| Value | Full place + stories | Place IDs + coordinates only |
| TTL | 24 h | 10 min |
| Invalidation | Explicit `DEL` on write | TTL only |
| Hit rate (measured) | ~98 % | ~74 % clustered |

Tier B stores IDs rather than payloads for one reason: **invalidation cost**. If
geo keys held story text, editing one place would require finding every geo key
that might contain it — which is every cell within the largest radius bucket, an
unbounded set in practice. Storing IDs means story text exists in exactly one
tier, one key, and a place edit is a single `DEL`.

The cost is an extra Redis round trip (an `MGET` for hydration). At an ~98 %
Tier A hit rate that round trip is cheap, and it is one round trip regardless of
how many places came back.

### The superset guarantee

The property the design rests on, stated precisely:

> Let *C* be a geohash cell, *c* its centre, *h* the maximum distance from *c*
> to any point in *C*, and *r* the radius bucket. For any query point *p* ∈ *C*
> and any place *q* with `distance(p, q) ≤ r`:
>
> `distance(c, q) ≤ distance(c, p) + distance(p, q) ≤ h + r`
>
> So every place a query from *p* should return is inside the circle of radius
> `h + r` around *c* — which is exactly what gets cached.

`tests/test_geo.py::test_half_diagonal_covers_every_point_in_the_cell` asserts
the *h* bound directly; `tests/test_cache.py` asserts that the exact re-filter
puts the answer back where it belongs.

The trade is over-fetching. At precision 6, *h* is roughly 670 m, so a 500 m
query fetches a ~1.17 km circle — around 5× the area. With thousands of places
that is a handful of extra rows. It is the parameter to revisit first if the
dataset grows: raise the precision (smaller cells, less over-fetch, lower hit
rate) or lower it (the reverse). `GEOHASH_PRECISION` is configuration, not a
constant, for exactly this reason.

`NEAR_SUPERSET_CAP` (default 500) bounds the damage if a query lands somewhere
dense. Hitting it is counted at `/v1/stats` as `proximity_supersets_capped` and
surfaces in the response as `query.truncated` — a non-zero count is a signal to
retune, not something to discover from a user complaint.

## What is deliberately absent from v1

Named so that their absence reads as a decision rather than an oversight:

- **No submission endpoint.** A public write path needs authentication, spam
  defence, a moderation queue and an admin UI. That is a second product. Pull
  requests against `data/places/` give contributors a real path today.
- **No authentication or user accounts.** Nothing in the API is per-user.
- **No text search.** `GET /v1/places` filters by category. Full-text search over
  stories wants `tsvector` and a ranking story of its own.
- **No images.** Media hosting is a storage and licensing problem, not an API
  one.
- **No Kubernetes.** Three containers. Compose is the right size.
- **Fixed-window rate limiting, not sliding.** Documented, with its 2× boundary
  burst acknowledged.
