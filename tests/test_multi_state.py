"""Coverage maps spanning several states.

The thing these tests are really guarding is that each state is resolved
against its own layers. A district name is only unique inside its own state,
so anything that leaks from one state into the next would mark the wrong
district while every check still passed.
"""

import pytest

from locator import data as data_module
from locator.cli import coverage_areas, validate_config
from locator.names import load_aliases
from locator.render import COUNTRY_SNAP, _widen_extent
from locator.validate import validate_coverage_request


def _boundaries_available() -> bool:
    from locator import cache as cache_module

    if cache_module.cache_is_ready():
        return True
    return all(data_module.raw_path(k).exists() for k in ("states", "districts", "blocks"))


pytestmark = pytest.mark.skipif(
    not _boundaries_available(),
    reason=(
        "no boundary data: run `python -m locator fetch` then "
        "`python -m locator prepare`"
    ),
)


@pytest.fixture(scope="module")
def aliases():
    return load_aliases(data_module.data_dir() / "aliases.csv")


def run(aliases, areas, **kwargs):
    return validate_coverage_request(areas=areas, aliases=aliases, **kwargs)


THREE_STATES = [
    {"state": "Karnataka", "districts": ["Bengaluru Urban", "Mysuru"]},
    {"state": "Telangana", "districts": ["Hyderabad"]},
    {"state": "Delhi", "districts": ["New Delhi"]},
]


class TestSeveralStates:
    def test_passes_with_no_errors_or_warnings(self, aliases):
        report, target = run(aliases, THREE_STATES)
        assert report.errors == []
        assert report.warnings == []
        assert target is not None

    def test_is_a_multi_state_coverage_map(self, aliases):
        _, target = run(aliases, THREE_STATES)
        assert target.multi_state
        assert target.multi_district  # so the renderer never tries three panels
        assert len(target.area_parts) == 3

    def test_every_chosen_district_is_marked(self, aliases):
        _, target = run(aliases, THREE_STATES)
        assert len(target.target_district_lgds) == 4

    def test_each_state_keeps_its_own_districts(self, aliases):
        _, target = run(aliases, THREE_STATES)
        by_state = {part.state_name: part.district_names for part in target.area_parts}
        assert by_state["Karnataka"] == ["Bengaluru Urban", "Mysuru"]
        assert by_state["Telangana"] == ["Hyderabad"]
        assert by_state["Delhi"] == ["New Delhi"]

    def test_draws_every_district_of_every_chosen_state(self, aliases):
        _, target = run(aliases, THREE_STATES)
        # 31 + 33 + 11, so the unmarked districts are there to be drawn grey.
        assert len(target.districts) == 75

    def test_the_title_names_all_three_states(self, aliases):
        _, target = run(aliases, THREE_STATES)
        assert target.state_name == "Karnataka, Telangana and Delhi"


class TestNamesDoNotLeakBetweenStates:
    def test_a_district_of_another_chosen_state_is_rejected(self, aliases):
        # Hyderabad is a real district, but not of Karnataka. Resolving the
        # states together must not make it acceptable here.
        report, target = run(
            aliases,
            [
                {"state": "Karnataka", "districts": ["Hyderabad"]},
                {"state": "Telangana", "districts": ["Hyderabad"]},
            ],
        )
        assert report.errors
        assert target is None

    def test_a_name_in_two_states_marks_one_district_in_each(self, aliases):
        # Bilaspur exists in both Himachal Pradesh and Chhattisgarh. Marking by
        # LGD code rather than by name is what keeps these apart.
        report, target = run(
            aliases,
            [
                {"state": "Himachal Pradesh", "districts": ["Bilaspur"]},
                {"state": "Chhattisgarh", "districts": ["Bilaspur"]},
            ],
        )
        assert report.errors == []
        assert len(target.target_district_lgds) == 2
        assert len(set(target.target_district_lgds)) == 2


