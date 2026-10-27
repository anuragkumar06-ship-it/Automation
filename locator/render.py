"""Draw the three-panel locator map.

Panels run left to right: India with the target state highlighted, the state
with the target district highlighted, then the district with the target
block(s) highlighted and any site points marked.

Three decisions shape how this looks.

**Detail callouts, not arrows.** Each panel carries a thin teal box around the
area the next panel enlarges, with two light lines running from that box to the
corners of the next panel. This is the convention an atlas uses for an inset. A
single arrow across the gap read as a stray diagonal.

**Tiered labels.** The target unit is the loud one. Every other unit is set
smaller and in a grey that sits behind it, and in the default ``auto`` density a
unit too small to carry a label without a tangle of leader lines does not get
one. How many were left off is recorded in the render log, so nothing is
quietly dropped.

**Page structure.** A title with a rule under it, panels on a light ground
inside hairline frames, captions with their own short rules, then the legend and
the source line. The height of the figure follows the shapes being drawn.

Every polygon comes from a layer loaded by :mod:`locator.data`. Simplification
stays below one printed pixel at 600 dpi, so shapes never visibly change.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import geopandas as gpd
import matplotlib
import pandas as pd
from shapely.geometry import Point

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import ConnectionPatch, Rectangle  # noqa: E402

from . import data as data_module  # noqa: E402
from .names import display  # noqa: E402
from .style import Brand, india_lcc, local_crs  # noqa: E402

__all__ = ["render_map", "RenderResult", "slug"]

# Simplification per panel, in metres. One printed pixel at 600 dpi across a
# 3.5 inch panel is roughly 1.4 km for India, 160 m for a state and 25 m for a
# district, so each tolerance below sits well under a visible change.
SIMPLIFY_INDIA_M = 400
SIMPLIFY_STATE_M = 60
SIMPLIFY_DISTRICT_M = 10

# Neighbouring states are background context, so they are thinned hard before
# the adjacency test. Comparing full-resolution coastlines against every state
# is the single most expensive thing this module could do.
NEIGHBOUR_SIMPLIFY_M = 500

# adjustText stops after a one second time limit unless it is told otherwise,
# which makes label positions depend on how busy the machine is. Pinning the
# iteration count instead is what makes two runs produce the same picture.
LABEL_ITERATIONS = 260

# Fraction of panel height kept clear at the bottom for the scale bar.
SCALE_BAND = 0.10
# Breathing room around the mapped area.
EXTENT_PAD = 0.02

# The tallest a single-map panel is allowed to be, so a tall state does not
# produce a page nobody can look at whole.
COVERAGE_MAX_HEIGHT_IN = 6.4

# Once a widened coverage frame reaches this share of the country's width it
# is treated as a national view and the whole country is shown.
COUNTRY_SNAP = 0.8
COVERAGE_MIN_WIDTH_IN = 8.6

# How tall a single panel is drawn when written out on its own.
PANEL_ALONE_HEIGHT_IN = 5.6

# On the map across states, sizes on paper in points (1 mm is 2.83 pt).
#
# Block boundaries inside a covered district are drawn only when the median
# block is at least this wide. Across India a block is under a millimetre, and
# the white lines bury the district's own colour until it reads as a scribble.
SUBLAYER_MIN_PT = 6.0
# A covered district drawn smaller than this also gets a dot, so it cannot
# vanish at national scale. Kolkata is about half a millimetre across.
SMALL_MARK_PT = 6.0
# Parts of a chosen state smaller than this are left out of its outline. The
# outline is drawn heavier than a border, and round an island or an enclave
# it prints as a dark speck rather than a shape.
RIM_MIN_PT = 3.0
# Space kept between a placed label and anything it must not touch.
CALLOUT_CLEAR_PT = 1.5
# How far out a label is tried from what it names, nearest first.
CALLOUT_GAPS_PT = (2.5, 5, 9, 14, 21, 30, 42, 58, 80)
# Positions tried round each ring.
CALLOUT_STEPS = 32
# A label is moved this far before a line is drawn back to what it names.
CALLOUT_LEADER_PT = 6.0

# Fixed bands, in inches, for the title block above the panels and for the
# legend plus source line below them. Keeping these in inches rather than as a
# fraction means type stays the same size whatever height the panels come out.
BAND_TOP_IN = 0.95
BAND_BOTTOM_IN = 0.80


@dataclass
class RenderResult:
    files: list[Path]
    figure_size: tuple[float, float]
    notes: list[str]


@dataclass
class Panel:
    """One prepared panel: its geometry, extent and how it should be drawn."""

    kind: str
    caption: str
    frame: gpd.GeoDataFrame
    crs: object
    highlight_mask: object
    highlight_colours: list[str]
    extent: tuple[float, float, float, float]
    context: gpd.GeoDataFrame | None = None
    label_frame: gpd.GeoDataFrame | None = None
    sites: list[dict] = field(default_factory=list)
    ax: object = None
    labels_skipped: int = 0
    footnote: str | None = None
    outline_only: bool = False
    unit_label: str = "block"
    # Larger areas the panel covers, named so a reader can tell them apart.
    # Used by the multi-state coverage map to label the states themselves.
    area_labels: gpd.GeoDataFrame | None = None
    # Finer units drawn inside the highlighted ones and never labelled. The
    # coverage map uses this to show the blocks of a marked district: at that
    # scale they are a texture, not something a name could be read off.
    sublayer: gpd.GeoDataFrame | None = None
    sublayer_mask: object = None
    # Overrides the brand's label density for this panel only.
    label_density: str | None = None
    # Fill for the units that are not highlighted. The multi-state coverage
    # map washes them in the pale accent, so a chosen state reads as chosen
    # rather than as more grey country.
    other_fill: str | None = None
    # Labels placed one at a time into clear space, each with a leader line
    # back to what it names. Used on the map across states, where a district
    # is a few millimetres wide and a label started on top of it ends up
    # across a coastline or a state border.
    callouts: bool = False
    # The districts named on a callout map, by LGD code. A state marked whole
    # fills its districts too, but they are not named; the state is.
    covered_lgds: list[int] = field(default_factory=list)
    whole_state_lgds: list[int] = field(default_factory=list)
    # Covered districts too small to see at this scale, given a dot as well.
    dotted: int = 0

    @property
    def aspect(self) -> float:
        x0, x1, y0, y1 = self.extent
        return (x1 - x0) / (y1 - y0)


def render_map(*, target, config: dict, brand: Brand, report, output_dir: Path) -> RenderResult:
    """Render the map and write SVG, PDF and PNG files plus a render log."""
    output_dir.mkdir(parents=True, exist_ok=True)

    if getattr(target, "multi_district", False):
        # Several districts picked: the third panel has nothing to show, so the
        # map is the state with each of them marked. This is how programme
        # coverage across a state gets shown.
        return _render_coverage(
            target=target, config=config, brand=brand, output_dir=output_dir
        )

    notes: list[str] = []

    plt.rcParams["font.family"] = brand.font_family
    plt.rcParams["svg.fonttype"] = "none"  # keep text selectable in the SVG
    plt.rcParams["pdf.fonttype"] = 42  # embed TrueType so the PDF stays editable

    panels = _prepare_panels(target, brand)

    width = brand.layout("figure_width_in")
    max_height = brand.layout("figure_height_in")
    margin = brand.layout("margin_in")
    gap = brand.layout("panel_gap_in")

    available_w = width - 2 * margin - 2 * gap
    available_h = max_height - BAND_TOP_IN - BAND_BOTTOM_IN

    panel_h, panel_widths = _allocate(
        [p.aspect for p in panels], available_w=available_w, available_h=available_h
    )

    # How tall the three panels turn out depends on how wide their shapes are:
    # a wide state such as Bihar forces shorter panels than a narrow one such as
    # Tamil Nadu. The figure is trimmed to fit rather than left with a band of
    # empty paper, so the image drops into a document at a sensible size.
    height = panel_h + BAND_TOP_IN + BAND_BOTTOM_IN

    figure = plt.figure(figsize=(width, height), facecolor=brand.background)

    cursor = margin
    for panel, panel_w in zip(panels, panel_widths):
        panel.ax = figure.add_axes(
            [cursor / width, BAND_BOTTOM_IN / height, panel_w / width, panel_h / height],
            facecolor=brand.panel_fill,
        )
        cursor += panel_w + gap

    for panel in panels:
        _draw_panel(panel, brand)

    # Callouts are drawn once every panel has its final limits, because the box
    # on one panel is the extent of the next.
    _draw_callout(figure, panels[0], panels[1], brand)
    _draw_callout(figure, panels[1], panels[2], brand)

    title = config.get("title") or f"{target.district_name} district, {target.state_name}"
    # The rule stops short of the logo rather than running under it, which the
    # brand guide treats as competing with the logo for attention.
    rule_right = width - margin
    if brand.show_logo and brand.logo_position.startswith("top") and brand.logo_position.endswith("right"):
        rule_right = width - margin - brand.logo_width_in - brand.logo_clear_space_in
    _draw_title_block(
        figure, title, brand, margin=margin, width=width, height=height, rule_right=rule_right
    )
    _draw_legend(figure, panels[2], brand, target=target)

    if brand.show_logo:
        _draw_logo(figure, brand, margin=margin, width=width, height=height)

    source_line = _source_line()
    figure.text(
        margin / width,
        0.22 / height,
        source_line,
        ha="left",
        va="center",
        fontsize=brand.size("source_line"),
        color=brand.text_muted,
    )

    name = config.get("output_name") or "locator_map"
    files = _write_figure(figure, output_dir, name)

    # Each panel on its own as well as the strip, so a proposal can use just
    # the district map without cropping the other two off by hand.
    panel_files, panel_figures = _write_panels_separately(
        panels, config=config, brand=brand, output_dir=output_dir, name=name,
        target=target,
    )
    files += panel_files

    # And everything in one PDF, in reading order, for sending as a single
    # attachment. The figures stay open until it is written.
    bundle = [figure] + panel_figures
    if len(bundle) > 1:
        files.append(_write_bundle(bundle, output_dir, f"{name}_all_maps"))
    for drawn in bundle:
        plt.close(drawn)

    notes.append(f"Source line: {source_line}")
    notes.append(
        f"Simplification: India {SIMPLIFY_INDIA_M} m, state {SIMPLIFY_STATE_M} m, "
        f"district {SIMPLIFY_DISTRICT_M} m (all below one pixel at 600 dpi)."
    )
    notes.append(f"India panel projection: Lambert conformal conic, {india_lcc()}")
    notes.append(f"State panel projection: {panels[1].crs.to_string()}")
    notes.append(f"District panel projection: {panels[2].crs.to_string()}")
    notes.append(
        "Panel widths (inches): "
        + ", ".join(f"{p.kind} {w:.2f}" for p, w in zip(panels, panel_widths))
        + f"; shared height {panel_h:.2f}"
    )
    density_note = f"Label density: {brand.label_density}"
    if brand.label_density == "auto":
        density_note += f" (minimum drawn size {brand.label_min_points:g} pt)"
    notes.append(density_note)
    for panel in panels:
        if panel.labels_skipped:
            notes.append(
                f"  {panel.kind} panel: {panel.labels_skipped} unit(s) left unlabelled, "
                f"too small to label legibly at this size"
            )
    notes.append(f"Label layout: {LABEL_ITERATIONS} fixed iterations (not time limited).")
    notes.append(f"Font used: {brand.font_family}.")

    return RenderResult(files=files, figure_size=(width, height), notes=notes)


def _render_coverage(*, target, config: dict, brand: Brand, output_dir: Path) -> RenderResult:
    """One state, with several districts marked. A coverage map, not a locator.

    Same data, same checks, same brand as the three-panel map; it simply
    answers a different question - not "where is this one place" but "where
    across this state are we working".
    """
    notes: list[str] = []

    plt.rcParams["font.family"] = brand.font_family
    plt.rcParams["svg.fonttype"] = "none"
    plt.rcParams["pdf.fonttype"] = 42

    multi_state = getattr(target, "multi_state", False)

    districts = target.districts.copy()
    # One state sits inside a single UTM zone, which keeps its shape truest.
    # Several states can span a third of the country, and one zone stretches
    # whatever falls near its edges - so a multi-state map moves to the
    # conformal conic the India panel uses, which holds shape across that
    # span. Raw latitude and longitude is still never plotted.
    crs = india_lcc() if multi_state else local_crs(districts)
    districts = districts.to_crs(crs)
    districts["geometry"] = districts.geometry.simplify(
        SIMPLIFY_STATE_M, preserve_topology=True
    )
    districts = _repair(districts)

    whole_parts = list(getattr(target, "whole_states", []))
    whole_lgds = [int(part.state_row["lgd"]) for part in whole_parts]
    only_whole = bool(whole_parts) and len(whole_parts) == len(target.area_parts)

    if multi_state:
        # Marked by LGD code, not by name. A district name is only unique
        # within its own state, and two chosen states can share one.
        mask = districts["lgd"].astype("int64").isin(target.target_district_lgds)
        if whole_lgds:
            # A state marked whole is every one of its districts.
            mask = mask | districts["state_lgd"].astype("int64").isin(whole_lgds)
    else:
        mask = districts["name_key"].isin(target.target_district_keys)

    margin = brand.layout("margin_in")

    context = None
    area_labels = None
    sublayer = None
    sublayer_mask = None
    extent = _extent(districts.total_bounds)
    if multi_state:
        sublayer, sublayer_mask = _coverage_sublayer(target, crs)
        context, area_labels, country = _coverage_context(target, crs)
        if only_whole:
            # Nothing finer than a state is marked, so the question the map
            # answers is where in India these states are: the whole country.
            extent = _extent(country)
        else:
            extent = _widen_extent(
                extent,
                min_aspect=(brand.layout("figure_width_in") - 2 * margin)
                / COVERAGE_MAX_HEIGHT_IN,
                limit=country,
            )

    panel = Panel(
        kind="coverage",
        # No caption: the title above already names the states, and a single
        # map does not need labelling twice.
        caption="",
        frame=districts,
        crs=crs,
        highlight_mask=mask,
        # Deeper where the state around them is washed in the pale tint, so a
        # covered district reads against its own state rather than into it.
        highlight_colours=[brand.highlight_deep if multi_state else brand.highlight],
        extent=extent,
        # On a one-state map neighbouring states fill the frame with grey and
        # crowd the thing the map is about. Across several states they are the
        # opposite - without them, two states that do not touch leave white
        # paper between them where the country should be.
        context=context,
        area_labels=area_labels,
        sublayer=sublayer,
        sublayer_mask=sublayer_mask,
        # The chosen states in a pale wash of the accent, so they read as the
        # states the programme runs in rather than as more grey country.
        other_fill=brand.highlight_pale if multi_state else None,
        # Only the districts the programme runs in are named. Three states'
        # worth of district labels is unreadable at A4, and the question this
        # map answers is where the work is, not what every district is called.
        label_density="target_only" if multi_state else None,
        sites=target.sites,
        callouts=multi_state,
        covered_lgds=[int(v) for v in target.target_district_lgds] if multi_state else [],
        whole_state_lgds=whole_lgds,
    )

    # Fit inside both dimensions. Sizing on width alone made a tall state such
    # as Karnataka come out nearly a metre high.
    available_w = brand.layout("figure_width_in") - 2 * margin
    panel_h = min(COVERAGE_MAX_HEIGHT_IN, available_w / panel.aspect)
    panel_w = panel_h * panel.aspect

    # Block boundaries only where a block is big enough on paper to read as a
    # shape. Below that they are a white scribble over the district's colour,
    # and the district's own map is where the blocks are shown anyway.
    blocks_hidden = False
    if panel.sublayer is not None and len(panel.sublayer):
        per_unit = panel_w * 72 / (panel.extent[1] - panel.extent[0])
        median_pt = float(panel.sublayer.geometry.area.pow(0.5).median()) * per_unit
        if median_pt < SUBLAYER_MIN_PT:
            blocks_hidden = True
            panel.sublayer = None
            panel.sublayer_mask = None
            notes.append(
                f"Block boundaries left off the overview: the median block is "
                f"{median_pt / 2.83:.1f} mm across at this scale, too small to read "
                f"as a shape. Each district's own map shows them."
            )

    # The page is then trimmed to the map rather than left at A4 width, which
    # for a portrait state left two thirds of the sheet empty. The floor is
    # what the title and the source line need to sit on one line each.
    width = max(panel_w + 2 * margin, COVERAGE_MIN_WIDTH_IN)
    height = panel_h + BAND_TOP_IN + BAND_BOTTOM_IN

    figure = plt.figure(figsize=(width, height), facecolor=brand.background)
    panel.ax = figure.add_axes(
        [margin / width, BAND_BOTTOM_IN / height, panel_w / width, panel_h / height],
        facecolor=brand.panel_fill,
    )
    _draw_panel(panel, brand)

    # Sentence case, and it says which states and what kind of map, the way
    # the three-panel titles do.
    if only_whole and len(whole_parts) == 1:
        default_title = f"{target.state_name} on the map of India"
    elif only_whole:
        default_title = f"States covered: {target.state_name}"
    elif whole_parts:
        default_title = f"Coverage across {target.state_name}"
    elif multi_state:
        default_title = f"Districts across {target.state_name}"
    else:
        default_title = f"{target.state_name} district map"
    title = config.get("title") or default_title
    _draw_title_block(
        figure,
        title,
        brand,
        margin=margin,
        width=width,
        height=height,
        rule_right=(
            width - margin - brand.logo_width_in - brand.logo_clear_space_in
            if brand.show_logo and brand.logo_position == "top-right"
            else None
        ),
    )
    _draw_coverage_legend(
        figure, panel, brand, target=target, blocks_elsewhere=blocks_hidden
    )

    if brand.show_logo:
        _draw_logo(figure, brand, margin=margin, width=width, height=height)

    source_line = _source_line()
    figure.text(
        margin / width,
        0.22 / height,
        source_line,
        ha="left",
        va="center",
        fontsize=brand.size("source_line"),
        color=brand.text_muted,
    )

    name = config.get("output_name") or "coverage_map"
    files = _write_figure(figure, output_dir, name)
    bundle = [figure]

    # Then a map per chosen district, at the only scale a block can be named
    # at. The overview above shows where the work is; these show what it is.
    if multi_state and getattr(target, "district_details", []):
        detail_files, detail_figures = _write_detail_maps(
            target, config=config, brand=brand, output_dir=output_dir, name=name
        )
        files += detail_files
        bundle += detail_figures

    # The overview first, then each district, in one PDF.
    if len(bundle) > 1:
        files.append(_write_bundle(bundle, output_dir, f"{name}_all_maps"))
    for drawn in bundle:
        plt.close(drawn)

    notes.append(f"Source line: {source_line}")
    if multi_state:
        notes.append(
            f"Map type: coverage across states, {len(target.target_district_lgds)} "
            f"districts and {len(whole_parts)} whole states marked across "
            f"{len(target.area_parts)} states."
        )
        for part in target.area_parts:
            if part.whole:
                notes.append(f"{part.state_name}: marked whole, no district chosen.")
            else:
                notes.append(
                    f"Districts marked in {part.state_name}: "
                    + ", ".join(part.district_names)
                )
        notes.append(
            "Only the marked districts and the chosen states are labelled, each "
            "placed clear of borders and coastlines with a leader line where it "
            "had to move away; three states of district labels does not stay "
            "legible at A4."
        )
        if panel.dotted:
            notes.append(
                f"{panel.dotted} covered district(s) too small to see at this scale "
                f"are also marked with a dot."
            )
        details = getattr(target, "district_details", [])
        if details:
            drawn = sum(len(d.units) for d in details if d.units_available)
            where = (
                "left off this overview"
                if blocks_hidden
                else "drawn inside the marked districts, unlabelled at this scale"
            )
            notes.append(
                f"Block detail: {drawn} units {where}, and one map per district "
                f"written beside this one ({len(details)} of them)."
            )
            for detail in details:
                if not detail.units_available:
                    notes.append(
                        f"{detail.district_name}: no blocks published, mapped at "
                        f"district level."
                    )
                    continue
                marked = ", ".join(display(n) for n in detail.marked_names) or "none"
                notes.append(
                    f"{detail.district_name}: {len(detail.units)} "
                    f"{detail.unit_label}s, marked: {marked}."
                )
    else:
        notes.append(
            f"Map type: state coverage, {len(target.target_district_keys)} of "
            f"{len(districts)} districts marked."
        )
        notes.append("Districts marked: " + ", ".join(target.district_names))
    # india_lcc() hands back a proj string; local_crs() a CRS object.
    notes.append(f"Projection: {crs if isinstance(crs, str) else crs.to_string()}")
    notes.append(f"Font used: {brand.font_family}.")
    return RenderResult(files=files, figure_size=(width, height), notes=notes)


def _write_panels_separately(
    panels, *, config, brand: Brand, output_dir: Path, name: str, target=None
):
    """Write each panel out as its own map, beside the three-panel strip.

    Redrawn rather than cropped, so each one gets its own title, logo, scale
    bar and source line and stands on its own in a document.

    Returns the files written and the figures, which are left open so they can
    go into the combined PDF before being closed.
    """
    written: list[Path] = []
    drawn: list = []
    margin = brand.layout("margin_in")
    overall = config.get("title") or ""

    for panel in panels:
        panel_h = min(COVERAGE_MAX_HEIGHT_IN, PANEL_ALONE_HEIGHT_IN)
        panel_w = panel_h * panel.aspect
        width = max(panel_w + 2 * margin, COVERAGE_MIN_WIDTH_IN)
        height = panel_h + BAND_TOP_IN + BAND_BOTTOM_IN

        figure = plt.figure(figsize=(width, height), facecolor=brand.background)
        panel.ax = figure.add_axes(
            [margin / width, BAND_BOTTOM_IN / height, panel_w / width, panel_h / height],
            facecolor=brand.panel_fill,
        )
        caption, panel.caption = panel.caption, ""  # the title says it instead
        _draw_panel(panel, brand)
        panel.caption = caption

        # On its own, a panel has to say what it is without the other two
        # beside it to explain it. "Tamil Nadu" alone does not tell a reader
        # they are looking at that state's districts.
        standalone = {
            "india": "India: states and union territories",
            "state": f"{caption} district map",
            "district": f"{caption}",
        }.get(panel.kind, caption)
        title = standalone if not overall else f"{standalone} — {overall}"
        _draw_title_block(
            figure,
            title,
            brand,
            margin=margin,
            width=width,
            height=height,
            rule_right=(
                width - margin - brand.logo_width_in - brand.logo_clear_space_in
                if brand.show_logo and brand.logo_position == "top-right"
                else None
            ),
        )
        # The district panel is the one carrying a highlight and site markers,
        # so it is the one that needs a key to read them by.
        if target is not None and panel.kind == "district":
            _draw_legend(figure, panel, brand, target=target)

        if brand.show_logo:
            _draw_logo(figure, brand, margin=margin, width=width, height=height)

        figure.text(
            margin / width,
            0.22 / height,
            _source_line(),
            ha="left",
            va="center",
            fontsize=brand.size("source_line"),
            color=brand.text_muted,
        )

        written += _write_figure(figure, output_dir, f"{name}_{panel.kind}")
        drawn.append(figure)

    return written, drawn


def _coverage_context(target, crs):
    """The rest of the country behind a multi-state coverage panel.

    Returns the states that are not on the map, to be drawn in the context
    grey and left unlabelled, and the chosen states, which are named. Both
    come from the same official state layer the India panel uses, so the
    external boundary is the official depiction here too.
    """
    states = data_module.load_states()
    states = states[~states["disputed"]].to_crs(crs)
    states = states.copy()
    states["geometry"] = states.geometry.simplify(
        SIMPLIFY_INDIA_M, preserve_topology=True
    )
    states = _repair(states)

    chosen = [int(part.state_row["lgd"]) for part in target.area_parts]
    codes = states["lgd"].astype("int64")
    return states[~codes.isin(chosen)], states[codes.isin(chosen)], states.total_bounds


def _coverage_sublayer(target, crs):
    """The blocks of every marked district, for drawing inside the highlights.

    Returns the units and a mask of the ones chosen, or ``(None, None)`` when
    no block detail was worked out. Districts whose blocks are not published
    simply contribute nothing, which leaves them a plain filled shape.
    """
    details = [d for d in getattr(target, "district_details", []) if d.units_available]
    if not details:
        return None, None

    frames = []
    for detail in details:
        units = detail.units.copy()
        units["is_marked"] = units["name"].isin(detail.marked_names)
        frames.append(units[["name", "is_marked", "geometry"]])

    units = gpd.GeoDataFrame(
        pd.concat(frames, ignore_index=True), crs=frames[0].crs
    ).to_crs(crs)
    units["geometry"] = units.geometry.simplify(
        SIMPLIFY_STATE_M, preserve_topology=True
    )
    units = _repair(units)
    return units, units["is_marked"]


def _detail_panels(target, brand: Brand):
    """One district-scale panel per chosen district, where blocks are legible.

    A block is about 16 km across. On a map spanning several states that is
    around a millimetre; on a map of its own district it is 40, which is what
    makes the difference between a boundary you can see and a name you can
    read.
    """
    built = []
    for detail in getattr(target, "district_details", []):
        if detail.units_available:
            units = detail.units.copy()
            crs = local_crs(units)
            units = units.to_crs(crs)
            units["geometry"] = units.geometry.simplify(
                SIMPLIFY_DISTRICT_M, preserve_topology=True
            )
            units = _repair(units)

            mask = units["name"].isin(detail.marked_names)
            panel = Panel(
                kind="district",
                caption=f"{detail.district_name} district",
                frame=units,
                crs=crs,
                highlight_mask=mask,
                highlight_colours=(
                    brand.highlight_colours(int(mask.sum())) or [brand.highlight]
                ),
                extent=_extent(units.total_bounds),
                sites=detail.sites,
                unit_label=detail.unit_label,
                footnote=(
                    None
                    if detail.unit_level == "block"
                    else (
                        "Sub-districts (tehsils) shown: block boundaries are not "
                        f"published for this district. They cover "
                        f"{detail.unit_coverage * 100:.0f}% of it."
                    )
                ),
            )
        else:
            # No block layer for this district. The map shows the district on
            # its own, outlined, and says why on its face - the same answer
            # the three-panel map gives.
            outline = gpd.GeoDataFrame(
                {
                    "name": [detail.district_name],
                    "geometry": [detail.district_row["geometry"]],
                },
                crs=target.districts.crs,
            )
            crs = local_crs(outline)
            outline = outline.to_crs(crs)
            outline["geometry"] = outline.geometry.simplify(
                SIMPLIFY_DISTRICT_M, preserve_topology=True
            )
            outline = _repair(outline)

            panel = Panel(
                kind="district",
                caption=f"{detail.district_name} district",
                frame=outline,
                crs=crs,
                highlight_mask=outline["name"].isin([]),
                highlight_colours=[brand.highlight],
                extent=_extent(outline.total_bounds),
                sites=detail.sites,
                footnote="Block boundaries are not published for this district.",
                outline_only=True,
                unit_label=detail.unit_label,
            )
        built.append((detail, panel))
    return built


def _write_detail_maps(target, *, config, brand: Brand, output_dir: Path, name: str):
    """Write a block map for each chosen district, beside the overview.

    Returns the files written and the figures, left open for the combined PDF.
    """
    written: list[Path] = []
    drawn: list = []
    margin = brand.layout("margin_in")
    overall = config.get("title") or ""

    for detail, panel in _detail_panels(target, brand):
        panel_h = min(COVERAGE_MAX_HEIGHT_IN, PANEL_ALONE_HEIGHT_IN)
        panel_w = panel_h * panel.aspect
        width = max(panel_w + 2 * margin, COVERAGE_MIN_WIDTH_IN)
        height = panel_h + BAND_TOP_IN + BAND_BOTTOM_IN

        figure = plt.figure(figsize=(width, height), facecolor=brand.background)
        panel.ax = figure.add_axes(
            [margin / width, BAND_BOTTOM_IN / height, panel_w / width, panel_h / height],
            facecolor=brand.panel_fill,
        )
        caption, panel.caption = panel.caption, ""  # the title says it instead
        _draw_panel(panel, brand)
        panel.caption = caption

        # Names the district, its state and what is being shown, because this
        # sheet travels on its own.
        title = (
            f"{detail.district_name} district, {detail.state_name}: "
            f"{detail.unit_label}s"
            if detail.units_available
            else f"{detail.district_name} district, {detail.state_name}"
        )
        if overall:
            title = f"{title} — {overall}"

        _draw_title_block(
            figure,
            title,
            brand,
            margin=margin,
            width=width,
            height=height,
            rule_right=(
                width - margin - brand.logo_width_in - brand.logo_clear_space_in
                if brand.show_logo and brand.logo_position == "top-right"
                else None
            ),
        )
        _draw_detail_legend(figure, panel, brand, detail=detail)

        if brand.show_logo:
            _draw_logo(figure, brand, margin=margin, width=width, height=height)

        figure.text(
            margin / width,
            0.22 / height,
            _source_line(),
            ha="left",
            va="center",
            fontsize=brand.size("source_line"),
            color=brand.text_muted,
        )

        written += _write_figure(figure, output_dir, f"{name}_{slug(detail.district_name)}")
        drawn.append(figure)

    return written, drawn


def slug(value: str) -> str:
    """A file-name-safe form of a place name."""
    kept = [c.lower() if c.isalnum() else "_" for c in str(value)]
    return "".join(kept).strip("_").replace("__", "_") or "district"


def _draw_detail_legend(figure, panel: Panel, brand: Brand, *, detail) -> None:
    """Legend for one district's block map."""
    handles = []
    if panel.outline_only:
        handles.append(
            Line2D([], [], marker="s", linestyle="none", markerfacecolor="none",
                   markeredgecolor=brand.highlight, markeredgewidth=1.4,
                   color="none", markersize=6,
                   label=f"{detail.district_name} district")
        )
    else:
        for name, colour in zip(detail.marked_names, panel.highlight_colours):
            handles.append(
                Line2D([], [], marker="s", linestyle="none", color=colour,
                       markersize=6, label=f"{display(name)} {panel.unit_label}")
            )
        handles.append(
            Line2D([], [], marker="s", linestyle="none", color=brand.unit_fill,
                   markersize=6,
                   label=f"Other {panel.unit_label}s"
                   if detail.marked_names
                   else f"{panel.unit_label.capitalize()}s")
        )

    seen = set()
    for site in panel.sites:
        site_type = (site.get("type") or "site").lower()
        if site_type in seen:
            continue
        seen.add(site_type)
        handles.append(
            Line2D([], [], marker=brand.marker(site_type), linestyle="none",
                   color=brand.site_marker, markersize=5,
                   label=site_type[:1].upper() + site_type[1:])
        )

    if not handles:
        return

    box = panel.ax.get_position()
    legend = figure.legend(
        handles=handles,
        loc="upper left",
        bbox_to_anchor=(box.x0, box.y0 - 0.022),
        frameon=False,
        fontsize=brand.size("legend"),
        handletextpad=0.6,
        labelspacing=0.4,
        borderpad=0.0,
        ncols=min(len(handles), 3),
        columnspacing=1.5,
    )
    for text in legend.get_texts():
        text.set_color(brand.text_secondary)


