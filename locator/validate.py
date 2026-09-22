"""Validation that runs before every render.

The rule this module exists to enforce is that a map is never drawn from
assumptions. Each check either confirms something against a sourced dataset or
reports, by name, what it could not confirm.

Severities
----------
``ERROR``
    Something required is absent or wrong: an unknown place name, a missing
    layer, a site outside the district it was filed under. Always stops the
    render. ``--force`` does not override these.
``WARNING``
    Something is inconsistent but the map can still be drawn honestly: a unit
    count that disagrees with the LGD reference, a site in a different block
    from the one the user named. Stops the render unless ``--force`` is given.
``INFO``
    Worth recording in the render log, never blocks.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

import geopandas as gpd
from shapely.geometry import Point

from . import data as data_module
from .names import AliasTable, display, key as name_key

__all__ = ["Issue", "ValidationReport", "validate_request", "ResolvedTarget"]

ERROR = "ERROR"
WARNING = "WARNING"
INFO = "INFO"


@dataclass(frozen=True)
class Issue:
    severity: str
    check: str
    message: str

    def __str__(self) -> str:
        return f"[{self.severity}] {self.check}: {self.message}"


@dataclass
class ValidationReport:
    issues: list[Issue] = field(default_factory=list)

    def add(self, severity: str, check: str, message: str) -> None:
        self.issues.append(Issue(severity, check, message))

    def error(self, check: str, message: str) -> None:
        self.add(ERROR, check, message)

    def warning(self, check: str, message: str) -> None:
        self.add(WARNING, check, message)

    def info(self, check: str, message: str) -> None:
        self.add(INFO, check, message)

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == ERROR]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == WARNING]

    def blocks_render(self, *, force: bool) -> bool:
        if self.errors:
            return True
        return bool(self.warnings) and not force

    def summary(self) -> str:
        counts = {
            "errors": len(self.errors),
            "warnings": len(self.warnings),
            "notes": len([i for i in self.issues if i.severity == INFO]),
        }
        return ", ".join(f"{v} {k}" for k, v in counts.items())

    def render_text(self) -> str:
        if not self.issues:
            return "All checks passed."
        order = {ERROR: 0, WARNING: 1, INFO: 2}
        lines = [str(i) for i in sorted(self.issues, key=lambda i: order[i.severity])]
        return "\n".join(lines)


@dataclass
class ResolvedTarget:
    """What the validator worked out, handed on to the renderer."""

    state_name: str
    state_key: str
    state_row: object
    district_name: str
    district_lgd: object
    district_row: object
    districts: gpd.GeoDataFrame
    blocks: gpd.GeoDataFrame
    target_block_names: list[str]
    sites: list[dict]
    block_level_label: str = "block"


def _load_reference_counts() -> dict[tuple[str, str], dict]:
    """Load ``data/lgd/reference_counts.csv``.

    This is the independent register the layers are checked against. It is
    deliberately separate from the geometry: checking an LGD-derived layer
    against itself would confirm nothing.
    """
    path = data_module.data_dir() / "lgd" / "reference_counts.csv"
    if not path.exists():
        return {}
    table: dict[tuple[str, str], dict] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            level = (row.get("level") or "").strip().lower()
            parent = name_key(row.get("parent") or "")
            if not level or not parent:
                continue
            table[(level, parent)] = row
    return table


def validate_request(
    *,
    state: str,
    district: str,
    blocks: list[str],
    sites: list[dict],
    aliases: AliasTable,
    report: ValidationReport | None = None,
) -> tuple[ValidationReport, ResolvedTarget | None]:
    """Run every pre-render check. Returns the report and, if usable, the target."""
    report = report or ValidationReport()
    references = _load_reference_counts()

    # ---- Check 1a: the state exists in the boundary layer -------------------
    state_canonical, alias_hit = aliases.resolve("state", state)
    if alias_hit:
        report.info("names", alias_hit.message())

    states = data_module.load_states()
    real_states = states[~states["disputed"]]
    state_match = real_states[real_states["name_key"] == name_key(state_canonical)]
    if state_match.empty:
        near = _closest(name_key(state_canonical), real_states["name_key"].tolist())
        hint = f" Did you mean {display(near)}?" if near else ""
        report.error(
            "state name",
            f"{state!r} is not a state or union territory in the boundary layer.{hint}",
        )
        return report, None
    state_row = state_match.iloc[0]
    state_display = display(state_row["name"])

    # ---- Check 1b: the district exists in that state ------------------------
    district_canonical, alias_hit = aliases.resolve("district", district)
    if alias_hit:
        report.info("names", alias_hit.message())

    districts = data_module.districts_of(name_key(state_display))
    if districts.empty:
        report.error(
            "district layer",
            f"The district layer has no districts for {state_display}. "
            f"This state cannot be mapped until district data is added.",
        )
        return report, None

    district_match = districts[districts["name_key"] == name_key(district_canonical)]
    if district_match.empty:
        near = _closest(name_key(district_canonical), districts["name_key"].tolist())
        hint = f" Did you mean {display(near)}?" if near else ""
        report.error(
            "district name",
            f"{district!r} is not a district of {state_display}.{hint} "
            f"Add a spelling variant to data/aliases.csv if the name is right.",
        )
        return report, None
    district_row = district_match.iloc[0]
    district_display = display(district_row["name"])
    district_lgd = district_row["lgd"]

    # ---- Check 2: district count against the LGD reference ------------------
    _check_count(
        report=report,
        references=references,
        aliases=aliases,
        level="district",
        parent=state_display,
        observed_names=sorted(display(n) for n in districts["name"]),
        what=f"districts in {state_display}",
    )

    # ---- Check 3: block layer and block count -------------------------------
    block_frame = data_module.blocks_of(district_lgd)
    block_level_label = "block"
    if block_frame.empty:
        report.error(
            "block layer",
            f"No community development blocks are available for {district_display}. "
            f"The third panel cannot be drawn. Either map this district at district "
            f"level only, or add a block layer for {state_display} and record it in "
            f"data/SOURCES.md.",
        )
        return report, None

    _check_count(
        report=report,
        references=references,
        aliases=aliases,
        level="block",
        parent=district_display,
        observed_names=sorted(display(n) for n in block_frame["name"]),
        what=f"blocks in {district_display}",
    )

    # ---- Check 3b: the named target blocks exist ----------------------------
    target_block_names: list[str] = []
    available = block_frame["name_key"].tolist()
    for given in blocks:
        canonical, alias_hit = aliases.resolve("block", given)
        if alias_hit:
            report.info("names", alias_hit.message())
        match = block_frame[block_frame["name_key"] == name_key(canonical)]
        if match.empty:
            near = _closest(name_key(canonical), available)
            hint = f" Did you mean {display(near)}?" if near else ""
            listing = ", ".join(sorted(display(n) for n in block_frame["name"]))
            report.error(
                "block name",
                f"{given!r} is not a block of {district_display}.{hint}\n"
                f"           The {len(block_frame)} blocks are: {listing}",
            )
        else:
            target_block_names.append(match.iloc[0]["name"])

    # ---- Check 4: site points fall where they are said to fall --------------
    resolved_sites = _check_sites(
        report=report,
        sites=sites,
        district_row=district_row,
        district_display=district_display,
        block_frame=block_frame,
        stated_blocks=target_block_names,
    )

    # ---- Check 5: geometry validity and coverage ----------------------------
    _check_geometry(report, districts, f"districts of {state_display}")
    _check_geometry(report, block_frame, f"blocks of {district_display}")
    _check_coverage(report, district_row, block_frame, district_display)

    if report.errors:
        return report, None

    return report, ResolvedTarget(
        state_name=state_display,
        state_key=name_key(state_display),
        state_row=state_row,
        district_name=district_display,
        district_lgd=district_lgd,
        district_row=district_row,
        districts=districts,
        blocks=block_frame,
        target_block_names=target_block_names,
        sites=resolved_sites,
        block_level_label=block_level_label,
    )


def _sentence(text: str) -> str:
    """Capitalise the first letter only, leaving proper nouns inside intact."""
    return text[:1].upper() + text[1:]


def _check_count(*, report, references, aliases, level, parent, observed_names, what) -> None:
    """Compare a unit count against the LGD reference register, by name.

    Both sides go through the alias table before comparison, so a recorded
    spelling variant never shows up as a missing plus an extra name.
    """
    def canonical_key(value: str) -> str:
        resolved, _ = aliases.resolve(level, value)
        return name_key(resolved)

    reference = references.get((level, name_key(parent)))
    observed = len(observed_names)

    if reference is None:
        report.warning(
            f"{level} count",
            f"No LGD reference is recorded for {what}, so the count of {observed} "
            f"has not been independently checked. Add a row to "
            f"data/lgd/reference_counts.csv to enable this check.",
        )
        return

    expected_count = int(reference["count"])
    expected_names_raw = (reference.get("names") or "").strip()
    source = reference.get("source", "LGD")

    if expected_names_raw:
        expected = [n.strip() for n in expected_names_raw.split("|") if n.strip()]
        expected_keys = {canonical_key(n): n for n in expected}
        observed_keys = {canonical_key(n): n for n in observed_names}

        missing = [expected_keys[k] for k in expected_keys if k not in observed_keys]
        extra = [observed_keys[k] for k in observed_keys if k not in expected_keys]

        if missing or extra:
            parts = []
            if missing:
                parts.append(f"missing from the map data: {', '.join(sorted(missing))}")
            if extra:
                parts.append(f"present but not in {source}: {', '.join(sorted(extra))}")
            report.warning(
                f"{level} count",
                f"{_sentence(what)} do not match {source} "
                f"({observed} found, {expected_count} expected) - " + "; ".join(parts),
            )
            return

    if observed != expected_count:
        report.warning(
            f"{level} count",
            f"{_sentence(what)}: {observed} found but {source} records "
            f"{expected_count}.",
        )
        return

    report.info(f"{level} count", f"{_sentence(what)}: {observed}, matching {source}.")


def _check_sites(*, report, sites, district_row, district_display, block_frame, stated_blocks):
    """Confirm each site falls inside the district and report its actual block."""
    if not sites:
        report.info("sites", "No site points given.")
        return []

    # Work in a metre-based CRS so distances mean something.
    metric = block_frame.estimate_utm_crs()
    blocks_m = block_frame.to_crs(metric)
    district_m = gpd.GeoSeries([district_row["geometry"]], crs=block_frame.crs).to_crs(metric).iloc[0]

    stated_keys = {name_key(b) for b in stated_blocks}
    resolved = []

    for site in sites:
        name = site.get("name") or "unnamed site"
        try:
            lat = float(site["lat"])
            lon = float(site["lon"])
        except (KeyError, TypeError, ValueError):
            report.error("site coordinates", f"{name}: lat and lon must both be numbers.")
            continue

        if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
            report.error(
                "site coordinates",
                f"{name}: lat {lat}, lon {lon} is not a valid coordinate. "
                f"In India lat is about 8-37 and lon about 68-97 - check they are not swapped.",
            )
            continue

        point_m = gpd.GeoSeries([Point(lon, lat)], crs=4326).to_crs(metric).iloc[0]

        if not district_m.contains(point_m):
            distance_km = district_m.distance(point_m) / 1000
            report.error(
                "site location",
                f"{name} at ({lat}, {lon}) is not inside {district_display} district - "
                f"it is {distance_km:.1f} km outside it. Check the coordinates: "
                f"right-click the place in Google Maps and copy the pair it shows.",
            )
            continue

        hit = blocks_m[blocks_m.geometry.contains(point_m)]
        actual_block = display(hit.iloc[0]["name"]) if len(hit) else None

        if actual_block is None:
            report.warning(
                "site location",
                f"{name} is inside {district_display} district but not inside any "
                f"block polygon. It may sit in a municipal area the block layer excludes.",
            )
        elif stated_keys and name_key(actual_block) not in stated_keys:
            stated_list = ", ".join(display(b) for b in stated_blocks)
            report.warning(
                "site location",
                f"{name} falls in {actual_block} block, not {stated_list}. "
                f"Either highlight {actual_block} instead, or keep the current "
                f"highlight if the site serves {stated_list}.",
            )
        else:
            report.info("site location", f"{name} falls in {actual_block} block, as stated.")

        entry = dict(site)
        entry["actual_block"] = actual_block
        resolved.append(entry)

    return resolved


def _check_geometry(report, frame: gpd.GeoDataFrame, what: str) -> None:
    """Report invalid or empty geometries by name."""
    if frame.empty:
        return
    empty = frame[frame.geometry.is_empty | frame.geometry.isna()]
    if len(empty):
        names = ", ".join(display(n) for n in empty["name"])
        report.error("geometry", f"These {what} have no shape: {names}.")

    invalid = frame[~frame.geometry.is_valid & ~frame.geometry.is_empty]
    if len(invalid):
        names = ", ".join(display(n) for n in invalid["name"])
        report.warning(
            "geometry",
            f"These {what} have self-intersecting outlines and will be repaired "
            f"for drawing only: {names}.",
        )


def _check_coverage(report, district_row, block_frame, district_display) -> None:
    """Check the blocks tile the district, with no meaningful gap or overhang."""
    metric = block_frame.estimate_utm_crs()
    district_area = (
        gpd.GeoSeries([district_row["geometry"]], crs=block_frame.crs).to_crs(metric).area.sum()
    )
    blocks_area = block_frame.to_crs(metric).area.sum()
    if district_area <= 0:
        return

    difference_pct = (blocks_area - district_area) / district_area * 100
    if abs(difference_pct) <= 1.0:
        report.info(
            "coverage",
            f"Blocks tile {district_display} district "
            f"({blocks_area / 1e6:,.0f} km² against {district_area / 1e6:,.0f} km²).",
        )
    elif difference_pct < 0:
        report.warning(
            "coverage",
            f"The blocks of {district_display} cover {abs(difference_pct):.1f}% less area "
            f"than the district polygon. Part of the district has no block - often a "
            f"municipal corporation area. It will appear unfilled on the map.",
        )
    else:
        report.warning(
            "coverage",
            f"The blocks of {district_display} cover {difference_pct:.1f}% more area than "
            f"the district polygon, so the two layers disagree at the boundary.",
        )


def _closest(target: str, candidates: list[str]) -> str | None:
    """Return the nearest candidate name, for a 'did you mean' hint."""
    import difflib

    matches = difflib.get_close_matches(target, candidates, n=1, cutoff=0.75)
    return matches[0] if matches else None
