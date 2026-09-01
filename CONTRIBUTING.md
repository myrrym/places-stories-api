# Contributing

The fastest way to help is to **add a place, or add a story to a place that has
none.** No account to create, no submission form, no moderation queue — a pull
request against `data/places/` is the whole process.

## Add a place

1. Create `data/places/<id>.yaml`. The filename must match the `id` field.
2. Fill it in (template below).
3. Validate locally:
   ```bash
   pip install pyyaml jsonschema pytest
   pytest tests/test_data_files.py -q
   ```
4. Open a pull request. CI validates the file against
   `data/schema/place.schema.json` on every push.

```yaml
id: kampung-kling-mosque          # lowercase slug, matches the filename
name: Kampung Kling Mosque
name_local: Masjid Kampung Kling  # optional; omit if same as `name`
category: religious               # historic | religious | museum | natural | market | landmark
lat: 2.195278
lon: 102.247222
address: null
city: Melaka
state: Melaka
osm_type: way                     # optional, from OpenStreetMap
osm_id: 123456789
wikidata_id: Q1234567             # optional
wikipedia_title: Kampung Kling Mosque
stories:
  - title: Kampung Kling Mosque
    body_md: |
      The prose. Markdown is fine.
    lang: en
    source_name: Wikipedia
    source_url: https://en.wikipedia.org/wiki/Kampung_Kling_Mosque
    license: CC BY-SA 4.0
    retrieved_at: 2026-09-01
    match_method: manual          # wikidata | geosearch | manual
    match_confidence: 1.0
```

### Or let the pipeline do it

If the place has an English Wikipedia article, add one line to
`ingestion/seed_places.yaml` and run the builder — it resolves the coordinates
from OpenStreetMap and Wikidata and fetches the story for you:

```bash
python -m ingestion.build_seed --only <your-id>
```

Then review the generated file before committing it. The pipeline is a drafting
tool, not an authority.

## Rules for stories

**Attribution is mandatory.** Every story needs `source_name`, `source_url` and
`license`. A pull request without them will not be merged. See
[DATA_LICENSE.md](DATA_LICENSE.md) for what the upstream licences require.

**Only open-licensed text.** Wikipedia (CC BY-SA 4.0), Wikivoyage, government
open data, or your own original writing. Not travel blogs, not guidebooks, not
anything you found on a tourism website. If you cannot name the licence, it does
not go in.

**Use `match_method: manual` for anything you wrote or verified yourself**, and
be honest with `match_confidence`. A wrong story on a real landmark is worse
than no story — an empty `stories: []` is a perfectly good contribution, and a
place waiting for its story is a useful thing for the next person to pick up.

**Coordinates:** point at the place itself, not the car park or the town centre.
Six decimal places is plenty. The `lat`/`lon` order in a lat/lon swap is the
classic mistake; the test suite fences the whole dataset to Malaysia's bounding
box, so a swap will fail CI rather than reach the API.

## Code changes

```bash
cp .env.example .env
docker compose up -d db cache
pip install -e ".[dev]"
make test
make lint
```

The layering is enforced and worth preserving:

- All PostGIS SQL belongs in `app/db/repositories/places.py`. Nowhere else.
- All cache keys are built in `app/cache/keys.py`. Nowhere else.
- `app/` must not import `ingestion/`; `ingestion/` must not import `app/api/`.
- New behaviour needs a test. Geospatial and cache tests run against real
  PostGIS and Redis, not mocks.

Run `make fmt` before opening a pull request.

## Reporting a wrong story

Open an issue with the place `id` and what is wrong. A story attached to the
wrong place is a bug of the highest priority here — say so in the title and it
will be pulled straight away.
