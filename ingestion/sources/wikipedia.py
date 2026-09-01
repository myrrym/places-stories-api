"""Story layer: narrative text from Wikipedia.

Wikipedia article text is CC BY-SA 4.0. Every extract we store keeps its
article URL, licence and retrieval date so attribution travels with the
data all the way to the API response.

Upstream etiquette, because being a good open-data citizen is part of the
point: identify with a real User-Agent, one request at a time, a small
delay between calls, and back off on 429. We fetch once at build time and
store the result -- the serving API never touches Wikipedia.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

API = "https://en.wikipedia.org/w/api.php"
LICENSE = "CC BY-SA 4.0"
USER_AGENT = "places-stories-api/0.1 (https://github.com/myrrym/places-stories-api; batch ingester)"

# Wikipedia asks unauthenticated bots to stay gentle. 200 ms between calls is
# comfortably inside their guidance for a few dozen requests.
REQUEST_DELAY_S = 0.2


@dataclass(frozen=True)
class Article:
    title: str
    url: str
    extract: str
    # Wikipedia also knows where the subject is and which Wikidata item it
    # is, which is how the seed build gets coordinates without anyone
    # hand-typing a lat/lon.
    lat: float | None = None
    lon: float | None = None
    wikidata_id: str | None = None


@dataclass(frozen=True)
class GeoResult:
    title: str
    lat: float
    lon: float
    distance_m: float


class WikipediaClient:
    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(
            headers={"User-Agent": USER_AGENT}, timeout=30.0, follow_redirects=True
        )
        # The seed build asks for the same article twice (once to resolve
        # coordinates, once to match a story). Memoise so upstream sees one hit.
        self._articles: dict[str, Article | None] = {}

    def _get(self, params: dict) -> dict:
        for attempt in range(4):
            response = self._client.get(API, params={**params, "format": "json"})
            if response.status_code == 429:
                wait = int(response.headers.get("Retry-After", 2 ** (attempt + 1)))
                logger.warning("Wikipedia rate limited, sleeping %ss", wait)
                time.sleep(wait)
                continue
            response.raise_for_status()
            time.sleep(REQUEST_DELAY_S)
            return response.json()
        raise RuntimeError("Wikipedia kept rate limiting us; stop and retry later")

    def fetch_article(self, title: str) -> Article | None:
        """Lead-section plain-text extract for an article title.

        Returns None for a missing article -- a miss is a normal outcome and
        leaves the place story-less rather than guessing.
        """
        if title in self._articles:
            return self._articles[title]
        article = self._fetch_article_uncached(title)
        self._articles[title] = article
        return article

    def _fetch_article_uncached(self, title: str) -> Article | None:
        data = self._get(
            {
                "action": "query",
                "prop": "extracts|info|coordinates|pageprops",
                "exintro": 1,
                "explaintext": 1,
                "redirects": 1,
                "inprop": "url",
                "ppprop": "wikibase_item",
                "titles": title,
            }
        )
        pages = data.get("query", {}).get("pages", {})
        for page_id, page in pages.items():
            if page_id == "-1" or "missing" in page:
                logger.info("no Wikipedia article for %r", title)
                return None
            extract = (page.get("extract") or "").strip()
            if not extract:
                return None
            coords = (page.get("coordinates") or [{}])[0]
            return Article(
                title=page["title"],
                url=page.get("fullurl")
                or f"https://en.wikipedia.org/wiki/{page['title'].replace(' ', '_')}",
                extract=extract,
                lat=coords.get("lat"),
                lon=coords.get("lon"),
                wikidata_id=(page.get("pageprops") or {}).get("wikibase_item"),
            )
        return None

    def geosearch(self, lat: float, lon: float, radius_m: int = 500, limit: int = 10):
        """Articles with coordinates near a point. The fallback matcher."""
        data = self._get(
            {
                "action": "query",
                "list": "geosearch",
                "gscoord": f"{lat}|{lon}",
                "gsradius": radius_m,
                "gslimit": limit,
            }
        )
        return [
            GeoResult(
                title=item["title"],
                lat=item["lat"],
                lon=item["lon"],
                distance_m=float(item.get("dist", 0.0)),
            )
            for item in data.get("query", {}).get("geosearch", [])
        ]

    def close(self) -> None:
        self._client.close()