class TestRefusals:
    def test_a_state_with_no_district_chosen_is_an_error(self, aliases):
        report, target = run(
            aliases,
            [
                {"state": "Karnataka", "districts": ["Mysuru"]},
                {"state": "Telangana", "districts": []},
            ],
        )
        assert report.errors
        assert target is None

    def test_the_same_state_twice_is_an_error(self, aliases):
        report, target = run(
            aliases,
            [
                {"state": "Karnataka", "districts": ["Mysuru"]},
                {"state": "Karnataka", "districts": ["Bengaluru Urban"]},
            ],
        )
        assert report.errors
        assert target is None

    def test_an_unknown_state_is_an_error(self, aliases):
        report, target = run(
            aliases,
            [
                {"state": "Karnataka", "districts": ["Mysuru"]},
                {"state": "Nowhere", "districts": ["Anywhere"]},
            ],
        )
        assert report.errors
        assert target is None

    def test_no_states_at_all_is_an_error(self, aliases):
        report, target = run(aliases, [])
        assert report.errors
        assert target is None


class TestOneStateIsNotASpecialCase:
    def test_a_single_entry_gives_the_three_panel_map(self, aliases):
        report, target = run(
            aliases, [{"state": "Tamil Nadu", "districts": ["Madurai"]}]
        )
        assert report.errors == []
        assert not target.multi_state
        assert not target.multi_district
        # The third panel is populated, which is what makes it a locator map.
        assert len(target.blocks) == 13


class TestBlockDetail:
    """Each chosen district gets a block map of its own."""

    def test_one_detail_per_chosen_district(self, aliases):
        _, target = run(aliases, THREE_STATES)
        assert len(target.district_details) == 4
        assert [d.district_name for d in target.district_details] == [
            "Bengaluru Urban",
            "Mysuru",
            "Hyderabad",
            "New Delhi",
        ]

    def test_each_detail_carries_its_own_blocks(self, aliases):
        _, target = run(aliases, THREE_STATES)
        counts = {d.district_name: len(d.units) for d in target.district_details}
        assert counts["Bengaluru Urban"] == 5
        assert counts["Mysuru"] == 9
        assert all(d.unit_label == "block" for d in target.district_details)

    def test_blocks_can_be_marked_per_district(self, aliases):
        report, target = run(
            aliases,
            [
                {
                    "state": "Tamil Nadu",
                    "districts": ["Thanjavur"],
                    "blocks": {"Thanjavur": ["Orattanadu"]},
                },
                {"state": "Andhra Pradesh", "districts": ["Bapatla"]},
            ],
        )
        assert report.errors == []
        marked = {d.district_name: d.marked_names for d in target.district_details}
        assert marked["Thanjavur"] == ["ORATTANADU"]
        assert marked["Bapatla"] == []

    def test_a_block_of_the_wrong_district_is_rejected(self, aliases):
        # Orattanadu is a Thanjavur block, not a Nilgiris one.
        report, target = run(
            aliases,
            [
                {
                    "state": "Tamil Nadu",
                    "districts": ["The Nilgiris"],
                    "blocks": {"The Nilgiris": ["Orattanadu"]},
                },
                {"state": "Andhra Pradesh", "districts": ["Bapatla"]},
            ],
        )
        assert report.errors
        assert target is None

    def test_a_misspelled_block_is_rejected_with_a_suggestion(self, aliases):
        report, target = run(
            aliases,
            [
                {
                    "state": "Tamil Nadu",
                    "districts": ["Thanjavur"],
                    "blocks": {"Thanjavur": ["Orathanadu"]},
                },
                {"state": "Andhra Pradesh", "districts": ["Bapatla"]},
            ],
        )
        assert target is None
        assert any("Orattanadu" in i.message for i in report.errors)

    def test_it_can_be_turned_off(self, aliases):
        _, target = run(aliases, THREE_STATES, block_detail=False)
        assert target.district_details == []

    def test_turning_it_off_still_draws_the_overview(self, aliases):
        report, target = run(aliases, THREE_STATES, block_detail=False)
        assert report.errors == []
        assert target.multi_state
        assert len(target.target_district_lgds) == 4