def _widen_extent(extent, *, min_aspect, limit=None):
    """Widen a tight extent so the sheet is not a ribbon of white paper.

    States scattered down the country give a tall, narrow bounding box. Framed
    on that alone the map comes out a strip a third of the page wide, and the
    land around it is cut to a rectangle that reads as a crop rather than a
    map. The frame is opened out sideways to the page's own proportions, and
    never past the country's own bounds, so the space gained is filled with
    real geography instead of sea.
    """
    x0, x1, y0, y1 = extent
    width, height = x1 - x0, y1 - y0
    if height <= 0 or width <= 0 or width / height >= min_aspect:
        return extent

    wanted = height * min_aspect
    if limit is not None:
        wanted = min(wanted, max(limit[2] - limit[0], width))

    grow = (wanted - width) / 2
    x0, x1 = x0 - grow, x1 + grow

    if limit is not None and (x1 - x0) >= COUNTRY_SNAP * (limit[2] - limit[0]):
        # Opened out this far the frame is a national one, and a frame that
        # wide but cut off above the northernmost state slices the outline
        # across the north. At this scale the country is shown whole, with the
        # external boundary as the official depiction has it.
        return _extent(limit)

    if limit is not None:
        # Slide back inside the country rather than hang off one side of it.
        if x0 < limit[0]:
            x1 += limit[0] - x0
            x0 = limit[0]
        if x1 > limit[2]:
            x0 -= x1 - limit[2]
            x1 = limit[2]
    return (x0, x1, y0, y1)


