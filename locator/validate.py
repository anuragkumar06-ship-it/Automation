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
import pandas as pd
from shapely.geometry import Point

from . import data as data_module
from .names import AliasTable, display, key as name_key

__all__ = [
    "Issue",
    "ValidationReport",
    "validate_request",
    "validate_coverage_request",
    "ResolvedTarget",
    "AreaPart",
]

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
class AreaPart:
    """One state of a multi-state coverage map, and the districts chosen in it.

    Each state is resolved on its own - its own district layer, its own count
    check - so a name that exists in two states can never be confused for the
    other one. The districts are carried by LGD code for the same reason.
    """

    state_name: str
    state_row: object
    districts: gpd.GeoDataFrame
    district_names: list[str]
    district_keys: list[str]
    district_lgds: list[int]


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
    blocks_available: bool = True
    unit_level: str = "block"        # "block", "tehsil" or "none"
    unit_coverage: float = 1.0       # share of the district the units cover

    # Several districts picked at once. The third panel only makes sense for
    # one district, so a request naming several is a different map: the state
    # with each of them marked, which is how programme coverage is shown.
    district_names: list[str] = field(default_factory=list)
    target_district_keys: list[str] = field(default_factory=list)

    # Several states picked at once. The map is then one continuous panel:
    # every chosen state's districts, the programme districts marked, and the
    # rest of the country behind them in grey so there is no hole in the land
    # between two states that do not touch.
    area_parts: list[AreaPart] = field(default_factory=list)
    target_district_lgds: list[int] = field(default_factory=list)

    @property
    def multi_state(self) -> bool:
        return len(self.area_parts) > 1

    @property
    def multi_district(self) -> bool:
        # A multi-state map is a coverage map whatever the district count, so
        # anything branching on this treats it as one.
        return len(self.target_district_keys) > 1 or self.multi_state


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


def _resolve_state(*, state: str, aliases: AliasTable, report: ValidationReport):
    """Find one state in the boundary layer, through the alias table.

    Returns the matching row, or ``None`` after reporting why it could not be
    matched. Disputed rows are excluded: the official depiction carries them
    for the external boundary, not as places a map can be made of.
    """
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
        return None
    return state_match.iloc[0]


def _resolve_districts(
    *,
    wanted: list[str],
    districts: gpd.GeoDataFrame,
    state_display: str,
    aliases: AliasTable,
    report: ValidationReport,
):
    """Match each requested district name in one state's district layer.

    Returns the keys, display names and LGD codes of the districts chosen, in
    the order given, or ``None`` after reporting the first name that could not
    be matched. The LGD codes are what the renderer marks on, because a
    district name is only unique within its state.
    """
    chosen_keys: list[str] = []
    chosen_names: list[str] = []
    chosen_lgds: list[int] = []
    for given in wanted:
        canonical, alias_hit = aliases.resolve("district", given)
        if alias_hit:
            report.info("names", alias_hit.message())
        match = districts[districts["name_key"] == name_key(canonical)]
        if match.empty:
            near = _closest(name_key(canonical), districts["name_key"].tolist())
            hint = f" Did you mean {display(near)}?" if near else ""
            report.error(
                "district name",
                f"{given!r} is not a district of {state_display}.{hint} "
                f"Add a spelling variant to data/aliases.csv if the name is right.",
            )
            return None
        key_value = match.iloc[0]["name_key"]
        if key_value in chosen_keys:
            continue
        chosen_keys.append(key_value)
        chosen_names.append(display(match.iloc[0]["name"]))
        chosen_lgds.append(int(match.iloc[0]["lgd"]))

    return chosen_keys, chosen_names, chosen_lgds


def _join_names(names: list[str]) -> str:
    """"A, B and C" - for titles and messages naming several places."""
    if len(names) <= 1:
        return names[0] if names else ""
    return f"{', '.join(names[:-1])} and {names[-1]}"


