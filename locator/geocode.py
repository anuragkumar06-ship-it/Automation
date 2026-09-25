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

__all__ = ["Place", "GeocodeError", "search", "attribution"]

ENDPOINT = "https://nominatim.openstreetmap.org/search"

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

    def label(self) -> str:
        """A single line a person can read to judge whether this is the right place."""
        kind = self.kind.replace("_", " ")
        return f"{self.address}  ·  {kind}  ·  {self.lat:.5f}, {self.lon:.5f}"

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
) -> list[Place]:
    """Search the gazetteer for ``query`` and return what it matched.

    ``near`` is appended to the query to narrow it, which is how a district or
    state name is used to disambiguate a common facility name. Returns an empty
    list when the search ran but matched nothing. Raises :class:`GeocodeError`
    when the search could not be carried out at all.
    """
    query = (query or "").strip()
    if not query:
        return []

    full_query = f"{query}, {near}".strip(", ") if near else query
    params = {
        "q": full_query,
        "format": "jsonv2",
        "limit": str(max(1, min(int(limit), 20))),
        "addressdetails": "1",
    }
    if country:
        params["countrycodes"] = country

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


def attribution() -> str:
    """The credit OpenStreetMap's licence requires wherever its data is shown."""
    return "Place search: OpenStreetMap contributors, via Nominatim (ODbL)."