def _draw_coverage_legend(
    figure, panel: Panel, brand: Brand, *, target, blocks_elsewhere: bool = False
) -> None:
    """Marked against not marked, plus any site types used.

    Every entry describes something actually drawn: a map of whole states has
    no pale districts to explain, and a map that left the block boundaries off
    says where they are instead.
    """
    covered_colour = (
        panel.highlight_colours[0] if panel.highlight_colours else brand.highlight
    )
    any_districts = bool(panel.covered_lgds) or not panel.callouts
    if panel.whole_state_lgds and any_districts:
        covered = "States and districts covered"
    elif panel.whole_state_lgds:
        covered = "States covered" if len(panel.whole_state_lgds) > 1 else "State covered"
    else:
        covered = "Districts covered"
    handles = [
        Line2D([], [], marker="s", linestyle="none", color=covered_colour,
               markersize=6, label=covered),
    ]
    if panel.dotted:
        handles.append(
            Line2D([], [], marker="o", linestyle="none", color=covered_colour,
                   markeredgecolor=brand.background, markeredgewidth=0.6,
                   markersize=5, label="District covered, too small to see at this scale")
        )
    if bool((~panel.highlight_mask).any()):
        handles.append(
            Line2D([], [], marker="s", linestyle="none",
                   color=panel.other_fill or brand.unit_fill, markersize=6,
                   label="Other districts in these states"
                   if panel.other_fill
                   else "Other districts")
        )
    if blocks_elsewhere:
        handles.append(
            Line2D([], [], marker="none", linestyle="none", color="none",
                   label="Blocks are shown on each district's own map")
        )
    if panel.sublayer is not None and len(panel.sublayer):
        if panel.sublayer_mask is not None and bool(panel.sublayer_mask.any()):
            handles.insert(
                1,
                Line2D([], [], marker="s", linestyle="none",
                       color=brand.highlight_secondary, markersize=6,
                       label="Blocks covered"),
            )
        handles.append(
            Line2D([], [], marker="_", linestyle="none", color=brand.text_muted,
                   markersize=7, label="Block boundaries (named on each district map)")
        )
    if panel.context is not None and not panel.context.empty:
        # Across several states the paler grey behind them is the rest of the
        # country, which is a different thing from a district not covered.
        handles.append(
            Line2D([], [], marker="s", linestyle="none", color=brand.context_fill,
                   markersize=6, label="Other states")
        )
    seen = set()
    for site in panel.sites:
        site_type = (site.get("type") or "site").lower()
        if site_type in seen:
            continue
        seen.add(site_type)
        handles.append(
            Line2D([], [], marker=brand.marker(site_type), linestyle="none",
                   color=brand.site_marker, markersize=5,
                   label=site_type[:1].upper() + site_type[1:])
        )

    box = panel.ax.get_position()
    legend = figure.legend(
        handles=handles,
        loc="upper left",
        bbox_to_anchor=(box.x0, box.y0 - 0.022),
        frameon=False,
        fontsize=brand.size("legend"),
        handletextpad=0.6,
        labelspacing=0.4,
        borderpad=0.0,
        ncols=min(len(handles), 3),
        columnspacing=1.5,
    )
    for text in legend.get_texts():
        text.set_color(brand.text_secondary)


