"""Look a place name up and get back real coordinates.

This is a **database lookup, not a generator**. It searches OpenStreetMap's
gazetteer through Nominatim and returns the records it matched, each with the
address and the kind of thing it is. If it does not know a place it returns
nothing. It never produces a coordinate that is not attached to a real record.

That distinction is the whole point. Asking a language model for coordinates
returns a plausible answer, not a looked-up one, and a plausible answer is the
dangerous kind: a hospital placed 1.5 km from where it is still sits in the
right district and the right block, so every check this project runs passes and
the map is quietly wrong. A gazetteer either knows the place or says so.

Nothing here fills a coordinate in by itself. A search returns candidates; a
person picks one. The district and block checks still run afterwards.

Usage policy. Nominatim is free and asks for two things in return: a User-Agent
that identifies the application, and no more than one request a second. Both
are enforced here rather than left to the caller.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

__all__ = [
    "Place",
    "GeocodeError",
    "search",
    "search_best",
    "attribution",
    "provider",
    "PROVIDERS",
]

ENDPOINT = "https://nominatim.openstreetmap.org/search"
GOOGLE_ENDPOINT = "https://places.googleapis.com/v1/places:searchText"
PHOTON_ENDPOINT = "https://photon.komoot.io/api/"

PROVIDERS = ("openstreetmap", "google")


def provider() -> str:
    """Which lookup service to use.

    OpenStreetMap by default: free, no key, nothing to bill. Google Places is
    better on small Indian facilities but needs a billing account and an API
    key, so it is opt-in through the environment:

        set LOCATOR_GEOCODER=google
        set GOOGLE_MAPS_API_KEY=...

    The key is only ever read from the environment, never from a file in the
    repository, so it cannot be committed by accident.
    """
    import os

    choice = os.environ.get("LOCATOR_GEOCODER", "openstreetmap").strip().lower()
    if choice == "google" and os.environ.get("GOOGLE_MAPS_API_KEY"):
        return "google"
    return "openstreetmap"

# Nominatim's policy asks for an identifying User-Agent and at most one request
# per second. Both are honoured here so no caller has to remember to.
USER_AGENT = (
    "cf-locator-maps/0.1 "
    "(Cognizant Foundation India locator map generator; "
    "https://github.com/ramSeraph/indian_admin_boundaries)"
)
MIN_INTERVAL_SECONDS = 1.1
REQUEST_TIMEOUT_SECONDS = 20

_rate_lock = threading.Lock()
_last_request_at = 0.0


class GeocodeError(RuntimeError):
    """Raised when a search could not be carried out.

    Always means "I could not ask", never "the place does not exist". A search
    that ran and found nothing returns an empty list instead.
    """


@dataclass(frozen=True)
class Place:
    """One candidate returned by the gazetteer."""

    name: str
    address: str
    lat: float
    lon: float
    kind: str
    osm_id: str
    importance: float
    inside: bool | None = None  # set by the caller once it tests the district

    def with_inside(self, inside: bool) -> "Place":
        """A copy marked as falling inside, or outside, the target district."""
        return Place(
            name=self.name,
            address=self.address,
            lat=self.lat,
            lon=self.lon,
            kind=self.kind,
            osm_id=self.osm_id,
            importance=self.importance,
            inside=inside,
        )

    def label(self) -> str:
        """A single line a person can read to judge whether this is the right place."""
        kind = self.kind.replace("_", " ")
        flag = "" if self.inside is not False else "OUTSIDE the district  ·  "
        return f"{flag}{self.address}  ·  {kind}  ·  {self.lat:.5f}, {self.lon:.5f}"

    def short_label(self) -> str:
        head = self.address.split(",")[0].strip() or self.name
        return f"{head} ({self.kind.replace('_', ' ')})"


def _respect_rate_limit() -> None:
    """Block until at least one second has passed since the last request."""
    global _last_request_at
    with _rate_lock:
        wait = MIN_INTERVAL_SECONDS - (time.monotonic() - _last_request_at)
        if wait > 0:
            time.sleep(wait)
        _last_request_at = time.monotonic()


def search(
    query: str,
    *,
    limit: int = 5,
    country: str = "in",
    near: str | None = None,
    bbox: tuple[float, float, float, float] | None = None,
    bounded: bool = True,
) -> list[Place]:
    """Search the gazetteer for ``query`` and return what it matched.

    ``bbox`` is ``(min_lon, min_lat, max_lon, max_lat)`` around the area being
    mapped. With ``bounded`` set, results outside it are discarded by the
    service rather than ranked lower, which is the difference between useful
    and useless here: searching "Raghunath Bazar" while mapping Jammu district
    returns temples in Srinagar and a street in Mumbai without it, and nothing
    at all with it - the honest answer, because that name is not in the
    database anywhere near Jammu.

    ``near`` appends place names to the query instead. It is a far weaker
    filter and is kept only for the widened second search, where the caller
    wants matches from beyond the district and labels them as such.

    Returns an empty list when the search ran and matched nothing. Raises
    :class:`GeocodeError` only when the search could not be carried out.
    """
    query = (query or "").strip()
    if not query:
        return []

    if provider() == "google":
        return _search_google(query, limit=limit, near=near, bbox=bbox, bounded=bounded)

    return _search_nominatim(
        query, limit=limit, country=country, near=near, bbox=bbox, bounded=bounded
    )


def _search_nominatim(
    query: str,
    *,
    limit: int = 5,
    country: str = "in",
    near: str | None = None,
    bbox=None,
    bounded: bool = True,
) -> list[Place]:
    """The OpenStreetMap search itself."""
    full_query = f"{query}, {near}".strip(", ") if near else query
    params = {
        "q": full_query,
        "format": "jsonv2",
        "limit": str(max(1, min(int(limit), 20))),
        "addressdetails": "1",
    }
    if country:
        params["countrycodes"] = country
    if bbox:
        min_lon, min_lat, max_lon, max_lat = bbox
        # Nominatim takes two opposite corners, as west,north,east,south.
        params["viewbox"] = f"{min_lon},{max_lat},{max_lon},{min_lat}"
        if bounded:
            params["bounded"] = "1"

    url = f"{ENDPOINT}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})

    _respect_rate_limit()
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            raise GeocodeError(
                "The place-name service is asking us to slow down. Wait a few "
                "seconds and search again, or type the coordinates in by hand."
            ) from exc
        raise GeocodeError(
            f"The place-name service answered with an error ({exc.code}). "
            f"You can still type the coordinates in by hand."
        ) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise GeocodeError(
            "Could not reach the place-name service. Check the internet "
            "connection, or type the coordinates in by hand: right-click the "
            "place in Google Maps and copy the pair of numbers."
        ) from exc
    except ValueError as exc:
        raise GeocodeError(
            "The place-name service sent something unreadable. Try again, or "
            "type the coordinates in by hand."
        ) from exc

    return [place for place in (_to_place(row) for row in payload) if place is not None]


def _to_place(row: dict) -> Place | None:
    try:
        lat = float(row["lat"])
        lon = float(row["lon"])
    except (KeyError, TypeError, ValueError):
        return None

    address = str(row.get("display_name") or "").strip()
    name = str(row.get("name") or "").strip() or address.split(",")[0].strip()
    kind = str(row.get("type") or row.get("category") or "place").strip()

    return Place(
        name=name,
        address=address,
        lat=lat,
        lon=lon,
        kind=kind,
        osm_id=f"{row.get('osm_type', '')}/{row.get('osm_id', '')}",
        importance=float(row.get("importance") or 0.0),
    )


def _search_google(query, *, limit, near, bbox, bounded):
    """The same search against Google Places, when a key is configured.

    Google's coverage of small Indian facilities is better than OpenStreetMap's.
    It is still a lookup, not a generator: it returns places that exist in
    Google's index, or nothing. A bounding box is passed as a location bias, or
    as a hard restriction when ``bounded`` is set.
    """
    import os

    key = os.environ.get("GOOGLE_MAPS_API_KEY", "")
    if not key:
        raise GeocodeError(
            "Google place search is selected but GOOGLE_MAPS_API_KEY is not set. "
            "Set it, or unset LOCATOR_GEOCODER to use OpenStreetMap."
        )

    body: dict = {
        "textQuery": f"{query}, {near}".strip(", ") if near else query,
        "maxResultCount": max(1, min(int(limit), 20)),
        "regionCode": "IN",
    }
    if bbox:
        min_lon, min_lat, max_lon, max_lat = bbox
        area = {
            "rectangle": {
                "low": {"latitude": min_lat, "longitude": min_lon},
                "high": {"latitude": max_lat, "longitude": max_lon},
            }
        }
        body["locationRestriction" if bounded else "locationBias"] = area

    request = urllib.request.Request(
        GOOGLE_ENDPOINT,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-Goog-Api-Key": key,
            "X-Goog-FieldMask": (
                "places.displayName,places.formattedAddress,places.location,places.types"
            ),
            "User-Agent": USER_AGENT,
        },
    )

    _respect_rate_limit()
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "ignore")[:200]
        raise GeocodeError(
            f"Google place search refused the request ({exc.code}). Check the API "
            f"key and that the Places API is enabled. {detail}"
        ) from exc
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise GeocodeError(
            "Could not reach Google place search. Check the internet connection, "
            "or type the coordinates in by hand."
        ) from exc

    places = []
    for row in payload.get("places", []):
        location = row.get("location") or {}
        try:
            lat = float(location["latitude"])
            lon = float(location["longitude"])
        except (KeyError, TypeError, ValueError):
            continue
        kinds = row.get("types") or ["place"]
        places.append(
            Place(
                name=(row.get("displayName") or {}).get("text", "").strip(),
                address=str(row.get("formattedAddress") or "").strip(),
                lat=lat,
                lon=lon,
                kind=str(kinds[0]),
                osm_id="",
                importance=0.0,
            )
        )
    return places


def _search_photon(query, *, limit, bbox):
    """A second free service over the same OpenStreetMap data.

    Photon indexes and ranks differently from Nominatim, so it sometimes finds
    a name the other misses. Its bounding box is only a hint, not a limit - it
    answered a Jammu query with a temple in Sialkot - so the caller must still
    test every result against the real district.
    """
    params = {"q": query, "limit": str(max(1, min(int(limit), 20))), "lang": "en"}
    if bbox:
        min_lon, min_lat, max_lon, max_lat = bbox
        params["bbox"] = f"{min_lon},{min_lat},{max_lon},{max_lat}"

    url = f"{PHOTON_ENDPOINT}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})

    _respect_rate_limit()
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, ValueError):
        return []  # a second opinion that cannot be reached is simply skipped

    places = []
    for feature in payload.get("features", []):
        try:
            lon, lat = feature["geometry"]["coordinates"][:2]
            lat, lon = float(lat), float(lon)
        except (KeyError, IndexError, TypeError, ValueError):
            continue
        fields = feature.get("properties", {}) or {}
        parts = [
            fields.get(k)
            for k in ("name", "street", "district", "city", "county", "state")
            if fields.get(k)
        ]
        places.append(
            Place(
                name=str(fields.get("name") or "").strip(),
                address=", ".join(dict.fromkeys(parts)) or str(fields.get("name") or ""),
                lat=lat,
                lon=lon,
                kind=str(fields.get("osm_value") or fields.get("type") or "place"),
                osm_id=f"{fields.get('osm_type', '')}/{fields.get('osm_id', '')}",
                importance=0.0,
            )
        )
    return places


def search_best(
    query: str,
    *,
    bbox: tuple[float, float, float, float] | None = None,
    keep=None,
    limit: int = 8,
) -> tuple[list[Place], str, list[str]]:
    """Ask each service in turn until one returns a usable answer.

    ``keep`` is a test the caller supplies - in practice "is this point inside
    the district being mapped?" - and is applied to every result whatever the
    service claimed, because none of these bounding boxes is trustworthy on
    its own.

    Returns the places, the name of the service that found them, and the list
    of services tried, so the page can say where an answer came from.

    Order: OpenStreetMap through Nominatim, then Photon over the same data but
    indexed differently, then Google Places if a key is configured. Free and
    keyless first; Google is only reached when the others found nothing.
    """
    tried: list[str] = []

    def usable(places):
        return [p for p in places if keep is None or keep(p.lat, p.lon)]

    # 1. Nominatim, hard-bounded to the district.
    tried.append("OpenStreetMap")
    try:
        found = usable(_search_nominatim(query, limit=limit, bbox=bbox, bounded=True))
    except GeocodeError:
        found = []
    if found:
        return found, "OpenStreetMap", tried

    # 2. Photon, the same data indexed differently.
    tried.append("Photon")
    found = usable(_search_photon(query, limit=limit, bbox=bbox))
    if found:
        return found, "Photon", tried

    # 3. Google Places, only when a key is configured.
    import os

    if os.environ.get("GOOGLE_MAPS_API_KEY"):
        tried.append("Google Places")
        try:
            found = usable(
                _search_google(query, limit=limit, near=None, bbox=bbox, bounded=True)
            )
        except GeocodeError:
            found = []
        if found:
            return found, "Google Places", tried

    return [], "", tried


def attribution() -> str:
    """The credit the licence of whichever service is in use requires."""
    if provider() == "google":
        return "Place search: Google Places."
    return "Place search: OpenStreetMap contributors, via Nominatim (ODbL)."