def validate_request(
    *,
    state: str,
    district: str | None = None,
    districts: list[str] | None = None,
    blocks: list[str] | None = None,
    sites: list[dict] | None = None,
    aliases: AliasTable,
    report: ValidationReport | None = None,
) -> tuple[ValidationReport, ResolvedTarget | None]:
    """Run every pre-render check. Returns the report and, if usable, the target.

    ``districts`` names one or more districts. One district gives the
    three-panel locator map. Several give a state coverage map, with each of
    them marked - the third panel would have nothing to show.

    ``district`` is the older single-district spelling and still works.
    """
    wanted = [d for d in (districts or []) if str(d).strip()]
    if district and not wanted:
        wanted = [district]
    blocks = blocks or []
    sites = sites or []

    report = report or ValidationReport()
    references = _load_reference_counts()

    # ---- Check 1a: the state exists in the boundary layer -------------------
    state_row = _resolve_state(state=state, aliases=aliases, report=report)
    if state_row is None:
        return report, None
    state_display = display(state_row["name"])

    # ---- Check 1b: the district exists in that state ------------------------
    if not wanted:
        report.error("district name", "No district was chosen.")
        return report, None

    districts = data_module.districts_of(state_row["lgd"])
    if districts.empty:
        report.error(
            "district layer",
            f"The district layer has no districts for {state_display}. "
            f"This state cannot be mapped until district data is added.",
        )
        return report, None

    resolved = _resolve_districts(
        wanted=wanted,
        districts=districts,
        state_display=state_display,
        aliases=aliases,
        report=report,
    )
    if resolved is None:
        return report, None
    chosen_keys, chosen_names, _chosen_lgds = resolved

    district_row = districts[districts["name_key"] == chosen_keys[0]].iloc[0]
    district_display = display(district_row["name"])
    district_lgd = district_row["lgd"]
    many = len(chosen_keys) > 1

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

    # ---- several districts: a state coverage map, no third panel ------------
    if many:
        if blocks:
            report.error(
                "blocks",
                f"Blocks cannot be highlighted when {len(chosen_keys)} districts are "
                f"chosen: the third panel shows one district at a time. Pick a single "
                f"district to mark blocks, or clear the block selection.",
            )
            return report, None

        chosen = districts[districts["name_key"].isin(chosen_keys)]
        report.info(
            "districts",
            f"{len(chosen_keys)} districts chosen, so the map is {state_display} with "
            f"each of them marked: {', '.join(chosen_names)}.",
        )

        resolved_sites = _check_sites(
            report=report,
            sites=sites,
            district_row=_combined_row(chosen, state_display),
            district_display=f"the {len(chosen_keys)} chosen districts",
            block_frame=chosen.iloc[0:0],
            stated_blocks=[],
            unit_label="district",
        )
        _check_geometry(report, districts, f"districts of {state_display}")

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
            blocks=chosen.iloc[0:0],
            target_block_names=[],
            sites=resolved_sites,
            block_level_label="district",
            blocks_available=False,
            unit_level="none",
            unit_coverage=1.0,
            district_names=chosen_names,
            target_district_keys=chosen_keys,
        )

    # ---- Check 3: block layer and block count -------------------------------
    block_frame = data_module.blocks_of(district_lgd)
    block_level_label = "block"
    unit_level = "block"
    unit_coverage = 1.0
    blocks_available = not block_frame.empty

    if not blocks_available:
        # Fall back to sub-districts before giving up on the third panel. They
        # are never called blocks: a tehsil is a different unit and the map
        # says so.
        tehsils, coverage = data_module.subdistricts_within(district_row["geometry"])
        if not tehsils.empty:
            block_frame = tehsils
            block_level_label = "tehsil"
            unit_level = "tehsil"
            unit_coverage = coverage
            blocks_available = True

            report.info(
                "block layer",
                f"No community development blocks are published for {district_display}, "
                f"so the third panel shows its {len(tehsils)} tehsils instead. These are "
                f"sub-districts, not blocks, and the map says so.",
            )
            note = (
                f"The tehsils are selected by which ones fall inside {district_display}, "
                f"because the sub-district register still files them under the district "
                f"this one was carved out of. They cover {coverage * 100:.1f}% of it."
            )
            if coverage < 0.95:
                report.warning("tehsil coverage", note)
            else:
                report.info("tehsil coverage", note)

    if not blocks_available:
        # Some recently created districts have a district boundary published but
        # no block boundaries yet. Refusing outright would make those districts
        # unmappable, so the third panel shows the district on its own and says
        # so on the map. Asking to highlight a named block is still an error:
        # there is no polygon to highlight.
        if blocks:
            report.error(
                "block layer",
                f"No community development blocks are published for {district_display}, "
                f"so {', '.join(blocks)} cannot be highlighted. Clear the block "
                f"selection to map this district at district level instead.",
            )
            return report, None

        report.info(
            "block layer",
            f"No community development blocks are published for {district_display}. "
            f"The third panel shows the district on its own and says so on the map. "
            f"This affects districts created after the block layer was last updated.",
        )

    if unit_level == "block":
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
        unit_label=block_level_label,
    )

    # ---- Check 5: geometry validity and coverage ----------------------------
    _check_geometry(report, districts, f"districts of {state_display}")
    if blocks_available:
        _check_geometry(report, block_frame, f"{block_level_label}s of {district_display}")
    if unit_level == "block":
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
        blocks_available=blocks_available,
        unit_level=unit_level,
        unit_coverage=unit_coverage,
        district_names=chosen_names,
        target_district_keys=chosen_keys,
    )