def _write_bundle(figures, output_dir: Path, name: str) -> Path:
    """Every map of one job in a single PDF, in reading order.

    One file to attach to an email or drop into a proposal, instead of a
    folder of them. Each map keeps its own page size, because they are
    different shapes and forcing them onto one page size would either letterbox
    them or distort them.
    """
    from matplotlib.backends.backend_pdf import PdfPages

    path = output_dir / f"{name}.pdf"
    with PdfPages(path) as pdf:
        for figure in figures:
            pdf.savefig(figure)
    return path


def _write_figure(figure, output_dir: Path, name: str) -> list[Path]:
    """Write one figure out in every format, vector first."""
    files: list[Path] = []
    for path, kwargs in [
        (output_dir / f"{name}.svg", {}),
        (output_dir / f"{name}.pdf", {}),
        (output_dir / f"{name}_300dpi.png", {"dpi": 300}),
        (output_dir / f"{name}_600dpi.png", {"dpi": 600}),
    ]:
        figure.savefig(path, facecolor="#FFFFFF", **kwargs)
        files.append(path)
    return files


# --------------------------------------------------------------------------
# preparing each panel
# --------------------------------------------------------------------------


def _prepare_panels(target, brand: Brand) -> list[Panel]:
    """Reproject, simplify and work out the extent for all three panels."""
    india_crs = india_lcc()
    states = data_module.load_states().to_crs(india_crs).copy()
    states["geometry"] = states.geometry.simplify(SIMPLIFY_INDIA_M, preserve_topology=True)
    states = _repair(states)
    india = Panel(
        kind="india",
        caption="India",
        frame=states,
        crs=india_crs,
        highlight_mask=states["name_key"] == target.state_key,
        highlight_colours=[brand.highlight],
        extent=_extent(states.total_bounds),
        label_frame=states[~states["disputed"]],
    )

    districts = target.districts.copy()
    state_crs = local_crs(districts)
    districts = districts.to_crs(state_crs)
    districts["geometry"] = districts.geometry.simplify(SIMPLIFY_STATE_M, preserve_topology=True)
    districts = _repair(districts)

    state = Panel(
        kind="state",
        caption=target.state_name,
        frame=districts,
        crs=state_crs,
        highlight_mask=districts["name_key"] == target.district_row["name_key"],
        highlight_colours=[brand.highlight],
        # Extent comes from the districts of this state, never from the
        # neighbouring states, which are context only.
        extent=_extent(districts.total_bounds),
        context=_neighbours_of(target, state_crs),
    )

    unit_label = target.block_level_label

    if target.blocks_available:
        blocks = target.blocks.copy()
        district_crs = local_crs(blocks)
        blocks = blocks.to_crs(district_crs)
        blocks["geometry"] = blocks.geometry.simplify(SIMPLIFY_DISTRICT_M, preserve_topology=True)
        blocks = _repair(blocks)

        mask = blocks["name"].isin(target.target_block_names)
        district = Panel(
            kind="district",
            caption=f"{target.district_name} district",
            frame=blocks,
            crs=district_crs,
            highlight_mask=mask,
            highlight_colours=brand.highlight_colours(int(mask.sum())),
            extent=_extent(blocks.total_bounds),
            sites=target.sites,
            unit_label=unit_label,
            footnote=(
                None
                if target.unit_level == "block"
                else (
                    "Sub-districts (tehsils) shown: block boundaries are not "
                    f"published for this district. They cover "
                    f"{target.unit_coverage * 100:.0f}% of it."
                )
            ),
        )
    else:
        # No block layer for this district. Rather than refuse to draw, the
        # third panel shows the district on its own, outlined in the accent, and
        # says on the map that block boundaries are not published. Districts
        # created after the block layer was last updated land here.
        outline = gpd.GeoDataFrame(
            {"name": [target.district_name], "geometry": [target.district_row["geometry"]]},
            crs=target.districts.crs,
        )
        district_crs = local_crs(outline)
        outline = outline.to_crs(district_crs)
        outline["geometry"] = outline.geometry.simplify(
            SIMPLIFY_DISTRICT_M, preserve_topology=True
        )
        outline = _repair(outline)

        district = Panel(
            kind="district",
            caption=f"{target.district_name} district",
            frame=outline,
            crs=district_crs,
            highlight_mask=outline["name"].isin([]),
            highlight_colours=[brand.highlight],
            extent=_extent(outline.total_bounds),
            sites=target.sites,
            footnote="Block boundaries are not published for this district.",
            outline_only=True,
            unit_label=unit_label,
        )

    return [india, state, district]


