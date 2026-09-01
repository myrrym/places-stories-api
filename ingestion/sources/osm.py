"""Base layer: place names and coordinates from OpenStreetMap.

OSM data is ODbL-licensed. Attribution and share-alike obligations are
recorded in DATA_LICENSE.md.

Two ways in, in preference order:

1. **Overpass**, asking for elements that already carry a ``wikidata`` tag.
   Those elements come pre-linked to a Wikidata item, which removes the
   hardest part of matching entirely -- see ``ingestion/match.py``.
2. **Wikidata coordinates (P625)** as a fallback when Overpass is
   unavailable or an element has no usable geometry. Documented, not silent.

Never called from the serving API. This is a batch job.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"

# Identify ourselves. Both APIs ask for this and will throttle anonymous
# clients harder.
USER_AGENT = "places-stories-api/0.1 (https://github.com/myrrym/places-stories-api; batch ingester)"


@dataclass(frozen=True)
class OsmPoi:
    osm_type: str
    osm_id: int
    name: str
    name_local: str | None
    lat: float
    lon: float
    wikidata_id: str | None
    wikipedia_title: str | None
    tags: dict


def _overpass_query(wikidata_ids: list[str]) -> str:
    """Fetch exactly the elements whose ``wikidata`` tag is in our seed list.

    Asking for a narrow set of IDs rather than "every POI in Malaysia" keeps
    us well inside Overpass's fair-use limits for the seed build.
    """
    pattern = "|".join(wikidata_ids)
    return f"""
    [out:json][timeout:180];
    (
      node["wikidata"~"^({pattern})$"];
      way["wikidata"~"^({pattern})$"];
      relation["wikidata"~"^({pattern})$"];
    );
    out center tags;
    """


def fetch_by_wikidata(wikidata_ids: list[str], timeout: float = 200.0) -> dict[str, OsmPoi]:
    """Return ``{wikidata_id: OsmPoi}`` for whatever OSM knows about."""
    if not wikidata_ids:
        return {}

    logger.info("querying Overpass for %d wikidata-tagged elements", len(wikidata_ids))
    response = httpx.post(
        OVERPASS_URL,
        data={"data": _overpass_query(wikidata_ids)},
        headers={"User-Agent": USER_AGENT},
        timeout=timeout,
    )
    response.raise_for_status()

    found: dict[str, OsmPoi] = {}
    for element in response.json().get("elements", []):
        tags = element.get("tags", {})
        qid = tags.get("wikidata")
        if not qid:
            continue
        center = element.get("center") or element
        lat, lon = center.get("lat"), center.get("lon")
        if lat is None or lon is None:
            continue
        # Prefer nodes over ways over relations when OSM has several.
        if qid in found and element["type"] != "node":
            continue
        found[qid] = OsmPoi(
            osm_type=element["type"],
            osm_id=int(element["id"]),
            name=tags.get("name:en") or tags.get("name") or "",
            name_local=tags.get("name:ms") or tags.get("name:zh"),
            lat=float(lat),
            lon=float(lon),
            wikidata_id=qid,
            wikipedia_title=_strip_lang_prefix(tags.get("wikipedia")),
            tags=tags,
        )

    logger.info("Overpass returned %d/%d", len(found), len(wikidata_ids))
    return found


def _strip_lang_prefix(value: str | None) -> str | None:
    """``"en:Khoo Kongsi"`` -> ``"Khoo Kongsi"``."""
    if not value:
        return None
    lang, _, title = value.partition(":")
    return title if lang == "en" and title else None


def fetch_wikidata_coordinates(wikidata_ids: list[str]) -> dict[str, tuple[float, float]]:
    """Fallback coordinates straight from Wikidata's P625 property (CC0)."""
    if not wikidata_ids:
        return {}

    values = " ".join(f"wd:{qid}" for qid in wikidata_ids)
    query = f"""
    SELECT ?item ?coord WHERE {{
      VALUES ?item {{ {values} }}
      ?item wdt:P625 ?coord .
    }}
    """
    response = httpx.get(
        WIKIDATA_SPARQL,
        params={"query": query, "format": "json"},
        headers={"User-Agent": USER_AGENT, "Accept": "application/sparql-results+json"},
        timeout=120.0,
    )
    response.raise_for_status()

    out: dict[str, tuple[float, float]] = {}
    for row in response.json()["results"]["bindings"]:
        qid = row["item"]["value"].rsplit("/", 1)[-1]
        # Point(lon lat)
        raw = row["coord"]["value"].removeprefix("Point(").removesuffix(")")
        lon_s, lat_s = raw.split()
        out[qid] = (float(lat_s), float(lon_s))

    logger.info("Wikidata returned coordinates for %d/%d", len(out), len(wikidata_ids))
    return out