def _sentence(text: str) -> str:
    """Capitalise the first letter only, leaving proper nouns inside intact."""
    return text[:1].upper() + text[1:]


def validate_coverage_request(
    *,
    areas: list[dict],
    sites: list[dict] | None = None,
    aliases: AliasTable,
    report: ValidationReport | None = None,
) -> tuple[ValidationReport, ResolvedTarget | None]:
    """Run the checks for a coverage map spanning several states.

    ``areas`` is one entry per state, each ``{"state": name, "districts": [..]}``.
    Every state is resolved against its own district layer and counted against
    its own LGD reference, so nothing is carried from one state to the next and
    a district name that exists in two states cannot be confused for the other.

    One state is not a special case of this. A single entry is handed to
    ``validate_request``, which already draws the state coverage map.
    """
    sites = sites or []
    report = report or ValidationReport()
    references = _load_reference_counts()

    cleaned: list[tuple[str, list[str]]] = []
    for area in areas or []:
        area = area or {}
        name = str(area.get("state") or "").strip()
        wanted = [
            str(d).strip() for d in (area.get("districts") or []) if str(d).strip()
        ]
        if name:
            cleaned.append((name, wanted))

    if not cleaned:
        report.error("states", "No states were chosen.")
        return report, None

    if len(cleaned) == 1:
        state_name, wanted = cleaned[0]
        return validate_request(
            state=state_name,
            districts=wanted,
            sites=sites,
            aliases=aliases,
            report=report,
        )

    parts: list[AreaPart] = []
    state_names: list[str] = []

    for state_name, wanted in cleaned:
        # ---- Check 1a, per state --------------------------------------------
        state_row = _resolve_state(state=state_name, aliases=aliases, report=report)
        if state_row is None:
            return report, None
        state_display = display(state_row["name"])

        if state_display in state_names:
            report.error("states", f"{state_display} was chosen more than once.")
            return report, None
        state_names.append(state_display)

        if not wanted:
            report.error(
                "district name",
                f"No district was chosen in {state_display}. Pick at least one "
                f"district in every state on the map, or remove {state_display}.",
            )
            return report, None

        districts = data_module.districts_of(state_row["lgd"])
        if districts.empty:
            report.error(
                "district layer",
                f"The district layer has no districts for {state_display}. "
                f"This state cannot be mapped until district data is added.",
            )
            return report, None

        # ---- Check 1b and 2, per state --------------------------------------
        resolved = _resolve_districts(
            wanted=wanted,
            districts=districts,
            state_display=state_display,
            aliases=aliases,
            report=report,
        )
        if resolved is None:
            return report, None
        keys, names, lgds = resolved

        _check_count(
            report=report,
            references=references,
            aliases=aliases,
            level="district",
            parent=state_display,
            observed_names=sorted(display(n) for n in districts["name"]),
            what=f"districts in {state_display}",
        )

        # ---- Check 5, per state ---------------------------------------------
        _check_geometry(report, districts, f"districts of {state_display}")

        parts.append(
            AreaPart(
                state_name=state_display,
                state_row=state_row,
                districts=districts,
                district_names=names,
                district_keys=keys,
                district_lgds=lgds,
            )
        )

    combined = gpd.GeoDataFrame(
        pd.concat([part.districts for part in parts], ignore_index=True),
        crs=parts[0].districts.crs,
    )
    target_lgds = [lgd for part in parts for lgd in part.district_lgds]
    chosen = combined[combined["lgd"].astype("int64").isin(target_lgds)]

    report.info(
        "states",
        f"{len(parts)} states chosen, so the map is one panel covering "
        f"{_join_names(state_names)} with "
        f"{len(target_lgds)} districts marked: "
        + "; ".join(
            f"{part.state_name} - {', '.join(part.district_names)}" for part in parts
        )
        + ".",
    )

    # ---- Check 4: every site inside one of the chosen districts -------------
    resolved_sites = _check_sites(
        report=report,
        sites=sites,
        district_row=_combined_row(chosen, _join_names(state_names)),
        district_display=f"the {len(target_lgds)} chosen districts",
        block_frame=chosen.iloc[0:0],
        stated_blocks=[],
        unit_label="district",
    )

    if report.errors:
        return report, None

    first = chosen.iloc[0]
    keys_seen: list[str] = []
    for part in parts:
        for key in part.district_keys:
            if key not in keys_seen:
                keys_seen.append(key)

    return report, ResolvedTarget(
        state_name=_join_names(state_names),
        state_key=name_key(state_names[0]),
        state_row=parts[0].state_row,
        district_name=display(first["name"]),
        district_lgd=first["lgd"],
        district_row=first,
        districts=combined,
        blocks=chosen.iloc[0:0],
        target_block_names=[],
        sites=resolved_sites,
        block_level_label="district",
        blocks_available=False,
        unit_level="none",
        unit_coverage=1.0,
        district_names=[name for part in parts for name in part.district_names],
        target_district_keys=keys_seen,
        area_parts=parts,
        target_district_lgds=[int(lgd) for lgd in target_lgds],
    )


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
        # Not having a reference is a gap in our records, not a fault in the
        # map, so it is reported but does not stop the render. A reference that
        # actively disagrees is a different matter and still warns below.
        report.info(
            f"{level} count",
            f"{observed} {level}s found. No independent reference is recorded for "
            f"{what}, so this count has not been cross-checked. Add a row to "
            f"data/lgd/reference_counts.csv to turn that check on.",
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


def _combined_row(chosen, state_display):
    """The chosen districts as one shape, for testing whether a site is in any of them."""
    return {
        "geometry": chosen.geometry.union_all(),
        "name": f"{len(chosen)} districts of {state_display}",
    }


def _check_sites(
    *, report, sites, district_row, district_display, block_frame, stated_blocks, unit_label="block"
):
    """Confirm each site falls inside the district and report its actual block."""
    if not sites:
        report.info("sites", "No site points given.")
        return []

    # Work in a metre-based CRS so distances mean something. When no block
    # layer exists the district itself defines the projection.
    district_series = gpd.GeoSeries([district_row["geometry"]], crs=block_frame.crs)
    have_blocks = not block_frame.empty
    metric = block_frame.estimate_utm_crs() if have_blocks else district_series.estimate_utm_crs()
    blocks_m = block_frame.to_crs(metric) if have_blocks else block_frame
    district_m = district_series.to_crs(metric).iloc[0]

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

        actual_block = None
        if have_blocks:
            hit = blocks_m[blocks_m.geometry.contains(point_m)]
            actual_block = display(hit.iloc[0]["name"]) if len(hit) else None

        if not have_blocks:
            report.info(
                "site location",
                f"{name} is inside {district_display} district. There is no "
                f"{unit_label} layer for this district, so no {unit_label} can be named.",
            )
        elif actual_block is None:
            report.warning(
                "site location",
                f"{name} is inside {district_display} district but not inside any "
                f"{unit_label} polygon. It may sit in a municipal area the "
                f"{unit_label} layer excludes.",
            )
        elif stated_keys and name_key(actual_block) not in stated_keys:
            stated_list = ", ".join(display(b) for b in stated_blocks)
            report.warning(
                "site location",
                f"{name} falls in {actual_block} {unit_label}, not {stated_list}. "
                f"Either highlight {actual_block} instead, or keep the current "
                f"highlight if the site serves {stated_list}.",
            )
        else:
            report.info(
                "site location", f"{name} falls in {actual_block} {unit_label}, as stated."
            )

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