def _extent(bounds) -> tuple[float, float, float, float]:
    """Pad a bounding box and reserve a clear band at the bottom for the scale bar."""
    minx, miny, maxx, maxy = bounds
    dx, dy = maxx - minx, maxy - miny
    minx -= dx * EXTENT_PAD
    maxx += dx * EXTENT_PAD
    maxy += dy * EXTENT_PAD
    miny -= dy * (EXTENT_PAD + SCALE_BAND)
    return (minx, maxx, miny, maxy)


def _allocate(aspects: list[float], *, available_w: float, available_h: float):
    """Share the page between panels of equal height and content-driven width."""
    widths = [available_h * a for a in aspects]
    total = sum(widths)
    if total > available_w:
        scale = available_w / total
        return available_h * scale, [w * scale for w in widths]
    return available_h, widths


def _neighbours_of(target, crs) -> gpd.GeoDataFrame | None:
    """The states touching the target state, drawn faintly for orientation.

    Thinned and looked up through the spatial index rather than by measuring the
    exact distance from every state, which on full-resolution coastlines takes
    about a minute.
    """
    states = data_module.load_states().to_crs(crs).copy()
    states["geometry"] = states.geometry.simplify(NEIGHBOUR_SIMPLIFY_M, preserve_topology=True)
    states = _repair(states)

    match = states.loc[states["name_key"] == target.state_key, "geometry"]
    if match.empty:
        return None

    # A small buffer catches states that share a border without their simplified
    # outlines quite meeting.
    probe = match.iloc[0].buffer(NEIGHBOUR_SIMPLIFY_M * 4)
    nearby = states.iloc[states.sindex.query(probe, predicate="intersects")]
    neighbours = nearby[(nearby["name_key"] != target.state_key) & (~nearby["disputed"])]
    return neighbours if len(neighbours) else None


