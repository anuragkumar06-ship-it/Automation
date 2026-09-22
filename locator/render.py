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
from shapely.geometry import Point

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import ConnectionPatch, Rectangle  # noqa: E402

from . import data as data_module  # noqa: E402
from .names import display  # noqa: E402
from .style import Brand, india_lcc, local_crs  # noqa: E402

__all__ = ["render_map", "RenderResult"]

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

    @property
    def aspect(self) -> float:
        x0, x1, y0, y1 = self.extent
        return (x1 - x0) / (y1 - y0)


def render_map(*, target, config: dict, brand: Brand, report, output_dir: Path) -> RenderResult:
    """Render the map and write SVG, PDF and PNG files plus a render log."""
    output_dir.mkdir(parents=True, exist_ok=True)
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
    _draw_title_block(figure, title, brand, margin=margin, width=width, height=height)
    _draw_legend(figure, panels[2], brand, target=target)

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
    files: list[Path] = []
    for path, kwargs in [
        (output_dir / f"{name}.svg", {}),
        (output_dir / f"{name}.pdf", {}),
        (output_dir / f"{name}_300dpi.png", {"dpi": 300}),
        (output_dir / f"{name}_600dpi.png", {"dpi": 600}),
    ]:
        figure.savefig(path, facecolor=brand.background, **kwargs)
        files.append(path)
    plt.close(figure)

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
            facecolor=brand.unit_fill,
            edgecolor=brand.unit_edge,
            linewidth=brand.width("unit_edge"),
            zorder=1,
        )

    targets = panel.frame[panel.highlight_mask]
    for position, (_, row) in enumerate(targets.iterrows()):
        colour = panel.highlight_colours[position % len(panel.highlight_colours)]
        gpd.GeoSeries([row.geometry], crs=panel.frame.crs).plot(
            ax=ax,
            facecolor=colour,
            edgecolor=brand.highlight_rim,
            linewidth=brand.width("highlight_edge"),
            zorder=2,
        )

    # Fix the view before anything is measured against it.
    x0, x1, y0, y1 = panel.extent
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    ax.set_aspect("equal")
    _frame_panel(ax, brand)

    # Everything the unit labels must not collide with is drawn first, then
    # handed to the label pass as fixed obstacles.
    obstacles = []
    if panel.kind == "state":
        obstacles += _label_context(panel, brand)
        obstacles += _label_water(panel, brand)

    site_texts, site_points = _draw_sites(panel, brand)

    _label_units(panel, brand, extra_texts=site_texts, objects=obstacles, avoid_points=site_points)

    _caption_panel(ax, panel.caption, brand)
    _add_north_arrow(ax, brand)
    _add_scale_bar(ax, brand)


def _frame_panel(ax, brand: Brand) -> None:
    """A hairline frame, so each panel reads as its own map rather than a blob."""
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(True)
        spine.set_linewidth(brand.width("panel_frame"))
        spine.set_edgecolor(brand.panel_edge)


def _caption_panel(ax, caption: str, brand: Brand) -> None:
    """Panel name above the frame, with a short rule under it."""
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


def _labels_to_draw(panel: Panel, frame, highlight, brand: Brand):
    """Decide which units get a label.

    Returns the index to keep and how many were left off. In ``auto`` density a
    unit is labelled only if it is drawn large enough to carry the text without
    a leader line running halfway across the panel. The target is always
    labelled, however small it is.
    """
    density = brand.label_density
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


def _draw_title_block(figure, title: str, brand: Brand, *, margin, width, height) -> None:
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
    figure.add_artist(
        Line2D(
            [margin / width, 1 - margin / width],
            [rule_y, rule_y],
            transform=figure.transFigure,
            color=brand.rule,
            linewidth=brand.width("title_rule"),
            solid_capstyle="butt",
        )
    )


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
    for name, colour in zip(target.target_block_names, panel.highlight_colours):
        handles.append(
            Line2D(
                [],
                [],
                marker="s",
                linestyle="none",
                color=colour,
                markersize=6,
                label=f"{display(name)} block",
            )
        )
    handles.append(
        Line2D(
            [],
            [],
            marker="s",
            linestyle="none",
            color=brand.unit_fill,
            markersize=6,
            label="Other blocks",
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


def _source_line() -> str:
    """The attribution line printed at the foot of every map."""
    return (
        "Boundaries: Survey of India (states); Local Government Directory via BharatMaps "
        "(districts, blocks). Names and codes: LGD. Boundary data as of December 2023. "
        f"Map generated {date.today().isoformat()}."
    )
