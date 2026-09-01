"""Matching a POI to a Wikipedia article -- the hard part of the stitch.

An OSM point and a Wikipedia article are not the same object, and forcing a
link is worse than having none: a wrong story attached to a real landmark
destroys the only thing this API is for. So matching is **fail-closed**.

Strategy, in order:

1. **Explicit link (confidence 1.0).** The OSM element carries a
   ``wikipedia`` or ``wikidata`` tag, or the curated seed entry names the
   article. No guessing involved -- an editor already asserted the link.
2. **Geosearch + name similarity (confidence = similarity).** Ask Wikipedia
   for articles with coordinates within ``GEOSEARCH_RADIUS_M`` of the POI,
   then compare normalised names. Accept only when the name similarity is at
   or above ``MIN_NAME_SIMILARITY`` *and* the article sits within
   ``MAX_MATCH_DISTANCE_M``.
3. **No match.** The place is written out with an empty ``stories`` list and
   the API serves it as a place with no story yet. That is a valid state and
   a good first contribution for someone.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher

from ingestion.sources.wikipedia import Article, WikipediaClient

logger = logging.getLogger(__name__)

GEOSEARCH_RADIUS_M = 500
MAX_MATCH_DISTANCE_M = 500.0
MIN_NAME_SIMILARITY = 0.85

# Words that carry no discriminating power in Malaysian place names -- every
# other mosque is a "masjid". Stripping them stops two unrelated mosques in
# the same town from scoring as a match on the shared word alone.
_STOPWORDS = {
    "the",
    "of",
    "and",
    "dan",
    "di",
    "sri",
    "seri",
    "masjid",
    "mosque",
    "kuil",
    "temple",
    "muzium",
    "museum",
    "kota",
    "fort",
    "pasar",
    "market",
    "jalan",
    "lorong",
    "taman",
}


@dataclass(frozen=True)
class Match:
    article: Article
    method: str  # "wikidata" | "geosearch"
    confidence: float


def normalise(name: str) -> str:
    decomposed = unicodedata.normalize("NFKD", name)
    ascii_only = "".join(c for c in decomposed if not unicodedata.combining(c))
    cleaned = re.sub(r"[^a-z0-9\s]", " ", ascii_only.lower())
    return re.sub(r"\s+", " ", cleaned).strip()


def _significant_tokens(name: str) -> list[str]:
    tokens = [t for t in normalise(name).split() if t not in _STOPWORDS]
    return tokens or normalise(name).split()


def name_similarity(a: str, b: str) -> float:
    """Order-insensitive similarity in ``[0, 1]``.

    Tokens are sorted before comparison so "Kongsi Khoo" scores the same as
    "Khoo Kongsi". Parenthetical Wikipedia disambiguators are dropped first,
    since "Stadthuys (Malacca)" is the same subject as "Stadthuys".
    """
    a_clean = re.sub(r"\s*\([^)]*\)", "", a)
    b_clean = re.sub(r"\s*\([^)]*\)", "", b)
    a_key = " ".join(sorted(_significant_tokens(a_clean)))
    b_key = " ".join(sorted(_significant_tokens(b_clean)))
    if not a_key or not b_key:
        return 0.0
    return SequenceMatcher(None, a_key, b_key).ratio()


def match_article(
    client: WikipediaClient,
    name: str,
    lat: float,
    lon: float,
    explicit_title: str | None = None,
) -> Match | None:
    """Find the article for a POI, or None if nothing clears the bar."""
    if explicit_title:
        article = client.fetch_article(explicit_title)
        if article is not None:
            return Match(article=article, method="wikidata", confidence=1.0)
        logger.info("explicit title %r has no article; falling back to geosearch", explicit_title)

    candidates = client.geosearch(lat, lon, radius_m=GEOSEARCH_RADIUS_M)
    best: tuple[float, object] | None = None
    for candidate in candidates:
        if candidate.distance_m > MAX_MATCH_DISTANCE_M:
            continue
        score = name_similarity(name, candidate.title)
        if best is None or score > best[0]:
            best = (score, candidate)

    if best is None or best[0] < MIN_NAME_SIMILARITY:
        logger.info(
            "no confident match for %r (best score %.2f); leaving it story-less",
            name,
            best[0] if best else 0.0,
        )
        return None

    score, candidate = best
    article = client.fetch_article(candidate.title)
    if article is None:
        return None
    return Match(article=article, method="geosearch", confidence=round(score, 2))
