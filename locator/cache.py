"""Split the national boundary files into a per-state cache.

Why this exists. The three national layers hold about 1.1 GB once geopandas has
them in memory, which is over the 1 GB a free Streamlit Community Cloud app is
allowed. Loading all of India to draw one district was always wasteful; on a
hosted deployment it is fatal.

So the raw files are split once, on a machine with room to do it, into one file
per state. Drawing a map then reads one state's districts and one state's
blocks — a few megabytes — instead of the whole country.

Two things this deliberately does not do:

- **It does not simplify district or block geometry.** Those polygons are
  written through unchanged, so nothing about accuracy depends on this step.
  The only layer thinned is states, and only to 150 m, which is a tenth of a
  pixel at the size the India panel is ever drawn.
- **It does not become a source of truth.** The cache is derived, disposable
  and rebuilt with ``python -m locator prepare``. ``data/SOURCES.md`` still
  describes where the real data came from.

It also writes two small index files with no geometry in them at all, so the
dashboard can populate its dropdowns without reading a single polygon.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import geopandas as gpd
import pandas as pd

__all__ = ["prepare_cache", "cache_manifest", "cache_is_ready"]

# States are the one layer kept whole, so it is the one layer worth thinning.
# The India panel is drawn at roughly 1.4 km per pixel at 600 dpi and already
# simplifies to 400 m at render time, so 150 m here is well inside what was
# being discarded anyway.
STATE_SIMPLIFY_M = 150

MANIFEST_NAME = "MANIFEST.json"

# zstd roughly halves these files against parquet's default snappy, which is
# what makes the cache small enough to live in the repository and so small
# enough to deploy. It costs nothing at read time.
COMPRESSION = "zstd"
COMPRESSION_LEVEL = 15


def _write(frame, path: Path) -> None:
    frame.to_parquet(
        path, index=False, compression=COMPRESSION, compression_level=COMPRESSION_LEVEL
    )


def processed_dir() -> Path:
    from . import data as data_module

    return data_module.data_dir() / "processed"


def cache_manifest() -> dict | None:
    """Return what the cache says about itself, or None if it is not built."""
    path = processed_dir() / MANIFEST_NAME
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def cache_is_ready() -> bool:
    manifest = cache_manifest()
    if not manifest:
        return False
    root = processed_dir()
    required = [root / "states.parquet", root / "index.parquet", root / "units_index.parquet"]
    return all(p.exists() for p in required)


def prepare_cache(*, log=print, include_subdistricts: bool = True) -> dict:
    """Build the per-state cache from the raw national files.

    Needs the raw files present and about 1.5 GB of memory to run. It is a
    one-off: the output is what gets deployed.
    """
    from . import data as data_module

    root = processed_dir()
    (root / "districts").mkdir(parents=True, exist_ok=True)
    (root / "blocks").mkdir(parents=True, exist_ok=True)

    summary: dict = {
        "built_on": date.today().isoformat(),
        "state_simplify_m": STATE_SIMPLIFY_M,
        "note": (
            "Derived from the raw files described in data/SOURCES.md. District "
            "and block geometry is copied through unchanged. Rebuild with "
            "python -m locator prepare."
        ),
        "sources": {},
        "counts": {},
    }

    for key in ("states", "districts", "blocks"):
        path = data_module.raw_path(key)
        summary["sources"][key] = {
            "file": path.name,
            "size_mb": round(path.stat().st_size / 1e6, 1) if path.exists() else None,
        }

    # ---- states: the only layer kept whole, so the only one thinned --------
    log("Preparing states...")
    states = data_module.load_states()
    states = states.copy()
    metric = states.estimate_utm_crs()
    states["geometry"] = (
        states.to_crs(metric).geometry.simplify(STATE_SIMPLIFY_M, preserve_topology=True)
        .to_crs(states.crs)
    )
    _write(states, root / "states.parquet")
    summary["counts"]["states"] = int(len(states))

    # ---- districts, one file per state ------------------------------------
    log("Preparing districts, one file per state...")
    districts = data_module.load_districts()
    written = 0
    for state_lgd, group in districts.groupby(districts["state_lgd"].astype("int64")):
        _write(group, root / "districts" / f"{int(state_lgd)}.parquet")
        written += 1
    summary["counts"]["districts"] = int(len(districts))
    summary["counts"]["district_files"] = written

    # ---- blocks, one file per state ---------------------------------------
    log("Preparing blocks, one file per state...")
    blocks = data_module.load_blocks()
    written = 0
    for state_lgd, group in blocks.groupby(blocks["state_lgd"].astype("int64")):
        _write(group, root / "blocks" / f"{int(state_lgd)}.parquet")
        written += 1
    summary["counts"]["blocks"] = int(len(blocks))
    summary["counts"]["block_files"] = written

    # ---- the two index files, with no geometry at all ---------------------
    log("Writing the index files...")
    index = pd.DataFrame(
        {
            "state_lgd": districts["state_lgd"].astype("int64"),
            "state_name": districts["state"].astype(str),
            "state_key": districts["state_key"].astype(str),
            "dist_lgd": districts["lgd"].astype("int64"),
            "district_name": districts["name"].astype(str),
            "district_key": districts["name_key"].astype(str),
        }
    )
    # The state layer is the authority on what a state is called, so take the
    # display name from there rather than from the district layer, which spells
    # at least one union territory differently.
    state_names = dict(zip(states["lgd"].astype("int64"), states["name"].astype(str)))
    index["state_name"] = index["state_lgd"].map(state_names).fillna(index["state_name"])
    _write(index, root / "index.parquet")

    units = pd.DataFrame(
        {
            "dist_lgd": blocks["district_lgd"].astype("int64"),
            "unit_name": blocks["name"].astype(str),
            "unit_lgd": blocks["lgd"].astype("int64"),
            "level": "block",
        }
    )
    _write(units, root / "units_index.parquet")
    summary["counts"]["index_rows"] = int(len(index))
    summary["counts"]["unit_index_rows"] = int(len(units))

    # ---- sub-districts, for the districts with no blocks ------------------
    if include_subdistricts and data_module.raw_path("subdistricts").exists():
        # Sub-districts are only ever read for a district that has no blocks.
        # Writing all of them would more than double the cache for data almost
        # nothing uses, so only the states that actually contain such a
        # district are written, and the manifest records which.
        needy_districts = districts[
            ~districts["lgd"].astype("int64").isin(
                blocks["district_lgd"].astype("int64").unique()
            )
        ]
        needy_states = sorted(needy_districts["state_lgd"].astype("int64").unique())
        summary["districts_without_blocks"] = int(len(needy_districts))
        summary["states_needing_subdistricts"] = [int(x) for x in needy_states]

        if needy_states:
            log(
                f"Preparing sub-districts for the {len(needy_states)} state(s) with "
                f"block-less districts ({len(needy_districts)} districts)..."
            )
            (root / "subdistricts").mkdir(parents=True, exist_ok=True)
            subdistricts = data_module.load_subdistricts()
            written = 0
            for state_lgd, group in subdistricts.groupby(
                subdistricts["state_lgd"].astype("int64")
            ):
                if int(state_lgd) not in needy_states:
                    continue
                _write(group, root / "subdistricts" / f"{int(state_lgd)}.parquet")
                written += 1
            summary["counts"]["subdistrict_files"] = written
        else:
            log("No district is missing blocks, so no sub-districts are needed.")
    else:
        log("Skipping sub-districts: the raw file is not present.")

    total_mb = sum(p.stat().st_size for p in root.rglob("*.parquet")) / 1e6
    summary["cache_size_mb"] = round(total_mb, 1)

    (root / MANIFEST_NAME).write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    log(f"Cache built: {total_mb:.0f} MB across {len(list(root.rglob('*.parquet')))} files.")
    return summary


# --------------------------------------------------------------------------
# reading from the cache
# --------------------------------------------------------------------------


def read_states() -> gpd.GeoDataFrame | None:
    path = processed_dir() / "states.parquet"
    return gpd.read_parquet(path) if path.exists() else None


def read_districts(state_lgd: int) -> gpd.GeoDataFrame | None:
    path = processed_dir() / "districts" / f"{int(state_lgd)}.parquet"
    return gpd.read_parquet(path) if path.exists() else None


def read_blocks(state_lgd: int) -> gpd.GeoDataFrame | None:
    path = processed_dir() / "blocks" / f"{int(state_lgd)}.parquet"
    return gpd.read_parquet(path) if path.exists() else None


def read_subdistricts(state_lgd: int) -> gpd.GeoDataFrame | None:
    path = processed_dir() / "subdistricts" / f"{int(state_lgd)}.parquet"
    return gpd.read_parquet(path) if path.exists() else None


def read_index() -> pd.DataFrame | None:
    """Every state and district, names and codes only, no geometry."""
    path = processed_dir() / "index.parquet"
    return pd.read_parquet(path) if path.exists() else None


def read_units_index() -> pd.DataFrame | None:
    """Every block, names and codes only, no geometry."""
    path = processed_dir() / "units_index.parquet"
    return pd.read_parquet(path) if path.exists() else None


def state_of_district(dist_lgd: int) -> int | None:
    """Which state a district belongs to, looked up in the index."""
    index = read_index()
    if index is None:
        return None
    match = index[index["dist_lgd"].astype("int64") == int(dist_lgd)]
    return int(match.iloc[0]["state_lgd"]) if len(match) else None
