"""Download, cache and load the boundary layers.

Every dataset this module can load is declared in :data:`DATASETS`, and every
declaration matches an entry in ``data/SOURCES.md``. There is no code path that
fabricates geometry: if a file is missing the module downloads the declared
dataset, and if that fails it raises :class:`MissingDataError` with instructions
rather than falling back to anything.

Loaded layers are normalised to a common set of columns so the rest of the
project never has to know that Survey of India spells the column ``STATE_C``
while LGD spells it ``stname``.
"""

from __future__ import annotations

import shutil
import urllib.error
import urllib.request
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import geopandas as gpd
import pandas as pd

from .names import key as name_key

__all__ = [
    "MissingDataError",
    "DATASETS",
    "Dataset",
    "data_dir",
    "raw_path",
    "ensure_dataset",
    "load_states",
    "load_districts",
    "load_blocks",
]

_RELEASE_BASE = "https://github.com/ramSeraph/indian_admin_boundaries/releases/download"


class MissingDataError(RuntimeError):
    """Raised when a required boundary layer is not present and cannot be fetched.

    The message is written for a non-technical reader and always says what to do
    next. This error stops a render; it is never caught and worked around.
    """


@dataclass(frozen=True)
class Dataset:
    """One declared boundary file. Mirrors an entry in ``data/SOURCES.md``."""

    key: str
    filename: str
    release_tag: str
    description: str
    origin: str
    licence: str
    approx_mb: int

    @property
    def url(self) -> str:
        return f"{_RELEASE_BASE}/{self.release_tag}/{self.filename}"


DATASETS: dict[str, Dataset] = {
    "states": Dataset(
        key="states",
        filename="SOI_States.parquet",
        release_tag="states",
        description="India state and union territory boundaries",
        origin="Survey of India, via ramSeraph/indian_admin_boundaries",
        licence="CC0 1.0 (attribute Survey of India and datameet)",
        approx_mb=19,
    ),
    "districts": Dataset(
        key="districts",
        filename="LGD_Districts.parquet",
        release_tag="districts",
        description="District boundaries with LGD codes",
        origin="LGD / BharatMaps, via ramSeraph/indian_admin_boundaries",
        licence="CC0 1.0 (attribute LGD and datameet)",
        approx_mb=33,
    ),
    "subdistricts": Dataset(
        key="subdistricts",
        filename="LGD_Subdistricts.parquet",
        release_tag="subdistricts",
        description="Sub-district (tehsil / taluk) boundaries with LGD codes",
        origin="LGD / BharatMaps, via ramSeraph/indian_admin_boundaries",
        licence="CC0 1.0 (attribute LGD and datameet)",
        approx_mb=95,
    ),
    "blocks": Dataset(
        key="blocks",
        filename="LGD_Blocks.parquet",
        release_tag="blocks",
        description="Community development block boundaries with LGD codes",
        origin="LGD / BharatMaps, via ramSeraph/indian_admin_boundaries",
        licence="CC0 1.0 (attribute LGD and datameet)",
        approx_mb=96,
    ),
}


def data_dir() -> Path:
    """Return the project's ``data`` directory."""
    return Path(__file__).resolve().parent.parent / "data"


def raw_path(key: str) -> Path:
    """Return where the raw file for ``key`` lives on disk."""
    return data_dir() / "raw" / DATASETS[key].filename


