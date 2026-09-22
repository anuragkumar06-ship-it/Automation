"""Brand settings, font resolution and projection choices.

Everything visual is read from ``style/brand.yaml`` so that a change of colour
or type size is a one-line edit in a file a non-programmer can open, not a code
change.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml
from matplotlib import font_manager

__all__ = ["Brand", "load_brand", "india_lcc", "local_crs"]


# Standard secant parallels for a Lambert conformal conic covering India.
# Using a conic here rather than plain latitude/longitude is what stops the
# north of the country being stretched sideways relative to the south.
INDIA_LCC = (
    "+proj=lcc +lat_1=12.472944 +lat_2=35.172806 +lat_0=24 +lon_0=80 "
    "+x_0=4000000 +y_0=4000000 +datum=WGS84 +units=m +no_defs"
)


@dataclass
class Brand:
    """Resolved brand settings for one render."""

    raw: dict
    font_family: str

    # -- colours ----------------------------------------------------------
    def colour(self, name: str) -> str:
        return self.raw["colours"][name]

    @property
    def text(self) -> str:
        return self.colour("text")

    @property
    def text_secondary(self) -> str:
        return self.colour("text_secondary")

    @property
    def text_muted(self) -> str:
        return self.colour("text_muted")

    @property
    def unit_fill(self) -> str:
        return self.colour("unit_fill")

    @property
    def unit_edge(self) -> str:
        return self.colour("unit_edge")

    @property
    def highlight(self) -> str:
        return self.colour("highlight")

    @property
    def highlight_secondary(self) -> str:
        return self.colour("highlight_secondary")

    @property
    def water(self) -> str:
        return self.colour("water")

    @property
    def background(self) -> str:
        return self.colour("background")

    @property
    def site_marker(self) -> str:
        return self.colour("site_marker")

    @property
    def callout(self) -> str:
        return self.colour("callout")

    @property
    def highlight_rim(self) -> str:
        return self.colour("highlight_edge")

    @property
    def context_fill(self) -> str:
        return self.colour("context_fill")

    @property
    def panel_fill(self) -> str:
        return self.colour("panel_fill")

    @property
    def panel_edge(self) -> str:
        return self.colour("panel_edge")

    @property
    def rule(self) -> str:
        return self.colour("rule")

    # -- label policy ------------------------------------------------------
    @property
    def label_density(self) -> str:
        return str(self.raw.get("labels", {}).get("density", "auto")).lower()

    @property
    def label_min_points(self) -> float:
        return float(self.raw.get("labels", {}).get("min_size_points", 8))

    # -- measurements ------------------------------------------------------
    def width(self, name: str) -> float:
        return float(self.raw["line_widths"][name])

    def size(self, name: str) -> float:
        return float(self.raw["type_sizes"][name])

    def layout(self, name: str) -> float:
        return float(self.raw["layout"][name])

    def marker(self, site_type: str) -> str:
        markers = self.raw["markers"]
        return markers.get((site_type or "").lower(), markers["default"])

    @property
    def marker_size(self) -> float:
        return float(self.raw["markers"]["size"])

    @property
    def show_logo(self) -> bool:
        return bool(self.raw["rules"]["show_logo"])

    def highlight_colours(self, count: int) -> list[str]:
        """Return ``count`` highlight colours, staying inside one accent group.

        The brand allows one accent group only, so this alternates between the
        primary and secondary teal rather than introducing a third hue.
        """
        if count <= 1:
            return [self.highlight]
        palette = [self.highlight, self.highlight_secondary]
        return [palette[i % 2] for i in range(count)]


def load_brand(path: str | Path | None = None) -> Brand:
    """Load ``style/brand.yaml`` and work out which font is actually available."""
    if path is None:
        path = Path(__file__).resolve().parent.parent / "style" / "brand.yaml"
    with Path(path).open(encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)
    return Brand(raw=raw, font_family=_resolve_font(raw["font"]["family"]))


def _resolve_font(candidates: list[str]) -> str:
    """Return the first candidate font that is installed on this machine.

    Falls back to matplotlib's bundled DejaVu Sans, which always exists, so a
    missing brand font changes the look but never stops a render.
    """
    installed = {f.name for f in font_manager.fontManager.ttflist}
    for candidate in candidates:
        if candidate in installed:
            return candidate
    return "DejaVu Sans"


def india_lcc() -> str:
    """Projection for the India panel."""
    return INDIA_LCC


def local_crs(frame) -> object:
    """Pick a local projection for a state or district panel.

    Uses the UTM zone the data actually falls in, which keeps shapes true at
    state and district scale. Deterministic for a given set of geometries.
    """
    return frame.estimate_utm_crs()
