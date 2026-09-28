"""Turning the edited sites table into sites, safely.

This exists because of a bug that put sites called "nan" on maps.

A blank cell in a spreadsheet-style editor comes back as float NaN, and NaN is
truthy in Python. So ``str(value or "")`` on an empty name cell produces the
string ``"nan"``, every guard written as ``if not name`` walks straight past
it, and a site named "nan" is placed at whatever coordinates happened to be in
that row. The cleaners below treat a blank cell as blank.

The second rule here is that a half-filled row is reported, not dropped. A
coordinate with a typo in it should not make a site quietly vanish from the
map; the person needs to be told which row they need to look at.

Nothing in this module imports Streamlit, so it can be tested directly.
"""

from __future__ import annotations

import math

__all__ = ["empty_sites", "clean_text", "clean_number", "sites_from_table"]

# Strings a spreadsheet or a dataframe round-trip can leave behind where the
# person meant to leave the cell empty.
_BLANK_WORDS = {"nan", "none", "null", "<na>", "na", "nat"}

# The whole of India, with room to spare: Gujarat's west coast to Arunachal,
# and Kanyakumari to the northern tip of the official depiction. A coordinate
# outside this is wrong for this tool whatever else is true of it, and the
# commonest way to land outside it is to enter latitude and longitude the
# wrong way round.
INDIA_LAT = (5.5, 38.0)
INDIA_LON = (67.0, 98.5)


def empty_sites():
    """An empty sites table with the right columns and column types."""
    import pandas as pd

    return pd.DataFrame(
        {
            "name": pd.Series(dtype="object"),
            "lat": pd.Series(dtype="float64"),
            "lon": pd.Series(dtype="float64"),
            "type": pd.Series(dtype="object"),
        }
    )


def _is_missing(value) -> bool:
    """Whether a cell holds nothing, including the several ways of spelling it."""
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    try:
        import pandas as pd

        if pd.isna(value):
            return True
    except (TypeError, ValueError, ImportError):
        pass
    return False


def clean_text(value, fallback: str = "") -> str:
    """Text from a cell, with every flavour of blank treated as blank."""
    if _is_missing(value):
        return fallback
    text = str(value).strip()
    if not text or text.lower() in _BLANK_WORDS:
        return fallback
    return text


def clean_number(value):
    """A float from a cell, or ``None`` when it is blank or not a number."""
    if _is_missing(value):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def _in_india(lat: float, lon: float) -> bool:
    """Whether a coordinate falls in the box that contains all of India."""
    return INDIA_LAT[0] <= lat <= INDIA_LAT[1] and INDIA_LON[0] <= lon <= INDIA_LON[1]


def sites_from_table(frame) -> tuple[list[dict], list[str]]:
    """Return the usable sites, and a message for every row that is not usable.

    A completely empty row is ignored, because that is just the blank row the
    editor leaves at the bottom. Anything half-filled is reported by row
    number, so a mistyped coordinate is visible rather than silent.
    """
    sites: list[dict] = []
    problems: list[str] = []

    for position, row in enumerate(frame.to_dict("records"), start=1):
        name = clean_text(row.get("name"))
        lat = clean_number(row.get("lat"))
        lon = clean_number(row.get("lon"))

        if not name and lat is None and lon is None:
            continue

        if not name:
            problems.append(
                f"Row {position} has coordinates but no name, so it was left off the map."
            )
            continue
        if lat is None or lon is None:
            missing = "latitude" if lat is None else "longitude"
            problems.append(
                f"Row {position} ({name}) has no {missing}, so it was left off the map."
            )
            continue
        if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
            problems.append(
                f"Row {position} ({name}) has {lat}, {lon}, which is not a real "
                f"coordinate at all."
            )
            continue

        if not _in_india(lat, lon):
            swapped = _in_india(lon, lat)
            hint = (
                f" Those two look swapped: {lon}, {lat} would be in India."
                if swapped
                else " In India latitude is about 8 to 37 and longitude about 68 to 97."
            )
            problems.append(
                f"Row {position} ({name}) is at {lat}, {lon}, which is outside "
                f"India, so it was left off the map.{hint}"
            )
            continue

        sites.append(
            {
                "name": name,
                "lat": lat,
                "lon": lon,
                "type": clean_text(row.get("type"), "hospital"),
            }
        )

    return sites, problems
