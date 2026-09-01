# Data licensing and attribution

The code in this repository is Apache-2.0 (see `LICENSE`). **The data is not.**
It comes from three upstream projects with three different licences, and those
licences travel with it.

| Layer | Source | Licence | What we take |
|---|---|---|---|
| Coordinates, OSM identifiers | [OpenStreetMap](https://www.openstreetmap.org/) | [ODbL 1.0](https://opendatacommons.org/licenses/odbl/1-0/) | Element coordinates, `osm_type`/`osm_id`, local-language names |
| Coordinates (fallback), entity identifiers | [Wikidata](https://www.wikidata.org/) | [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/) | `P625` coordinate location, Q-identifiers |
| Story text | [Wikipedia](https://en.wikipedia.org/) | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/) | Lead-section extract of an article |

## What that means in practice

**Attribution is stored per record, not bolted on.** Every row in the `stories`
table carries `source_name`, `source_url`, `license` and `retrieved_at`, and
every API response includes them under `attribution`. A client that renders a
story has everything it needs to credit the source without a second lookup.

**Share-alike applies downstream.** ODbL is share-alike for derived databases,
and CC BY-SA is share-alike for the text. If you redistribute this dataset or a
derivative of it, you must carry these terms forward. Attribute
OpenStreetMap contributors for the geometry and Wikipedia for the prose.

**We store rather than proxy.** Ingestion is a batch job. The serving API never
calls OpenStreetMap or Wikipedia in the request path, so upstream never absorbs
our traffic. The batch job identifies itself with a real `User-Agent`, makes one
request at a time with a delay between calls, and backs off on HTTP 429.

## If you are an upstream maintainer

If any use here is out of line with your project's terms, open an issue and it
will be corrected or removed.