class TestConfigShape:
    def test_coverage_entries_are_read(self):
        areas = coverage_areas(
            {"coverage": [{"state": "Karnataka", "districts": ["Mysuru"]}]}
        )
        assert areas == [{"state": "Karnataka", "districts": ["Mysuru"]}]

    def test_a_singular_district_in_an_entry_is_accepted(self):
        areas = coverage_areas({"coverage": [{"state": "Karnataka", "district": "Mysuru"}]})
        assert areas == [{"state": "Karnataka", "districts": ["Mysuru"]}]

    def test_an_old_single_state_config_has_no_coverage(self):
        assert coverage_areas({"state": "Tamil Nadu", "districts": ["Madurai"]}) is None

    def test_an_old_config_still_routes_to_the_single_state_path(self, aliases):
        report, target = validate_config(
            {"state": "Tamil Nadu", "district": "Madurai", "blocks": [], "sites": []},
            aliases=aliases,
        )
        assert report.errors == []
        assert not target.multi_state

    def test_a_coverage_config_routes_to_the_multi_state_path(self, aliases):
        report, target = validate_config(
            {"coverage": THREE_STATES, "blocks": [], "sites": []}, aliases=aliases
        )
        assert report.errors == []
        assert target.multi_state


class TestCombinedPdf:
    """Every map of one job in a single PDF, for sending as one attachment."""

    def _figures(self, count):
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        return [plt.figure(figsize=(4, 3)) for _ in range(count)]

    def test_it_writes_one_page_per_map(self, tmp_path):
        from locator.render import _write_bundle
        import matplotlib.pyplot as plt

        figures = self._figures(3)
        try:
            path = _write_bundle(figures, tmp_path, "everything")
        finally:
            for figure in figures:
                plt.close(figure)

        assert path.exists()
        data = path.read_bytes()
        assert data.startswith(b"%PDF")
        # Read without a PDF library on purpose: nothing in requirements.txt
        # parses PDFs, and this file is written by matplotlib's own backend.
        assert b"/Count 3" in data

    def test_it_is_named_after_the_map(self, tmp_path):
        from locator.render import _write_bundle
        import matplotlib.pyplot as plt

        figures = self._figures(2)
        try:
            path = _write_bundle(figures, tmp_path, "madurai_locator_all_maps")
        finally:
            for figure in figures:
                plt.close(figure)

        assert path.name == "madurai_locator_all_maps.pdf"


class TestFraming:
    """A tall, narrow frame is opened out rather than printed as a ribbon."""

    def test_a_tall_box_is_widened(self):
        x0, x1, y0, y1 = _widen_extent((0.0, 100.0, 0.0, 1000.0), min_aspect=1.0)
        assert pytest.approx(x1 - x0) == 1000.0
        assert (y0, y1) == (0.0, 1000.0)  # the height is never touched

    def test_a_wide_enough_box_is_left_alone(self):
        extent = (0.0, 2000.0, 0.0, 1000.0)
        assert _widen_extent(extent, min_aspect=1.0) == extent

    def test_widening_stays_inside_the_country(self):
        # Hard against the eastern edge, so the room has to be found to the
        # west rather than hanging the frame off the side of the country.
        limit = (0.0, 0.0, 2000.0, 2000.0)  # minx, miny, maxx, maxy
        x0, x1, _, _ = _widen_extent(
            (1800.0, 1900.0, 0.0, 1000.0), min_aspect=1.0, limit=limit
        )
        assert x0 >= limit[0]
        assert x1 <= limit[2]
        assert pytest.approx(x1 - x0) == 1000.0

    def test_a_national_frame_shows_the_whole_country(self):
        # Widened past COUNTRY_SNAP of the country's width, the frame becomes
        # the country itself rather than a slab cut across the north.
        limit = (0.0, 0.0, 1000.0, 3000.0)
        x0, x1, y0, y1 = _widen_extent(
            (400.0, 600.0, 0.0, 2000.0), min_aspect=2.0, limit=limit
        )
        assert (x1 - x0) >= COUNTRY_SNAP * (limit[2] - limit[0])
        assert y1 > 2000.0  # the full height of the country, padded
