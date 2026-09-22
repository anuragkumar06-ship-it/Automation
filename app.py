"""Locator map dashboard.

A browser front end for the same pipeline the command line uses. Nobody has to
edit a YAML file or type a command: states, districts and blocks come from
dropdowns built out of the boundary data itself, so a misspelt name is not
something a user can produce.

Run it with:

    streamlit run app.py
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from locator import data as data_module
from locator import theme
from locator.cli import run_from_config
from locator.names import display
from locator.validate import INFO

PROJECT_ROOT = Path(__file__).resolve().parent
SITE_TYPES = ["hospital", "school", "camp"]

st.set_page_config(
    page_title="Locator map generator | Cognizant Foundation India",
    page_icon=str(theme.LOGO_PATH) if theme.LOGO_PATH.exists() else "🗺️",
    layout="wide",
)

st.markdown(theme.css(), unsafe_allow_html=True)


# --------------------------------------------------------------------------
# data, loaded once and kept for the life of the server
# --------------------------------------------------------------------------


# The sub-district layer is large and only a handful of districts need it, so
# it is fetched on demand rather than at startup.
CORE_LAYERS = ("states", "districts", "blocks")


@st.cache_resource(show_spinner="Loading boundary data. This happens once.")
def _boundaries():
    """Download if needed, then load the three layers every map uses."""
    for key in CORE_LAYERS:
        data_module.ensure_dataset(key)
    return (
        data_module.load_states(),
        data_module.load_districts(),
        data_module.load_blocks(),
    )


@st.cache_data(show_spinner=False)
def _state_options() -> list[tuple[str, int]]:
    states, _, _ = _boundaries()
    real = states[~states["disputed"]]
    pairs = sorted((display(r["name"]), int(r["lgd"])) for _, r in real.iterrows())
    return pairs


@st.cache_data(show_spinner=False)
def _district_options(state_lgd: int) -> list[tuple[str, int]]:
    districts = data_module.districts_of(state_lgd)
    return sorted((display(r["name"]), int(r["lgd"])) for _, r in districts.iterrows())


@st.cache_data(show_spinner=False)
def _unit_options(district_lgd: int, district_lgd_geom_key: str) -> tuple[list[str], str]:
    """The units the third panel can highlight, and what they are called.

    Blocks where they exist. Where they do not — a district created after the
    block register was last published — the tehsils that fall inside the
    district, which are never called blocks.
    """
    blocks = data_module.blocks_of(district_lgd)
    if not blocks.empty:
        return sorted(display(n) for n in blocks["name"]), "block"

    districts = data_module.load_districts()
    row = districts[districts["lgd"].astype("int64") == int(district_lgd)]
    if row.empty:
        return [], "block"
    with st.spinner("Loading sub-district boundaries. This happens once."):
        tehsils, _ = data_module.subdistricts_within(row.iloc[0]["geometry"])
    if tehsils.empty:
        return [], "block"
    return sorted(display(n) for n in tehsils["name"]), "tehsil"


# --------------------------------------------------------------------------
# page
# --------------------------------------------------------------------------

st.markdown(
    theme.header_html(
        "Locator map generator",
        "Three-panel location maps for Cognizant Foundation India funding proposals. "
        "Every boundary comes from a published government dataset — nothing is drawn, "
        "estimated or generated.",
    ),
    unsafe_allow_html=True,
)

try:
    _boundaries()
except data_module.MissingDataError as exc:
    st.error("The boundary data could not be loaded.")
    st.code(str(exc))
    st.stop()

with st.sidebar:
    st.header("Where is the map?")

    state_pairs = _state_options()
    state_name = st.selectbox(
        "State or union territory",
        [name for name, _ in state_pairs],
        index=[name for name, _ in state_pairs].index("Tamil Nadu")
        if any(n == "Tamil Nadu" for n, _ in state_pairs)
        else 0,
    )
    state_lgd = dict(state_pairs)[state_name]

    district_pairs = _district_options(state_lgd)
    if not district_pairs:
        st.error(f"No districts are available for {state_name}.")
        st.stop()

    district_names = [name for name, _ in district_pairs]
    default_district = "Madurai" if "Madurai" in district_names else district_names[0]
    district_name = st.selectbox(
        "District",
        district_names,
        index=district_names.index(default_district),
    )
    district_lgd = dict(district_pairs)[district_name]

    block_names, unit_label = _unit_options(district_lgd, district_lgd_geom_key=district_name)
    if block_names:
        default_blocks = [b for b in ("Madurai West",) if b in block_names]
        blocks = st.multiselect(
            f"{unit_label.capitalize()}s to highlight "
            f"({len(block_names)} in this district)",
            block_names,
            default=default_blocks,
        )
        if unit_label == "tehsil":
            st.markdown(
                '<div class="cf-caption">Block boundaries are not published for this '
                "district, so its tehsils are offered instead. The map says so on its "
                "face.</div>",
                unsafe_allow_html=True,
            )
    else:
        blocks = []
        st.warning(
            f"Neither blocks nor tehsils are published for {district_name}. "
            f"The third panel will show the district on its own."
        )

    st.divider()
    st.header("Sites")
    st.caption(
        "Right-click a place in Google Maps and click the number pair at the top "
        "of the menu. The first number is lat, the second is lon."
    )

    if "sites" not in st.session_state:
        st.session_state.sites = pd.DataFrame(
            [
                {
                    "name": "Government Rajaji Hospital (GRH)",
                    "lat": 9.9195,
                    "lon": 78.1193,
                    "type": "hospital",
                }
            ]
        )

    sites_table = st.data_editor(
        st.session_state.sites,
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "name": st.column_config.TextColumn("Name", width="medium"),
            "lat": st.column_config.NumberColumn("Lat", format="%.5f"),
            "lon": st.column_config.NumberColumn("Lon", format="%.5f"),
            "type": st.column_config.SelectboxColumn("Type", options=SITE_TYPES),
        },
        key="sites_editor",
    )

    st.divider()
    with st.expander("Titles and output"):
        title = st.text_input(
            "Title", value="", placeholder=f"{district_name} district, {state_name}"
        )
        output_name = st.text_input(
            "Folder name for the files",
            value=f"{district_name.lower().replace(' ', '_')}_locator",
        )

    force = st.checkbox(
        "Draw anyway if there are warnings",
        value=False,
        help=(
            "Warnings stop a render so you have to read them first. This lets one "
            "through. It never gets past an error, and missing data always stops "
            "the map."
        ),
    )

    go = st.button("Make the map", type="primary", use_container_width=True)
    check_only = st.button("Run the checks only", use_container_width=True)


def _build_config() -> dict:
    sites = []
    for row in sites_table.to_dict("records"):
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        if pd.isna(row.get("lat")) or pd.isna(row.get("lon")):
            continue
        sites.append(
            {
                "name": name,
                "lat": float(row["lat"]),
                "lon": float(row["lon"]),
                "type": str(row.get("type") or "hospital"),
            }
        )
    return {
        "state": state_name,
        "district": district_name,
        "blocks": list(blocks),
        "sites": sites,
        "title": title.strip() or None,
        "output_name": output_name.strip() or "locator_map",
    }


def _show_report(report) -> None:
    """Print the validation result, grouped by how serious it is."""
    errors = report.errors
    warnings = report.warnings
    notes = [i for i in report.issues if i.severity == INFO]

    if errors:
        st.error(f"{len(errors)} problem(s) stopped the map.")
        for issue in errors:
            st.markdown(f"**{issue.check}** — {issue.message}")
    if warnings:
        st.warning(f"{len(warnings)} warning(s).")
        for issue in warnings:
            st.markdown(f"**{issue.check}** — {issue.message}")
    if notes:
        with st.expander(f"What was checked ({len(notes)} confirmed)", expanded=not errors):
            for issue in notes:
                st.markdown(f"- **{issue.check}** — {issue.message}")


if check_only:
    from locator.names import load_aliases
    from locator.validate import validate_request

    config = _build_config()
    aliases = load_aliases(PROJECT_ROOT / "data" / "aliases.csv")
    report, _ = validate_request(
        state=config["state"],
        district=config["district"],
        blocks=config["blocks"],
        sites=config["sites"],
        aliases=aliases,
    )
    st.subheader("Checks")
    _show_report(report)
    if not report.errors and not report.warnings:
        st.success("Everything checks out. Press “Make the map”.")

elif go:
    config = _build_config()
    with st.spinner("Checking the names and coordinates, then drawing. About 15 seconds."):
        outcome = run_from_config(config, force=force, output_root=PROJECT_ROOT / "output")

    st.subheader("Checks")
    _show_report(outcome["report"])

    if not outcome["rendered"]:
        if outcome["report"].errors:
            st.info("Fix the problems above and try again.")
        else:
            st.info(
                "Nothing was drawn because of the warnings above. Read them, and if "
                "they are fine, tick “Draw anyway if there are warnings” and press "
                "“Make the map” again."
            )
    else:
        output_dir = Path(outcome["output_dir"])
        name = config["output_name"]

        st.markdown(theme.rule_html(), unsafe_allow_html=True)
        st.subheader("Your map")
        preview = output_dir / f"{name}_300dpi.png"
        if preview.exists():
            st.markdown('<div class="cf-map">', unsafe_allow_html=True)
            st.image(str(preview), use_container_width=True)
            st.markdown("</div>", unsafe_allow_html=True)

        st.subheader("Download")
        wanted = [
            (f"{name}.svg", "SVG — vector, for a designer"),
            (f"{name}.pdf", "PDF — vector, for printing"),
            (f"{name}_300dpi.png", "PNG 300 dpi — documents and decks"),
            (f"{name}_600dpi.png", "PNG 600 dpi — large print"),
            ("render_log.txt", "Render log — what was used and checked"),
        ]
        columns = st.columns(len(wanted))
        for column, (filename, caption) in zip(columns, wanted):
            path = output_dir / filename
            if not path.exists():
                continue
            with column:
                st.download_button(
                    caption.split(" — ")[0],
                    data=path.read_bytes(),
                    file_name=filename,
                    use_container_width=True,
                )
                st.caption(caption.split(" — ", 1)[1])

        with st.expander("Render log"):
            log = output_dir / "render_log.txt"
            if log.exists():
                st.code(log.read_text(encoding="utf-8"), language="text")

else:
    st.markdown(
        '<div class="cf-note">Pick a state, district and block on the left, add your '
        "sites, then press <b>Make the map</b>.</div>",
        unsafe_allow_html=True,
    )
    st.markdown(theme.rule_html(), unsafe_allow_html=True)
    st.subheader("What gets checked before anything is drawn")
    st.markdown(
        """
- The district and block counts, against an independent register where one is recorded.
- That each site falls inside the district you picked, and **which block it really falls in**.
- That the blocks fit together with no gap in the district.
- That every boundary drawn comes from a published dataset.

A problem stops the map and says what is wrong. Nothing is ever guessed or filled in.
        """
    )

st.markdown(theme.rule_html(), unsafe_allow_html=True)
st.markdown(
    '<div class="cf-caption">Boundaries: Survey of India (states); Local Government '
    "Directory via BharatMaps (districts, blocks and sub-districts). Sources, licences "
    "and the date each was checked are recorded in <code>data/SOURCES.md</code>.<br>"
    "Cognizant Foundation India logo used under the communication guidelines: approval "
    "is required for each use.</div>",
    unsafe_allow_html=True,
)
