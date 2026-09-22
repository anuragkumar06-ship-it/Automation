"""Draw the three-panel locator map.

Panels run left to right: India with the target state highlighted, the state
with the target district highlighted, then the district with the target
block(s) highlighted and any site points marked. Connector arrows run from each
highlighted unit into the panel that zooms into it.

Every polygon drawn here comes from a layer loaded by :mod:`locator.data`.

Layout note. India is tall, Tamil Nadu is taller and a district is usually
wide. Giving all three panels the same rectangle would leave most of the page
empty, so the panels share one height and each takes the width its own shape
needs. Simplification tolerances stay below one printed pixel at 600 dpi, so
shapes never visibly change, and they are recorded in the render log.
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

# Fraction of panel height kept clear at the bottom for the scale bar.
SCALE_BAND = 0.11
# Breathing room around the mapped area.
EXTENT_PAD = 0.02

# Fixed bands, in inches, for the running title above the panels and for the
# legend plus source line below them. Keeping these in inches rather than as a
# fraction means type stays the same size whatever height the panels come out.
BAND_TOP_IN = 0.68
BAND_BOTTOM_IN = 0.72


@dataclass
class RenderResult:
    files: list[Path]
    figure_size: tuple[float, float]
    notes: list[str]


@dataclass
class Panel:
    """One prepared panel: its geometry, extent and how it should be drawn."""

    kind: str
    title: str
    frame: gpd.GeoDataFrame
    crs: object
    highlight_mask: object
    highlight_colours: list[str]
    extent: tuple[float, float, float, float]
    context: gpd.GeoDataFrame | None = None
    label_frame: gpd.GeoDataFrame | None = None
    sites: list[dict] = field(default_factory=list)
    ax: object = None

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
    # a wide state such as Bihar forces shorter panels than a narrow one such
    # as Tamil Nadu. The figure is trimmed to fit rather than left with a band
    # of empty paper, so the image drops into a document at a sensible size.
    height = panel_h + BAND_TOP_IN + BAND_BOTTOM_IN

    figure = plt.figure(figsize=(width, height), facecolor=brand.background)

    cursor = margin
    for panel, panel_w in zip(panels, panel_widths):
        panel.ax = figure.add_axes(
            [cursor / width, BAND_BOTTOM_IN / height, panel_w / width, panel_h / height],
            facecolor=brand.water,
        )
        cursor += panel_w + gap

    for panel in panels:
        _draw_panel(panel, brand)

    _connect(figure, panels[0], panels[1], brand)
    _connect(figure, panels[1], panels[2], brand)

    _add_legend(figure, panels[2], brand, target=target)

    # ---- running title and source line ------------------------------------
    title = config.get("title") or f"{target.district_name} district, {target.state_name}"
    figure.text(
        margin / width,
        1 - 0.26 / height,
        title,
        ha="left",
        va="center",
        fontsize=brand.size("panel_title") + 3,
        color=brand.text,
        fontweight="bold",
    )

    source_line = _source_line()
    figure.text(
        margin / width,
        0.17 / height,
        source_line,
        ha="left",
        va="center",
        fontsize=brand.size("source_line"),
        color=brand.text_muted,
    )
    notes.append(f"Source line: {source_line}")

    # ---- write the files --------------------------------------------------
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
    notes.append(f"Font used: {brand.font_family}.")

    return RenderResult(files=files, figure_size=(width, height), notes=notes)


# --------------------------------------------------------------------------
# preparing each panel
# --------------------------------------------------------------------------


def _prepare_panels(target, brand: Brand) -> list[Panel]:
    """Reproject, simplify and work out the extent for all three panels."""
    # ---- panel 1: India ---------------------------------------------------
    india_crs = india_lcc()
    states = _repair(data_module.load_states().to_crs(india_crs))
    states["geometry"] = states.geometry.simplify(SIMPLIFY_INDIA_M, preserve_topology=True)
    india = Panel(
        kind="india",
        title="India",
        frame=states,
        crs=india_crs,
        highlight_mask=states["name_key"] == target.state_key,
        highlight_colours=[brand.highlight],
        extent=_extent(states.total_bounds),
        label_frame=states[~states["disputed"]],
    )

    # ---- panel 2: the state ----------------------------------------------
    districts = _repair(target.districts.copy())
    state_crs = local_crs(districts)
    districts = districts.to_crs(state_crs)
    districts["geometry"] = districts.geometry.simplify(SIMPLIFY_STATE_M, preserve_topology=True)

    neighbours = _neighbours_of(target, state_crs)
    state = Panel(
        kind="state",
        title=target.state_name,
        frame=districts,
        crs=state_crs,
        highlight_mask=districts["name_key"] == target.district_row["name_key"],
        highlight_colours=[brand.highlight],
        # Extent comes from the state's own districts, never from the
        # neighbouring states, which are context only.
        extent=_extent(districts.total_bounds),
        context=neighbours,
    )

    # ---- panel 3: the district -------------------------------------------
    blocks = _repair(target.blocks.copy())
    district_crs = local_crs(blocks)
    blocks = blocks.to_crs(district_crs)
    blocks["geometry"] = blocks.geometry.simplify(SIMPLIFY_DISTRICT_M, preserve_topology=True)

    mask = blocks["name"].isin(target.target_block_names)
    district = Panel(
        kind="district",
        title=f"{target.district_name} district",
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
    """The states touching the target state, drawn faintly for orientation."""
    states = _repair(data_module.load_states().to_crs(crs))
    match = states.loc[states["name_key"] == target.state_key, "geometry"]
    if match.empty:
        return None
    target_geom = match.iloc[0]
    neighbours = states[
        (states["name_key"] != target.state_key)
        & (~states["disputed"])
        & (states.geometry.distance(target_geom) < 1500)
    ]
    return neighbours if len(neighbours) else None


# --------------------------------------------------------------------------
# drawing
# --------------------------------------------------------------------------


def _draw_panel(panel: Panel, brand: Brand) -> None:
    ax = panel.ax

    if panel.context is not None:
        panel.context.plot(
            ax=ax,
            facecolor="#EAEAE8",
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
            edgecolor=brand.unit_edge,
            linewidth=brand.width("highlight_edge"),
            zorder=2,
        )

    # Fix the view before anything is measured against it.
    x0, x1, y0, y1 = panel.extent
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    ax.set_aspect("equal")
    ax.set_axis_off()

    site_texts = _draw_sites(panel, brand)
    _label_units(panel, brand, extra_texts=site_texts)

    if panel.kind == "state":
        _label_context(panel, brand)
        _label_water(panel, brand)

    ax.set_title(
        panel.title,
        loc="left",
        fontsize=brand.size("panel_title"),
        color=brand.text,
        pad=6,
    )
    _add_north_arrow(ax, brand)
    _add_scale_bar(ax, brand)


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


def _label_units(panel: Panel, brand: Brand, *, extra_texts=None) -> None:
    """Place one label per unit, nudged apart and joined by leader lines."""
    from adjustText import adjust_text

    ax = panel.ax
    frame = panel.label_frame if panel.label_frame is not None else panel.frame
    highlight = panel.highlight_mask.reindex(frame.index, fill_value=False)

    texts = list(extra_texts or [])
    for (_, row), is_target in zip(frame.iterrows(), highlight):
        point = row.geometry.representative_point()
        texts.append(
            ax.text(
                point.x,
                point.y,
                display(row["name"]),
                fontsize=brand.size("target_label") if is_target else brand.size("unit_label"),
                color=brand.text,
                ha="center",
                va="center",
                fontweight="bold" if is_target else "normal",
                zorder=6,
            )
        )

    if not texts:
        return

    adjust_text(
        texts,
        ax=ax,
        expand=(1.06, 1.18),
        force_text=(0.15, 0.30),
        ensure_inside_axes=True,
        arrowprops=dict(
            arrowstyle="-",
            color=brand.text_muted,
            lw=brand.width("leader_line"),
            shrinkA=1,
            shrinkB=2,
        ),
    )


def _label_context(panel: Panel, brand: Brand) -> None:
    """Label neighbouring states in muted italic, inside the panel only."""
    if panel.context is None:
        return
    ax = panel.ax
    x0, x1 = ax.get_xlim()
    y0, y1 = ax.get_ylim()
    view = gpd.GeoSeries.from_wkt(
        [f"POLYGON(({x0} {y0},{x1} {y0},{x1} {y1},{x0} {y1},{x0} {y0}))"],
        crs=panel.crs,
    ).iloc[0]

    for _, row in panel.context.iterrows():
        visible = row.geometry.intersection(view)
        if visible.is_empty or visible.area <= 0:
            continue
        point = visible.representative_point()
        ax.text(
            point.x,
            point.y,
            display(row["name"]),
            fontsize=brand.size("unit_label"),
            color=brand.text_muted,
            style="italic",
            ha="center",
            va="center",
            zorder=3,
        )


def _label_water(panel: Panel, brand: Brand) -> None:
    """Label seas that fall inside the panel, in muted italic."""
    path = data_module.data_dir() / "sea_labels.csv"
    if not path.exists():
        return

    rows = []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(line for line in handle if not line.startswith("#"))
        for row in reader:
            try:
                rows.append((row["name"], float(row["lat"]), float(row["lon"])))
            except (KeyError, TypeError, ValueError):
                continue
    if not rows:
        return

    ax = panel.ax
    points = gpd.GeoSeries([Point(lon, lat) for _, lat, lon in rows], crs=4326).to_crs(panel.crs)
    x0, x1 = ax.get_xlim()
    y0, y1 = ax.get_ylim()
    for (name, _, _), point in zip(rows, points):
        if x0 < point.x < x1 and y0 < point.y < y1:
            ax.text(
                point.x,
                point.y,
                name,
                fontsize=brand.size("unit_label"),
                color=brand.text_muted,
                style="italic",
                ha="center",
                va="center",
                zorder=4,
            )


def _draw_sites(panel: Panel, brand: Brand) -> list:
    """Plot site points. Returns their labels so they join the layout pass."""
    if not panel.sites:
        return []

    ax = panel.ax
    texts = []
    for site in panel.sites:
        point = gpd.GeoSeries(
            [Point(float(site["lon"]), float(site["lat"]))], crs=4326
        ).to_crs(panel.crs)
        x, y = point.x.iloc[0], point.y.iloc[0]
        ax.scatter(
            [x],
            [y],
            marker=brand.marker(site.get("type", "default")),
            s=brand.marker_size,
            color=brand.site_marker,
            edgecolor="#FFFFFF",
            linewidth=0.6,
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
    return texts


def _add_north_arrow(ax, brand: Brand) -> None:
    """A plain north arrow in the top-right corner of the panel."""
    ax.annotate(
        "N",
        xy=(0.965, 0.085),
        xytext=(0.965, 0.018),
        xycoords="axes fraction",
        textcoords="axes fraction",
        ha="center",
        va="center",
        fontsize=brand.size("scale_bar"),
        color=brand.text,
        arrowprops=dict(arrowstyle="-|>", color=brand.text, lw=0.8, shrinkA=0, shrinkB=0),
        zorder=11,
    )


def _add_scale_bar(ax, brand: Brand) -> None:
    """A scale bar in kilometres, rounded to a readable distance."""
    x0, x1 = ax.get_xlim()
    y0, y1 = ax.get_ylim()
    span_km = (x1 - x0) / 1000.0

    bar_km = _nice_distance(span_km * 0.25)
    bar_m = bar_km * 1000
    bar_x = x0 + (x1 - x0) * 0.03
    bar_y = y0 + (y1 - y0) * 0.035
    bar_height = (y1 - y0) * 0.007

    ax.add_patch(
        Rectangle(
            (bar_x, bar_y),
            bar_m,
            bar_height,
            facecolor=brand.text,
            edgecolor="none",
            zorder=10,
        )
    )
    ax.text(
        bar_x + bar_m / 2,
        bar_y + bar_height * 2.4,
        f"{bar_km:g} km",
        ha="center",
        va="bottom",
        fontsize=brand.size("scale_bar"),
        color=brand.text,
        zorder=10,
    )


def _nice_distance(raw_km: float) -> float:
    """Round a distance down to 1, 2 or 5 times a power of ten."""
    if raw_km <= 0:
        return 1
    magnitude = 10 ** int(f"{raw_km:e}".split("e")[1])
    for step in (1, 2, 5, 10):
        if step * magnitude >= raw_km:
            return step * magnitude
    return 10 * magnitude


def _add_legend(figure, panel: Panel, brand: Brand, *, target) -> None:
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
        bbox_to_anchor=(box.x0, box.y0 - 0.012),
        frameon=False,
        fontsize=brand.size("legend"),
        handletextpad=0.6,
        labelspacing=0.4,
        borderpad=0.0,
        ncols=min(len(handles), 3),
        columnspacing=1.4,
    )
    for text in legend.get_texts():
        text.set_color(brand.text)


def _connect(figure, panel_from: Panel, panel_to: Panel, brand: Brand) -> None:
    """Draw a solid arrow from the highlighted unit into the next panel."""
    highlighted = panel_from.frame[panel_from.highlight_mask]
    if highlighted.empty:
        return
    anchor = highlighted.geometry.union_all().representative_point()

    patch = ConnectionPatch(
        xyA=(anchor.x, anchor.y),
        coordsA=panel_from.ax.transData,
        xyB=(-0.025, 0.5),
        coordsB=panel_to.ax.transAxes,
        arrowstyle="-|>",
        mutation_scale=11,
        linewidth=brand.width("connector"),
        color=brand.connector,
        zorder=20,
        clip_on=False,
    )
    figure.add_artist(patch)


def _source_line() -> str:
    """The attribution line printed at the foot of every map."""
    return (
        "Boundaries: Survey of India (states); Local Government Directory via BharatMaps "
        "(districts, blocks). Names and codes: LGD. Boundary data as of December 2023. "
        f"Map generated {date.today().isoformat()}."
    )
