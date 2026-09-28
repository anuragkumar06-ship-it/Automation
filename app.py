"""Locator map dashboard.

A browser front end for the same pipeline the command line uses. Nobody has to
edit a YAML file or type a command: states, districts and blocks come from
dropdowns built out of the boundary data itself, so a misspelt name is not
something a user can produce.

Run it with:

    streamlit run app.py
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import streamlit as st

from locator import cache as cache_module, data as data_module
from locator import geocode, sites as sites_module, theme
from locator.cli import run_from_config
from locator.names import display
from locator.validate import INFO

PROJECT_ROOT = Path(__file__).resolve().parent


@st.cache_data(show_spinner=False)
def _site_types() -> list[str]:
    """The kinds of site on offer, read from style/brand.yaml.

    Kept in the brand file rather than here so the menu and the shapes drawn
    on the map cannot drift apart.
    """
    from locator.style import load_brand

    return load_brand(PROJECT_ROOT / "style" / "brand.yaml").site_types


SITE_TYPES = _site_types()

# Bump this whenever the sites table's shape or its defaults change, so open
# browser sessions do not carry stale rows across the change.
SITES_SCHEMA = 2


# --------------------------------------------------------------------------
# data, loaded once and kept for the life of the server
# --------------------------------------------------------------------------


# Only the layers a given map needs are ever loaded, one state at a time.
# Loading the national district and block layers took 1,016 MB, which is over
# what a hosted app is allowed before the framework's own overhead - the app
# would have been killed on its first boot.
CORE_LAYERS = ("states", "districts", "blocks")


@st.cache_resource(show_spinner="Getting the boundary data ready. This happens once.")
def _boundaries():
    """Make sure there is boundary data to read, without reading all of it.

    The prepared cache is what a deployment ships and all the app needs. Only
    a checkout that has never been prepared falls back to downloading the raw
    national files, which is a local-development path, not a hosted one.
    """
    if cache_module.cache_is_ready():
        return True
    for key in CORE_LAYERS:
        data_module.ensure_dataset(key)
    return True


@st.cache_data(show_spinner=False)
def _state_options() -> list[tuple[str, int]]:
    """States for the dropdown, from the index: names and codes, no geometry."""
    index = cache_module.read_index()
    if index is not None:
        pairs = {int(r.state_lgd): display(r.state_name) for r in index.itertuples()}
        return sorted((name, lgd) for lgd, name in pairs.items())

    states = data_module.load_states()
    real = states[~states["disputed"]]
    return sorted((display(r["name"]), int(r["lgd"])) for _, r in real.iterrows())


@st.cache_data(show_spinner=False)
def _district_options(state_lgd: int) -> list[tuple[str, int]]:
    """Districts for the dropdown, also from the index where there is one."""
    index = cache_module.read_index()
    if index is not None:
        rows = index[index["state_lgd"].astype("int64") == int(state_lgd)]
        if len(rows):
            return sorted(
                (display(r.district_name), int(r.dist_lgd)) for r in rows.itertuples()
            )

    districts = data_module.districts_of(state_lgd)
    return sorted((display(r["name"]), int(r["lgd"])) for _, r in districts.iterrows())


@st.cache_resource(show_spinner=False)
def _district_shape(state_lgd: int, district_lgd: int):
    """The district polygon and its bounding box, used to aim the search."""
    districts = data_module.districts_of(state_lgd)
    match = districts[districts["lgd"].astype("int64") == int(district_lgd)]
    if match.empty:
        return None, None
    geometry = match.iloc[0]["geometry"]
    return geometry, tuple(float(v) for v in geometry.bounds)


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

    # The table starts empty. It used to be seeded with a hospital in Madurai,
    # which then followed the user into every other district and failed the
    # "is this site inside the district?" check every time.
    #
    # The version number matters. Streamlit keeps session_state across a code
    # reload, so a browser tab open from before that change still held the
    # seeded row and kept failing in exactly the way the change was meant to
    # stop. Bumping this resets those tabs once.
    if st.session_state.get("sites_schema") != SITES_SCHEMA:
        st.session_state.sites = sites_module.empty_sites()
        st.session_state.sites_schema = SITES_SCHEMA
        st.session_state.pop("pending_site", None)
    if "sites" not in st.session_state:
        st.session_state.sites = sites_module.empty_sites()
    st.session_state.setdefault("sites_rev", 0)
    st.session_state.setdefault("geo_results", [])
    st.session_state.setdefault("geo_widened", False)

    # ---- look a place up rather than typing coordinates ------------------
    with st.expander("Find a place by name", expanded=False):
        st.markdown(
            '<div class="cf-caption">Searches OpenStreetMap and shows what it '
            "matched, with the address, so you can check it is the right place "
            "before adding it. If it does not know the place it says so — it "
            "never guesses a coordinate.</div>",
            unsafe_allow_html=True,
        )
        query = st.text_input(
            "Name of the place",
            key="geo_query",
            placeholder="Government Rajaji Hospital",
        )
        found_type = st.selectbox("Mark it as", SITE_TYPES, key="geo_type")

        wider = st.checkbox(
            "Search beyond this district",
            value=False,
            key="geo_wider",
            help=(
                "Off, only places inside the district are offered, which is what "
                "stops a search for a place in Jammu returning one in Srinagar. "
                "Turn it on if the site genuinely sits just outside."
            ),
        )

        if st.button("Search", use_container_width=True, key="geo_search"):
            if not query.strip():
                st.session_state.geo_results = []
                st.warning("Type a place name first.")
            else:
                shape, bbox = _district_shape(state_lgd, district_lgd)
                from shapely.geometry import Point

                def _inside(lat, lon):
                    return shape is None or shape.contains(Point(lon, lat))

                try:
                    with st.spinner(f"Looking for “{query}” in {district_name}..."):
                        if wider:
                            found = geocode.search(
                                query, near=f"{district_name}, {state_name}", limit=8
                            )
                            source, tried = "", []
                        else:
                            # Each service in turn until one answers, every
                            # result checked against the district itself.
                            found, source, tried = geocode.search_best(
                                query, bbox=bbox, keep=_inside, limit=8
                            )

                    if shape is not None:
                        found = [p.with_inside(_inside(p.lat, p.lon)) for p in found]
                        found.sort(key=lambda p: (not p.inside, -p.importance))

                    st.session_state.geo_results = found
                    st.session_state.geo_widened = wider
                    st.session_state.geo_source = source
                    st.session_state.geo_tried = tried
                except geocode.GeocodeError as exc:
                    st.session_state.geo_results = []
                    st.error(str(exc))

        results = st.session_state.geo_results
        if results and st.session_state.get("geo_source"):
            st.caption(f"Found by {st.session_state['geo_source']}.")
        if results:
            chosen = st.radio(
                f"{len(results)} match(es) — pick the right one",
                options=list(range(len(results))),
                format_func=lambda i: results[i].label(),
                key="geo_choice",
            )
            if st.button("Add to sites", type="primary", use_container_width=True):
                place = results[chosen]
                st.session_state.pending_site = {
                    "name": query.strip() or place.name,
                    "lat": place.lat,
                    "lon": place.lon,
                    "type": found_type,
                }
                st.session_state.geo_results = []
                st.rerun()
        elif st.session_state.get("geo_search"):
            if st.session_state.get("geo_widened"):
                st.info(
                    "No match anywhere in India. The place is very likely not in "
                    "OpenStreetMap under that name — small rural facilities often "
                    "are not. Type the coordinates in below instead."
                )
            else:
                tried = st.session_state.get("geo_tried") or ["OpenStreetMap"]
                has_google = bool(os.environ.get("GOOGLE_MAPS_API_KEY"))
                extra = (
                    ""
                    if has_google
                    else " Setting a Google Maps API key would add Google Places as a "
                    "third place to look; see DEPLOY.md."
                )
                st.info(
                    f"No match inside {district_name} district. Tried "
                    f"{', '.join(tried)}. That usually means none of them holds that "
                    f"name here, not that the place does not exist. Try a nearby "
                    f"landmark, tick “Search beyond this district”, or type the "
                    f"coordinates in below.{extra}"
                )

    sites_table = st.data_editor(
        st.session_state.sites,
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "name": st.column_config.TextColumn("Name", width="medium"),
            "lat": st.column_config.NumberColumn("Lat", format="%.5f"),
            "lon": st.column_config.NumberColumn("Lon", format="%.5f"),
            "type": st.column_config.SelectboxColumn(
                "Type", options=SITE_TYPES, width="medium"
            ),
        },
        key=f"sites_editor_{st.session_state.sites_rev}",
    )
    # Say, per row, whether it falls in the district being mapped. Sites stay
    # in the table when the district changes, which is usually what you want,
    # but it meant a leftover site from another district failed the check and
    # the message named that row while the user was looking at the one they
    # had just added.
    _checked, _problems = sites_module.sites_from_table(sites_table)
    if _checked:
        shape, _ = _district_shape(state_lgd, district_lgd)
        if shape is not None:
            from shapely.geometry import Point

            strays = [
                site for site in _checked
                if not shape.contains(Point(site["lon"], site["lat"]))
            ]
            if strays:
                names = ", ".join(s["name"] for s in strays)
                st.warning(
                    f"{len(strays)} site(s) are not inside {district_name} district: "
                    f"{names}. They are probably left over from another district."
                )
                if st.button(
                    f"Remove the {len(strays)} site(s) outside {district_name}",
                    use_container_width=True,
                    key="drop_strays",
                ):
                    keep = [s for s in _checked if s not in strays]
                    st.session_state.sites = (
                        pd.DataFrame(keep) if keep else sites_module.empty_sites()
                    )
                    st.session_state.sites_rev += 1
                    st.rerun()
            else:
                st.caption(
                    f"All {len(_checked)} site(s) fall inside {district_name} district."
                )
    for _problem in _problems:
        st.warning(_problem)

    # A site picked from the search is merged into whatever is in the table
    # right now, so adding one never discards rows typed by hand.
    pending = st.session_state.pop("pending_site", None)
    if pending is not None:
        st.session_state.sites = pd.concat(
            [sites_table, pd.DataFrame([pending])], ignore_index=True
        )
        st.session_state.sites_rev += 1
        st.rerun()

    # Deliberately NOT written back to st.session_state.sites on every run.
    # st.data_editor tracks edits as a delta against the frame it was given,
    # so replacing that frame underneath a live widget key made rows double
    # up, revert or vanish. The stored frame is the seed; it only changes when
    # we add a row ourselves, and the key is bumped when it does.

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


def _output_root() -> Path:
    """A private folder per browser session.

    Maps used to be written into the app's own folder, so two people rendering
    with the same output name overwrote each other's files and could download
    the wrong map. Each session now gets its own directory.
    """
    import tempfile

    if "output_root" not in st.session_state:
        st.session_state.output_root = tempfile.mkdtemp(prefix="locator-")
    return Path(st.session_state.output_root)


def _build_config() -> dict:
    sites, problems = sites_module.sites_from_table(sites_table)
    for problem in problems:
        st.warning(problem)
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
        outcome = run_from_config(config, force=force, output_root=_output_root())

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
    "Place search: OpenStreetMap contributors, via Nominatim (ODbL).<br>"
    "Cognizant Foundation India logo used under the communication guidelines: approval "
    "is required for each use.</div>",
    unsafe_allow_html=True,
)