def _repair(frame: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Fix self-intersecting outlines for drawing only.

    The validator has already reported anything it had to repair, so this never
    hides a problem from the user.
    """
    invalid = ~frame.geometry.is_valid
    if invalid.any():
        frame = frame.copy()
        frame.loc[invalid, "geometry"] = frame.loc[invalid, "geometry"].make_valid()
    return frame


# --------------------------------------------------------------------------
# drawing a panel
# --------------------------------------------------------------------------


def _draw_panel(panel: Panel, brand: Brand) -> None:
    ax = panel.ax

    if panel.context is not None:
        panel.context.plot(
            ax=ax,
            facecolor=brand.context_fill,
            edgecolor=brand.unit_edge,
            linewidth=brand.width("unit_edge"),
            zorder=0,
        )

    others = panel.frame[~panel.highlight_mask]
    if len(others):
        others.plot(
            ax=ax,
            facecolor=panel.other_fill or brand.unit_fill,
            edgecolor=brand.unit_edge,
            linewidth=brand.width("unit_edge"),
            zorder=1,
        )

    if panel.outline_only:
        panel.frame.plot(
            ax=ax,
            facecolor="none",
            edgecolor=brand.highlight,
            linewidth=1.6,
            zorder=3,
        )

    targets = panel.frame[panel.highlight_mask]
    whole = set(panel.whole_state_lgds)
    for position, (_, row) in enumerate(targets.iterrows()):
        colour = panel.highlight_colours[position % len(panel.highlight_colours)]
        # A state marked whole is one area, so its districts are filled with
        # no line between them. Drawn with the usual rim they made a busy
        # texture over the whole state at national scale.
        in_whole = bool(whole) and int(row.get("state_lgd", -1)) in whole
        gpd.GeoSeries([row.geometry], crs=panel.frame.crs).plot(
            ax=ax,
            facecolor=colour,
            edgecolor=colour if in_whole else brand.highlight_rim,
            linewidth=0.3 if in_whole else brand.width("highlight_edge"),
            zorder=2,
        )

    # Blocks inside the marked districts. Drawn over the district fill so the
    # subdivision shows, and never labelled - at coverage scale a block is
    # about a millimetre across, so a name would be a claim the map cannot
    # support. The district's own map is where the names belong.
    if panel.sublayer is not None and len(panel.sublayer):
        panel.sublayer.plot(
            ax=ax,
            facecolor="none",
            edgecolor=brand.unit_edge,
            linewidth=brand.width("unit_edge"),
            zorder=3,
        )
        if panel.sublayer_mask is not None:
            marked = panel.sublayer[panel.sublayer_mask]
            if len(marked):
                marked.plot(
                    ax=ax,
                    facecolor=brand.highlight_secondary,
                    edgecolor=brand.unit_edge,
                    linewidth=brand.width("unit_edge"),
                    zorder=4,
                )

    # The chosen states outlined over their own districts. Without this, two
    # chosen states that touch run together into one wash of colour and the
    # border between them is lost.
    if panel.area_labels is not None and len(panel.area_labels):
        min_size = RIM_MIN_PT / _points_per_unit(ax, panel.extent)
        is_whole = panel.area_labels["lgd"].astype("int64").isin(panel.whole_state_lgds)
        # A state marked whole is the deep fill right to its edge, where the
        # teal rim disappears. Two of them that touch are parted by a white
        # line instead, the way this brand sets lines on a dark ground.
        for chosen, colour, width in (
            (~is_whole, brand.highlight_rim, brand.width("highlight_edge")),
            (is_whole, brand.background, brand.width("highlight_edge") * 1.4),
        ):
            rims = _rim_outlines(panel.area_labels[chosen], min_size)
            if len(rims):
                rims.plot(ax=ax, facecolor="none", edgecolor=colour, linewidth=width, zorder=5)

    # Fix the view before anything is measured against it.
    x0, x1, y0, y1 = panel.extent
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    ax.set_aspect("equal")
    _frame_panel(ax, brand)

    if panel.callouts:
        _label_callout_map(panel, brand)
        _caption_panel(ax, panel.caption, brand, footnote=panel.footnote)
        _add_north_arrow(ax, brand)
        _add_scale_bar(ax, brand)
        return

    # Everything the unit labels must not collide with is drawn first, then
    # handed to the label pass as fixed obstacles.
    obstacles = []
    if panel.kind == "state":
        obstacles += _label_context(panel, brand)
        obstacles += _label_water(panel, brand)

    site_texts, site_points = _draw_sites(panel, brand)

    # State names go through the same adjustment pass as everything else, so
    # they are nudged clear of the district labels rather than sitting on top
    # of them as fixed obstacles would.
    area_texts = _label_areas(panel, brand)

    _label_units(
        panel,
        brand,
        extra_texts=site_texts + area_texts,
        objects=obstacles,
        avoid_points=site_points,
    )

    _caption_panel(ax, panel.caption, brand, footnote=panel.footnote)
    _add_north_arrow(ax, brand)
    _add_scale_bar(ax, brand)


def _frame_panel(ax, brand: Brand) -> None:
    """A hairline frame, so each panel reads as its own map rather than a blob.

    The axis labels have to be cleared explicitly. GeoPandas writes "Easting
    [metre]" and "Northing [metre]" onto a plot whose data is in a projected
    coordinate system, which is helpful on an analyst's chart and meaningless
    on a locator map. This used to be hidden by turning the whole axis off,
    but that hides the spines too, and the spines are what draw this frame.
    """
    ax.set_xlabel("")
    ax.set_ylabel("")
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(True)
        spine.set_linewidth(brand.width("panel_frame"))
        spine.set_edgecolor(brand.panel_edge)


def _caption_panel(ax, caption: str, brand: Brand, *, footnote: str | None = None) -> None:
    """Panel name above the frame, with a short rule under it."""
    if not caption:
        if footnote:
            _caption_footnote(ax, footnote, brand)
        return
    ax.text(
        0.0,
        1.062,
        caption,
        transform=ax.transAxes,
        ha="left",
        va="bottom",
        fontsize=brand.size("panel_caption"),
        color=brand.text,
    )
    ax.plot(
        [0.0, 0.085],
        [1.038, 1.038],
        transform=ax.transAxes,
        color=brand.rule,
        linewidth=brand.width("caption_rule"),
        solid_capstyle="butt",
        clip_on=False,
        zorder=12,
    )
    if footnote:
        _caption_footnote(ax, footnote, brand)


def _caption_footnote(ax, footnote: str, brand: Brand) -> None:
    """A quiet line under a panel, saying something the map cannot show."""
    if True:
        ax.text(
            0.0,
            -0.035,
            footnote,
            transform=ax.transAxes,
            ha="left",
            va="top",
            fontsize=brand.size("scale_bar"),
            color=brand.text_muted,
            style="italic",
            clip_on=False,
        )


# --------------------------------------------------------------------------
# labels
# --------------------------------------------------------------------------


def _label_units(
    panel: Panel, brand: Brand, *, extra_texts=None, objects=None, avoid_points=None
) -> None:
    """Place unit labels, tiered, and nudge them apart with leader lines."""
    from adjustText import adjust_text

    ax = panel.ax
    frame = panel.label_frame if panel.label_frame is not None else panel.frame
    highlight = panel.highlight_mask.reindex(frame.index, fill_value=False)

    keep, skipped = _labels_to_draw(panel, frame, highlight, brand)
    panel.labels_skipped = skipped

    texts = list(extra_texts or [])
    for index, row in frame.loc[keep].iterrows():
        is_target = bool(highlight.loc[index])
        point = row.geometry.representative_point()
        texts.append(
            ax.text(
                point.x,
                point.y,
                display(row["name"]),
                fontsize=brand.size("target_label") if is_target else brand.size("unit_label"),
                color=brand.text if is_target else brand.text_secondary,
                ha="center",
                va="center",
                fontweight="bold" if is_target else "normal",
                zorder=6,
            )
        )

    if not texts:
        return

    # Site markers are repelled from as bare coordinates. Passing the scatter
    # artists themselves does not work: adjustText measures a PathCollection as
    # a NaN bounding box, which takes the whole layout out.
    xs = [x for x, _ in (avoid_points or [])] or None
    ys = [y for _, y in (avoid_points or [])] or None

    adjust_text(
        texts,
        x=xs,
        y=ys,
        ax=ax,
        expand=(1.12, 1.30),
        force_text=(0.35, 0.55),
        force_static=(0.25, 0.45),
        ensure_inside_axes=True,
        iter_lim=LABEL_ITERATIONS,
        objects=objects or None,
        arrowprops=dict(
            arrowstyle="-",
            color=brand.text_muted,
            lw=brand.width("leader_line"),
            shrinkA=1,
            shrinkB=2,
        ),
    )

    _lift_labels_off_highlights(panel, brand, texts)


def _lift_labels_off_highlights(panel: Panel, brand: Brand, texts) -> None:
    """Settle any neighbour's label that ended up over a highlighted unit.

    The label pass can leave a grey label on the teal fill, where grey on dark
    teal cannot be read in print. There are two cases and they want different
    answers. A label sitting wholly on the fill turns white, which is how this
    brand sets text on a dark ground. A label straddling the boundary cannot
    be fixed by either colour - white is lost on the light grey, grey is lost
    on the teal - so it is pushed to whichever side of its anchor keeps it off
    the fill, by setting its alignment rather than moving it, which leaves any
    leader line still pointing where it was.

    Positions are only real after the adjustment pass, so this runs last.
    """
    targets = panel.frame[panel.highlight_mask]
    if not len(targets):
        return

    filled = targets.geometry.union_all()
    for text in texts:
        if text.get_color() == brand.text:
            continue  # a target's own label, already set for this fill

        x, y = text.get_position()
        half = _text_half_width(text, panel.ax)
        if half <= 0:
            continue

        # Where the text would sit centred, and where it would sit if pushed
        # to one side of its anchor.
        centred = _segment(x - half, x + half, y)
        leftward = _segment(x - 2 * half, x, y)
        rightward = _segment(x, x + 2 * half, y)

        if filled.contains(Point(x, y)):
            # On the fill. White works, but only if the whole label is on it.
            if filled.covers(centred):
                pass
            elif filled.covers(rightward):
                text.set_ha("left")
            elif filled.covers(leftward):
                text.set_ha("right")
            text.set_color(brand.background)
            continue

        # Off the fill, but the text may still run across it. Keep it grey and
        # move it to whichever side is clear.
        if not filled.intersects(centred):
            continue
        if not filled.intersects(rightward):
            text.set_ha("left")
        elif not filled.intersects(leftward):
            text.set_ha("right")
        else:
            text.set_color(brand.background)


def _segment(x0: float, x1: float, y: float):
    """A horizontal line at the height a label is drawn, for overlap tests."""
    from shapely.geometry import LineString

    return LineString([(x0, y), (x1, y)])


def _text_half_width(text, ax) -> float:
    """Half the drawn width of a label, in data units."""
    figure = ax.figure
    renderer = figure.canvas.get_renderer()
    box = text.get_window_extent(renderer=renderer)
    inverse = ax.transData.inverted()
    (x0, _), (x1, _) = inverse.transform([[box.x0, box.y0], [box.x1, box.y0]])
    return abs(x1 - x0) / 2.0


def _labels_to_draw(panel: Panel, frame, highlight, brand: Brand):
    """Decide which units get a label.

    Returns the index to keep and how many were left off. In ``auto`` density a
    unit is labelled only if it is drawn large enough to carry the text without
    a leader line running halfway across the panel. The target is always
    labelled, however small it is.
    """
    density = panel.label_density or brand.label_density
    if density == "all":
        return frame.index, 0
    if density == "target_only":
        keep = frame.index[highlight.to_numpy()]
        return keep, int(len(frame) - len(keep))

    # auto: measure each unit in points as it will actually be drawn.
    ax = panel.ax
    x0, x1 = ax.get_xlim()
    box = ax.get_window_extent()
    points_per_unit = (box.width * 72 / ax.figure.dpi) / (x1 - x0)

    bounds = frame.geometry.bounds
    across = (bounds["maxx"] - bounds["minx"]).clip(lower=0)
    up = (bounds["maxy"] - bounds["miny"]).clip(lower=0)
    drawn = across.combine(up, max) * points_per_unit

    keep_mask = (drawn >= brand.label_min_points).to_numpy() | highlight.to_numpy()
    return frame.index[keep_mask], int((~keep_mask).sum())


def _label_context(panel: Panel, brand: Brand) -> list:
    """Label neighbouring states in muted italic, inside the panel only."""
    if panel.context is None:
        return []
    ax = panel.ax
    x0, x1 = ax.get_xlim()
    y0, y1 = ax.get_ylim()
    view = gpd.GeoSeries.from_wkt(
        [f"POLYGON(({x0} {y0},{x1} {y0},{x1} {y1},{x0} {y1},{x0} {y0}))"],
        crs=panel.crs,
    ).iloc[0]

    labels = []
    for _, row in panel.context.iterrows():
        visible = row.geometry.intersection(view)
        if visible.is_empty or visible.area <= 0:
            continue
        point = visible.representative_point()
        labels.append(
            ax.text(
                point.x,
                point.y,
                display(row["name"]),
                fontsize=brand.size("context_label"),
                color=brand.text_muted,
                style="italic",
                ha="center",
                va="center",
                zorder=3,
            )
        )
    return labels


def _label_areas(panel: Panel, brand: Brand) -> list:
    """Name the larger areas a panel covers, clipped to what is in view.

    On a multi-state coverage map only the programme districts are named, so
    without the state names a reader has no way to tell which state any of
    them is in. The name sits on the visible part of the state, which matters
    when a state is only half inside the frame.
    """
    if panel.area_labels is None or panel.area_labels.empty:
        return []

    ax = panel.ax
    x0, x1 = ax.get_xlim()
    y0, y1 = ax.get_ylim()
    view = gpd.GeoSeries.from_wkt(
        [f"POLYGON(({x0} {y0},{x1} {y0},{x1} {y1},{x0} {y1},{x0} {y0}))"],
        crs=panel.crs,
    ).iloc[0]

    labels = []
    for _, row in panel.area_labels.iterrows():
        visible = row.geometry.intersection(view)
        if visible.is_empty or visible.area <= 0:
            continue
        point = visible.representative_point()
        labels.append(
            ax.text(
                point.x,
                point.y,
                display(row["name"]),
                fontsize=brand.size("unit_label"),
                color=brand.text_secondary,
                ha="center",
                va="center",
                zorder=5,
            )
        )
    return labels


def _label_water(panel: Panel, brand: Brand) -> list:
    """Label seas that fall inside the panel, in muted italic."""
    path = data_module.data_dir() / "sea_labels.csv"
    if not path.exists():
        return []

    rows = []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(line for line in handle if not line.startswith("#"))
        for row in reader:
            try:
                rows.append((row["name"], float(row["lat"]), float(row["lon"])))
            except (KeyError, TypeError, ValueError):
                continue
    if not rows:
        return []

    ax = panel.ax
    labels = []
    points = gpd.GeoSeries([Point(lon, lat) for _, lat, lon in rows], crs=4326).to_crs(panel.crs)
    x0, x1 = ax.get_xlim()
    y0, y1 = ax.get_ylim()
    for (name, _, _), point in zip(rows, points):
        if x0 < point.x < x1 and y0 < point.y < y1:
            labels.append(
                ax.text(
                    point.x,
                    point.y,
                    name,
                    fontsize=brand.size("context_label"),
                    color=brand.text_muted,
                    style="italic",
                    ha="center",
                    va="center",
                    zorder=4,
                )
            )
    return labels


# --------------------------------------------------------------------------
# labels on the map across states
# --------------------------------------------------------------------------


def _points_per_unit(ax, extent) -> float:
    """How many printed points one map unit (a metre) is drawn as."""
    x0, x1, _, _ = extent
    box = ax.get_window_extent()
    return (box.width * 72 / ax.figure.dpi) / (x1 - x0)


def _rim_outlines(states: gpd.GeoDataFrame, min_size: float) -> gpd.GeoSeries:
    """The outer edge of each chosen state, for drawing its outline.

    Holes are left out - an enclave such as Puducherry inside Tamil Nadu is a
    different territory, not the state's edge - and so is any island or sliver
    smaller than ``min_size`` across. In the heavier rim those printed as dark
    specks scattered over the state rather than as shapes. Their fill is drawn
    as before; only the outline skips them.
    """
    from shapely.geometry import Polygon

    kept = []
    for geometry in states.geometry:
        for part in _polygons(geometry):
            minx, miny, maxx, maxy = part.bounds
            if max(maxx - minx, maxy - miny) < min_size:
                continue
            kept.append(Polygon(part.exterior))
    return gpd.GeoSeries(kept, crs=states.crs)


def _polygons(geometry) -> list:
    """Every polygon in a geometry, however deeply it is nested.

    Repairing an outline with ``make_valid`` can hand back a collection that
    holds a multipolygon beside stray lines - Tamil Nadu's does - so looking
    one level down is not enough.
    """
    if geometry is None or geometry.is_empty:
        return []
    if geometry.geom_type == "Polygon":
        return [geometry]
    found = []
    for part in getattr(geometry, "geoms", []):
        found += _polygons(part)
    return found


def _area_only(geometry):
    """The polygons of a geometry as one shape, without any stray lines."""
    from shapely.geometry import MultiPolygon

    parts = _polygons(geometry)
    return parts[0] if len(parts) == 1 else MultiPolygon(parts)


def _furniture_boxes(extent, per_pt: float) -> list:
    """Where the scale bar and north arrow sit, so no label lands on them.

    Worked out from the same fractions ``_add_scale_bar`` and
    ``_add_north_arrow`` draw at.
    """
    from shapely.geometry import box

    x0, x1, y0, y1 = extent
    w, h = x1 - x0, y1 - y0
    bar_m = _nice_distance(w / 1000.0 * 0.22) * 1000
    scale = box(x0, y0, x0 + w * 0.035 + bar_m + 4 * per_pt, y0 + h * 0.048 + 10 * per_pt)
    arrow = box(x0 + w * 0.93, y0, x1, y0 + h * 0.072 + 4 * per_pt)
    return [scale, arrow]


def _label_callout_map(panel: Panel, brand: Brand) -> None:
    """Name the covered districts, the chosen states and any sites.

    A district on this map is a few millimetres wide, so a label started on
    top of it - which is how the general label pass works - ends up across the
    coastline or the state's own outline. Here each label is put into clear
    space beside what it names instead, nearest first, with a hairline back to
    it once it has had to move away.

    A label never touches a chosen state's outline, a covered area, a dot, a
    site, the scale bar, the north arrow or another label. Crossing another
    state's border or the coast is allowed but costs, so a clear position wins
    whenever there is one. A state's name goes inside the state when it fits
    there, and beside it when it does not.

    Deterministic: candidates are tried in a fixed order and a tie goes to the
    first, so the same map always gets the same labels.
    """
    from shapely import prepare
    from shapely.ops import unary_union

    ax = panel.ax
    per_pt = 1.0 / _points_per_unit(ax, panel.extent)
    clear = CALLOUT_CLEAR_PT * per_pt
    colour = panel.highlight_colours[0] if panel.highlight_colours else brand.highlight

    frame = panel.frame
    named = frame[frame["lgd"].astype("int64").isin(panel.covered_lgds)]
    filled = frame[panel.highlight_mask]
    states = panel.area_labels if panel.area_labels is not None else frame.iloc[0:0]

    # Crossing a border or the coast is allowed, at a price.
    borders = list(states.boundary)
    if panel.context is not None:
        borders += list(panel.context.boundary)
    soft = unary_union(borders) if borders else None

    # Never crossed. Kept apart because a state marked whole has its own name
    # set inside its own fill, which every other label has to stay off.
    rims = _rim_outlines(states, RIM_MIN_PT * per_pt)
    lines = [unary_union(list(rims.boundary)).buffer(clear)] if len(rims) else []
    fill = [filled.geometry.union_all().buffer(clear)] if len(filled) else []
    other = _furniture_boxes(panel.extent, per_pt)

    # A covered district too small to see gets a dot, and its label's leader
    # line runs to the dot.
    anchors = {}
    for index, row in named.iterrows():
        minx, miny, maxx, maxy = row.geometry.bounds
        if max(maxx - minx, maxy - miny) / per_pt >= SMALL_MARK_PT:
            continue
        point = row.geometry.representative_point()
        ax.scatter(
            [point.x], [point.y], marker="o", s=24, color=colour,
            edgecolor=brand.background, linewidth=0.6, zorder=7,
        )
        other.append(point.buffer(4 * per_pt))
        anchors[index] = point
        panel.dotted += 1

    specs = [
        (display(row["name"]), anchors.get(index, row.geometry), "district")
        for index, row in named.iterrows()
    ]

    # Site markers stay where they are; their names join this pass.
    site_texts, site_points = _draw_sites(panel, brand)
    for text, (x, y) in zip(site_texts, site_points):
        specs.append((text.get_text(), Point(x, y), "site"))
        text.remove()
        other.append(Point(x, y).buffer(4 * per_pt))

    whole = set(panel.whole_state_lgds)
    for _, row in states.iterrows():
        kind = "whole" if int(row["lgd"]) in whole else "state"
        specs.append((display(row["name"]), _area_only(row.geometry), kind))

    placed: list = []
    for label, geometry, kind in specs:
        style = _callout_style(kind, brand)
        text = ax.text(0, 0, label, ha="left", va="bottom", zorder=9, **style)
        w, h = _text_size(text, ax, per_pt)

        inside = None
        if kind in ("state", "whole"):
            # Inside first. A whole state's own fill is where its name goes,
            # so only for that one is the fill not in the way.
            keep_off = lines + other + placed + ([] if kind == "whole" else fill)
            inside = _place_inside(geometry, w, h, clear, keep_off)

        if inside is not None:
            x, y = inside
            if kind == "whole":
                text.set_color(brand.background)  # white on the deep fill
        else:
            keep_off = unary_union(lines + fill + other + placed)
            prepare(keep_off)
            x, y = _place_beside(
                geometry, w, h, per_pt=per_pt, view=panel.extent,
                keep_off=keep_off, soft=soft,
            )
            _draw_leader(ax, geometry, (x, y, w, h), per_pt=per_pt, brand=brand)

        text.set_position((x, y))
        placed.append(_box(x, y, w, h).buffer(clear))


def _callout_style(kind: str, brand: Brand) -> dict:
    """Type for each kind of label on the map across states."""
    if kind == "site":
        return dict(fontsize=brand.size("site_label"), color=brand.text, fontweight="bold")
    if kind == "state":
        return dict(fontsize=brand.size("legend"), color=brand.text_secondary)
    # Covered districts and states marked whole are what the map is about.
    return dict(fontsize=brand.size("target_label"), color=brand.text, fontweight="bold")


def _text_size(text, ax, per_pt: float) -> tuple[float, float]:
    """A label's drawn width and height, in map units."""
    renderer = ax.figure.canvas.get_renderer()
    box = text.get_window_extent(renderer=renderer)
    to_pt = 72 / ax.figure.dpi
    return box.width * to_pt * per_pt, box.height * to_pt * per_pt


def _box(x: float, y: float, w: float, h: float):
    from shapely.geometry import box

    return box(x, y, x + w, y + h)


def _place_inside(geometry, w, h, clear, keep_off):
    """A spot for a label wholly inside an area, or ``None`` if none fits.

    Tried outward from the area's representative point, on a grid a quarter of
    the label wide and half of it tall, nearest first.
    """
    from shapely import prepare
    from shapely.ops import unary_union

    room = geometry.buffer(-clear)
    if room.is_empty:
        return None
    blocked = unary_union(keep_off) if keep_off else None
    prepare(room)
    if blocked is not None:
        prepare(blocked)

    centre = geometry.representative_point()
    step_x, step_y = w / 4, h / 2
    offsets = sorted(
        ((i, j) for i in range(-14, 15) for j in range(-14, 15)),
        key=lambda o: ((o[0] * step_x) ** 2 + (o[1] * step_y) ** 2, o),
    )
    for i, j in offsets:
        x = centre.x + i * step_x - w / 2
        y = centre.y + j * step_y - h / 2
        candidate = _box(x, y, w, h)
        if not room.contains(candidate):
            continue
        if blocked is not None and blocked.intersects(candidate):
            continue
        return x, y
    return None


def _place_beside(geometry, w, h, *, per_pt, view, keep_off, soft):
    """The best spot for a label just outside what it names.

    Positions are tried on rings round the shape, nearest ring first, with the
    label set so its nearest edge or corner touches the ring. A position must
    stay inside the panel and off everything in ``keep_off``. Of those left,
    the cheapest wins: its distance out, plus the length of any border or
    coastline running through it. If nothing is clear at all, the position
    overlapping least is used rather than dropping the name.
    """
    x0, x1, y0, y1 = view
    margin = 2 * per_pt
    hull = geometry.convex_hull
    centre = hull.centroid if hull.area > 0 else geometry.representative_point()

    reach = (max(CALLOUT_GAPS_PT) * per_pt) + max(w, h)
    local = soft.intersection(hull.buffer(reach)) if soft is not None else None

    best, best_cost = None, None
    for gap_pt in CALLOUT_GAPS_PT:
        if best_cost is not None and best_cost < 1000 and gap_pt >= best_cost:
            break  # nothing further out can be cheaper
        ring = hull.buffer(gap_pt * per_pt, quad_segs=8).exterior
        for step in range(CALLOUT_STEPS):
            a = ring.interpolate(step / CALLOUT_STEPS, normalized=True)
            dx, dy = a.x - centre.x, a.y - centre.y
            length = (dx * dx + dy * dy) ** 0.5 or 1.0
            dx, dy = dx / length, dy / length
            x = a.x if dx > 0.38 else (a.x - w if dx < -0.38 else a.x - w / 2)
            y = a.y if dy > 0.38 else (a.y - h if dy < -0.38 else a.y - h / 2)
            if x < x0 + margin or x + w > x1 - margin or y < y0 + margin or y + h > y1 - margin:
                continue
            candidate = _box(x, y, w, h)
            if keep_off.intersects(candidate):
                overlap = keep_off.intersection(candidate).area / (w * h)
                cost = 1000 + 1000 * overlap + gap_pt
            else:
                crossing = 0.0
                if local is not None and not local.is_empty:
                    crossing = local.intersection(candidate).length / per_pt
                cost = gap_pt + 0.8 * crossing
            if best_cost is None or cost < best_cost:
                best, best_cost = (x, y), cost
    if best is None:
        point = geometry.representative_point()
        return point.x, point.y
    return best


def _draw_leader(ax, geometry, label_box, *, per_pt, brand: Brand) -> None:
    """A hairline from a label back to what it names, once it has moved away."""
    from shapely.ops import nearest_points

    x, y, w, h = label_box
    target = _box(x, y, w, h)
    if geometry.distance(target) / per_pt < CALLOUT_LEADER_PT:
        return
    start, end = nearest_points(geometry, target)
    ax.plot(
        [start.x, end.x],
        [start.y, end.y],
        color=brand.text_muted,
        linewidth=brand.width("leader_line"),
        solid_capstyle="butt",
        zorder=8,
    )


def _draw_sites(panel: Panel, brand: Brand) -> tuple[list, list]:
    """Plot site points.

    Returns the labels, which join the layout pass, and the marker positions,
    which the layout pass repels from so a label never lands on its own point.
    """
    if not panel.sites:
        return [], []

    ax = panel.ax
    texts = []
    points = []
    for site in panel.sites:
        point = gpd.GeoSeries([Point(float(site["lon"]), float(site["lat"]))], crs=4326).to_crs(
            panel.crs
        )
        x, y = point.x.iloc[0], point.y.iloc[0]
        points.append((x, y))
        ax.scatter(
            [x],
            [y],
            marker=brand.marker(site.get("type", "default")),
            s=brand.marker_size,
            color=brand.site_marker,
            edgecolor="#FFFFFF",
            linewidth=0.8,
            zorder=8,
        )
        texts.append(
            ax.text(
                x,
                y,
                str(site.get("name", "")).strip(),
                fontsize=brand.size("site_label"),
                color=brand.text,
                fontweight="bold",
                ha="center",
                va="center",
                zorder=9,
            )
        )
    return texts, points


# --------------------------------------------------------------------------
# furniture
# --------------------------------------------------------------------------


def _add_north_arrow(ax, brand: Brand) -> None:
    """A plain north arrow in the reserved band at the bottom right."""
    ax.annotate(
        "N",
        xy=(0.955, 0.072),
        xytext=(0.955, 0.016),
        xycoords="axes fraction",
        textcoords="axes fraction",
        ha="center",
        va="center",
        fontsize=brand.size("scale_bar"),
        color=brand.text_secondary,
        arrowprops=dict(
            arrowstyle="-|>", color=brand.text_secondary, lw=0.7, shrinkA=0, shrinkB=0
        ),
        zorder=11,
    )


def _add_scale_bar(ax, brand: Brand) -> None:
    """A scale bar in kilometres, rounded to a readable distance."""
    x0, x1 = ax.get_xlim()
    y0, y1 = ax.get_ylim()
    span_km = (x1 - x0) / 1000.0

    bar_km = _nice_distance(span_km * 0.22)
    bar_m = bar_km * 1000
    bar_x = x0 + (x1 - x0) * 0.035
    bar_y = y0 + (y1 - y0) * 0.032
    bar_height = (y1 - y0) * 0.006

    ax.add_patch(
        Rectangle(
            (bar_x, bar_y),
            bar_m,
            bar_height,
            facecolor=brand.text_secondary,
            edgecolor="none",
            zorder=10,
        )
    )
    ax.text(
        bar_x + bar_m / 2,
        bar_y + bar_height * 2.6,
        f"{bar_km:g} km",
        ha="center",
        va="bottom",
        fontsize=brand.size("scale_bar"),
        color=brand.text_secondary,
        zorder=10,
    )


def _nice_distance(raw_km: float) -> float:
    """Round a distance up to 1, 2 or 5 times a power of ten."""
    if raw_km <= 0:
        return 1
    magnitude = 10 ** int(f"{raw_km:e}".split("e")[1])
    for step in (1, 2, 5, 10):
        if step * magnitude >= raw_km:
            return step * magnitude
    return 10 * magnitude


def _draw_title_block(
    figure, title: str, brand: Brand, *, margin, width, height, rule_right=None
) -> None:
    """The running title, with a rule under it across the page."""
    figure.text(
        margin / width,
        1 - 0.30 / height,
        title,
        ha="left",
        va="center",
        fontsize=brand.size("title"),
        color=brand.text,
        fontweight="bold",
    )
    rule_y = 1 - 0.48 / height
    right = (rule_right if rule_right is not None else width - margin) / width
    figure.add_artist(
        Line2D(
            [margin / width, right],
            [rule_y, rule_y],
            transform=figure.transFigure,
            color=brand.rule,
            linewidth=brand.width("title_rule"),
            solid_capstyle="butt",
        )
    )


def _draw_logo(figure, brand: Brand, *, margin, width, height) -> None:
    """Place the Cognizant Foundation India logo in a corner of the page.

    The communication guidelines are specific: the logo sits in a corner and is
    never centred, and it is never recoloured, stretched or rotated. The aspect
    ratio comes from the file itself, so the drawn logo cannot be distorted, and
    the width is floored at the brand minimum by :class:`Brand`.
    """
    import matplotlib.image as mpimg

    path = Path(brand.logo_file)
    if not path.is_absolute():
        path = Path(__file__).resolve().parent.parent / path
    if not path.exists():
        return

    image = mpimg.imread(path)
    logo_w = brand.logo_width_in
    logo_h = logo_w * image.shape[0] / image.shape[1]

    clear = brand.logo_clear_space_in
    position = brand.logo_position
    left = margin if position.endswith("left") else width - margin - logo_w
    bottom = (
        height - margin - logo_h + 0.06 if position.startswith("top") else margin - 0.06
    )

    # Keep the logo clear of the page edge by at least its required clear space.
    left = min(max(left, clear), width - logo_w - clear)
    bottom = min(max(bottom, clear), height - logo_h - clear)

    axes = figure.add_axes(
        [left / width, bottom / height, logo_w / width, logo_h / height],
        zorder=30,
    )
    axes.imshow(image, interpolation="antialiased")
    axes.set_axis_off()
    axes.patch.set_alpha(0)


def _draw_callout(figure, panel_from: Panel, panel_to: Panel, brand: Brand) -> None:
    """Box the area the next panel enlarges, and run two light lines to it.

    This is the inset convention an atlas uses. The box sits on the wider panel
    and its right-hand corners join the left-hand corners of the panel that
    shows that area in detail.
    """
    nx0, nx1, ny0, ny1 = panel_to.extent
    corners = gpd.GeoSeries(
        [Point(nx0, ny0), Point(nx1, ny0), Point(nx1, ny1), Point(nx0, ny1)],
        crs=panel_to.crs,
    ).to_crs(panel_from.crs)

    bx0, bx1 = float(corners.x.min()), float(corners.x.max())
    by0, by1 = float(corners.y.min()), float(corners.y.max())

    # A box smaller than a couple of points would read as a smudge, so give it a
    # floor relative to the panel it sits on.
    ax = panel_from.ax
    px0, px1 = ax.get_xlim()
    py0, py1 = ax.get_ylim()
    floor_x = (px1 - px0) * 0.015
    floor_y = (py1 - py0) * 0.015
    if bx1 - bx0 < floor_x:
        mid = (bx0 + bx1) / 2
        bx0, bx1 = mid - floor_x / 2, mid + floor_x / 2
    if by1 - by0 < floor_y:
        mid = (by0 + by1) / 2
        by0, by1 = mid - floor_y / 2, mid + floor_y / 2

    ax.add_patch(
        Rectangle(
            (bx0, by0),
            bx1 - bx0,
            by1 - by0,
            facecolor="none",
            edgecolor=brand.callout,
            linewidth=brand.width("callout_box"),
            zorder=15,
        )
    )

    # Two lines from the right-hand corners of the box to the left-hand corners
    # of the next panel. Kept light so they read as a callout, not an arrow.
    for corner_y, target_y in ((by1, 1.0), (by0, 0.0)):
        figure.add_artist(
            ConnectionPatch(
                xyA=(bx1, corner_y),
                coordsA=ax.transData,
                xyB=(0.0, target_y),
                coordsB=panel_to.ax.transAxes,
                color=brand.callout,
                linewidth=brand.width("callout_line"),
                alpha=0.45,
                zorder=14,
                clip_on=False,
            )
        )


def _draw_legend(figure, panel: Panel, brand: Brand, *, target) -> None:
    """Legend under the district panel, so it never sits on top of the map."""
    handles = []
    if panel.outline_only:
        handles.append(
            Line2D(
                [],
                [],
                marker="s",
                linestyle="none",
                markerfacecolor="none",
                markeredgecolor=brand.highlight,
                markeredgewidth=1.4,
                color="none",
                markersize=6,
                label=f"{target.district_name} district",
            )
        )
    for name, colour in zip(target.target_block_names, panel.highlight_colours):
        handles.append(
            Line2D(
                [],
                [],
                marker="s",
                linestyle="none",
                color=colour,
                markersize=6,
                label=f"{display(name)} {panel.unit_label}",
            )
        )
    if not panel.outline_only:
        handles.append(
            Line2D(
                [],
                [],
                marker="s",
                linestyle="none",
                color=brand.unit_fill,
                markersize=6,
                label=f"Other {panel.unit_label}s",
            )
        )

    seen = set()
    for site in panel.sites:
        site_type = (site.get("type") or "site").lower()
        if site_type in seen:
            continue
        seen.add(site_type)
        handles.append(
            Line2D(
                [],
                [],
                marker=brand.marker(site_type),
                linestyle="none",
                color=brand.site_marker,
                markersize=5,
                label=site_type[:1].upper() + site_type[1:],
            )
        )

    box = panel.ax.get_position()
    # A footnote under the panel takes the first line below it, so the legend
    # drops to the next one.
    drop = 0.058 if panel.footnote else 0.022
    legend = figure.legend(
        handles=handles,
        loc="upper left",
        bbox_to_anchor=(box.x0, box.y0 - drop),
        frameon=False,
        fontsize=brand.size("legend"),
        handletextpad=0.6,
        labelspacing=0.4,
        borderpad=0.0,
        ncols=min(len(handles), 3),
        columnspacing=1.5,
    )
    for text in legend.get_texts():
        text.set_color(brand.text_secondary)


def _source_line() -> str:
    """The attribution line printed at the foot of every map."""
    return (
        "Boundaries: Survey of India (states); Local Government Directory via BharatMaps "
        "(districts, blocks). Names and codes: LGD. Boundary data as of December 2023. "
        f"Map generated {date.today().isoformat()}."
    )