def ensure_dataset(key: str, *, allow_download: bool = True, log=None) -> Path:
    """Return the path to dataset ``key``, downloading it if it is not present.

    Raises :class:`MissingDataError` if the file is absent and cannot be
    downloaded. It never substitutes a different dataset.
    """
    dataset = DATASETS[key]
    path = raw_path(key)
    if path.exists() and path.stat().st_size > 0:
        return path

    if not allow_download:
        raise MissingDataError(
            f"The {dataset.description} file is missing.\n"
            f"  Expected at: {path}\n"
            f"  Download it from: {dataset.url}\n"
            f"  ({dataset.approx_mb} MB). Put the file at the path above and run again."
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    if log:
        log(f"Downloading {dataset.description} ({dataset.approx_mb} MB). This happens once.")

    temp = path.with_suffix(path.suffix + ".part")
    try:
        with urllib.request.urlopen(dataset.url, timeout=120) as response, temp.open("wb") as out:
            shutil.copyfileobj(response, out)
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        temp.unlink(missing_ok=True)
        raise MissingDataError(
            f"Could not download the {dataset.description}.\n"
            f"  Tried: {dataset.url}\n"
            f"  Reason: {exc}\n\n"
            f"If you are offline or behind a firewall, download that file on a machine\n"
            f"that has internet access and save it here:\n"
            f"  {path}\n"
            f"Then run the tool again."
        ) from exc

    temp.replace(path)
    if log:
        log(f"Saved {path.name}.")
    return path


def _read(key: str, *, allow_download: bool = True, log=None) -> gpd.GeoDataFrame:
    path = ensure_dataset(key, allow_download=allow_download, log=log)
    frame = gpd.read_parquet(path)
    if frame.crs is None:
        raise MissingDataError(
            f"{path.name} has no coordinate reference system recorded, so it cannot be "
            f"projected safely. Delete the file and let the tool download it again."
        )
    return frame


@lru_cache(maxsize=1)
def load_states() -> gpd.GeoDataFrame:
    """Return all states and union territories, normalised.

    Columns: ``name``, ``name_key``, ``lgd``, ``disputed``, ``geometry``.

    The four internal "DISPUTED (...)" slivers are kept, because dropping them
    would leave holes in the national outline, and flagged so they are never
    labelled or offered as a target.
    """
    from . import cache as cache_module

    cached = cache_module.read_states()
    if cached is not None:
        return cached

    frame = _read("states")
    out = gpd.GeoDataFrame(
        {
            "name": frame["STATE_C"].astype(str).str.strip(),
            "lgd": frame["State_LGD"].astype("int64"),
            "geometry": frame.geometry,
        },
        crs=frame.crs,
    )
    out["disputed"] = out["name"].str.upper().str.startswith("DISPUTED")
    out["name_key"] = out["name"].map(name_key)
    return out


@lru_cache(maxsize=1)
def load_districts() -> gpd.GeoDataFrame:
    """Return all districts, normalised.

    Columns: ``name``, ``name_key``, ``lgd``, ``state``, ``state_key``,
    ``state_lgd``, ``geometry``.
    """
    frame = _read("districts")
    out = gpd.GeoDataFrame(
        {
            "name": frame["dtname"].astype(str).str.strip(),
            "lgd": frame["dist_lgd"],
            "state": frame["stname"].astype(str).str.strip(),
            "state_lgd": frame["state_lgd"],
            "geometry": frame.geometry,
        },
        crs=frame.crs,
    )
    out["name_key"] = out["name"].map(name_key)
    out["state_key"] = out["state"].map(name_key)
    return out


@lru_cache(maxsize=1)
def load_blocks() -> gpd.GeoDataFrame:
    """Return all community development blocks, normalised.

    Columns: ``name``, ``name_key``, ``lgd``, ``district``, ``district_key``,
    ``district_lgd``, ``state``, ``state_key``, ``state_lgd``, ``geometry``.
    """
    frame = _read("blocks")
    out = gpd.GeoDataFrame(
        {
            "name": frame["block_name"].astype(str).str.strip(),
            "lgd": frame["block_lgd"],
            "district": frame["district"].astype(str).str.strip(),
            "district_lgd": frame["dist_lgd"],
            "state": frame["state"].astype(str).str.strip(),
            "state_lgd": frame["state_lgd"],
            "geometry": frame.geometry,
        },
        crs=frame.crs,
    )
    out["name_key"] = out["name"].map(name_key)
    out["district_key"] = out["district"].map(name_key)
    out["state_key"] = out["state"].map(name_key)
    return out


@lru_cache(maxsize=1)
def load_subdistricts() -> gpd.GeoDataFrame:
    """Return all sub-districts (tehsils / taluks), normalised.

    Only loaded when a district has no block layer, because the file is large
    and most districts never need it.

    Columns: ``name``, ``name_key``, ``lgd``, ``district``, ``district_lgd``,
    ``state``, ``state_key``, ``geometry``.
    """
    frame = _read("subdistricts")
    out = gpd.GeoDataFrame(
        {
            "name": frame["sdtname"].astype(str).str.strip(),
            "lgd": frame["subdt_lgd"],
            "district": frame["dtname"].astype(str).str.strip(),
            "district_lgd": frame["dist_lgd"],
            "state": frame["stname"].astype(str).str.strip(),
            "state_lgd": frame["state_lgd"],
            "geometry": frame.geometry,
        },
        crs=frame.crs,
    )
    out["name_key"] = out["name"].map(name_key)
    out["district_key"] = out["district"].map(name_key)
    out["state_key"] = out["state"].map(name_key)
    return out


def _subdistrict_source(district_geometry) -> gpd.GeoDataFrame:
    """Sub-districts to search, narrowed to the relevant state where possible.

    A district carved out of a neighbour can draw tehsils from either, so this
    keeps every state whose extent touches the district rather than guessing
    one. Falls back to the national layer when the cache is not built.
    """
    from . import cache as cache_module

    index = cache_module.read_index()
    if index is None:
        return load_subdistricts()

    states = load_states()
    touching = states.iloc[states.sindex.query(district_geometry, predicate="intersects")]
    frames = []
    for state_lgd in touching["lgd"].astype("int64").unique():
        frame = cache_module.read_subdistricts(int(state_lgd))
        if frame is not None and len(frame):
            frames.append(frame)

    if not frames:
        return load_subdistricts()
    if len(frames) == 1:
        return frames[0]
    return gpd.GeoDataFrame(
        pd.concat(frames, ignore_index=True), crs=frames[0].crs
    )


def subdistricts_within(district_geometry, *, min_overlap: float = 0.5):
    """Return the sub-districts that lie inside ``district_geometry``.

    Selected by where they actually are, not by the district code they carry.
    A district created after the sub-district register was last published has
    no sub-districts filed under it, but the tehsils that now make it up do
    exist, filed under the district it was carved out of. Picking them up by
    location recovers them without inventing anything: every polygon returned
    is a published one.

    A sub-district is kept when more than ``min_overlap`` of its area falls
    inside the district. Returns the selection and the fraction of the
    district those pieces cover, which the caller reports to the user.
    """
    subdistricts = _subdistrict_source(district_geometry)
    candidates = subdistricts.iloc[
        subdistricts.sindex.query(district_geometry, predicate="intersects")
    ].copy()
    if candidates.empty:
        return candidates, 0.0

    metric = candidates.estimate_utm_crs()
    candidates_m = candidates.to_crs(metric)
    district_m = (
        gpd.GeoSeries([district_geometry], crs=subdistricts.crs).to_crs(metric).iloc[0]
    )

    overlap = candidates_m.geometry.intersection(district_m).area
    own_area = candidates_m.geometry.area
    share = overlap / own_area.where(own_area > 0)

    keep = candidates[(share > min_overlap).to_numpy()]
    if keep.empty or district_m.area <= 0:
        return keep, 0.0

    covered = keep.to_crs(metric).geometry.intersection(district_m).area.sum()
    return keep, float(covered / district_m.area)


def districts_of(state_lgd) -> gpd.GeoDataFrame:
    """Return the districts of one state, matched on LGD state code.

    Matching on the code rather than the name is what makes every state work.
    The layers disagree on punctuation for at least one union territory - the
    state layer writes "DADRA & NAGAR HAVELI & DAMAN & DIU" where the district
    layer writes "DADRA,NAGAR HAVELI,DAMAN & DIU" - and a name match silently
    returns nothing. All 785 districts match a state by code.

    Reads the one state's file from the prepared cache when there is one, so a
    map of one district never pulls the whole country into memory.
    """
    from . import cache as cache_module

    cached = cache_module.read_districts(state_lgd)
    if cached is not None:
        return cached.copy()

    districts = load_districts()
    return districts[districts["state_lgd"].astype("int64") == int(state_lgd)].copy()


def blocks_of(district_lgd) -> gpd.GeoDataFrame:
    """Return the blocks of one district, matched on LGD district code.

    Matching on the code rather than the name avoids every spelling problem and
    is the reason the district layer and the block layer can be joined reliably.

    Reads one state's file from the prepared cache when there is one.
    """
    from . import cache as cache_module

    state_lgd = cache_module.state_of_district(district_lgd)
    if state_lgd is not None:
        cached = cache_module.read_blocks(state_lgd)
        if cached is not None:
            return cached[
                cached["district_lgd"].astype("int64") == int(district_lgd)
            ].copy()

    blocks = load_blocks()
    return blocks[blocks["district_lgd"] == district_lgd].copy()


def dataset_versions() -> list[str]:
    """Return one human-readable line per dataset, for the render log."""
    lines = []
    for dataset in DATASETS.values():
        path = raw_path(dataset.key)
        if path.exists():
            size_mb = path.stat().st_size / 1e6
            lines.append(f"{dataset.filename} ({size_mb:.1f} MB) - {dataset.origin}")
        else:
            lines.append(f"{dataset.filename} - NOT PRESENT")
    return lines
