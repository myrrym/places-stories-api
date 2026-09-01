## What this changes

<!-- One or two sentences. -->

## If you added or edited a place

- [ ] The filename matches the `id` field
- [ ] Every story has `source_name`, `source_url` and `license`
- [ ] The story text is open-licensed (Wikipedia, Wikivoyage, government open
      data, or your own writing) — not from a travel blog or guidebook
- [ ] `match_method` honestly reflects how the story was linked, and
      `match_confidence` is not inflated
- [ ] The coordinates point at the place itself, not the car park or the town
      centre
- [ ] `pytest tests/test_data_files.py` passes locally

## If you changed code

- [ ] New PostGIS SQL, if any, is in `app/db/repositories/places.py`
- [ ] New cache keys, if any, are built in `app/cache/keys.py`
- [ ] `make test` and `make lint` pass
- [ ] New behaviour has a test
