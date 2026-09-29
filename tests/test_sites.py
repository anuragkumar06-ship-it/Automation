"""The sites table: what reaches the map and what is reported instead.

These cover the bug that put sites called "nan" on maps. A blank cell arrives
as float NaN, NaN is truthy, so `str(value or "")` yields "nan" and every
emptiness guard walks past it.
"""

import pandas as pd
import pytest

from locator.sites import clean_number, clean_text, empty_sites, sites_from_table

NAN = float("nan")


def table(rows):
    return pd.DataFrame(rows, columns=["name", "lat", "lon", "type"])


class TestCleanText:
    @pytest.mark.parametrize("blank", [NAN, None, "", "   ", "nan", "NaN", "<NA>", "None"])
    def test_every_flavour_of_blank_reads_as_blank(self, blank):
        assert clean_text(blank) == ""

    def test_a_real_name_survives_untouched(self):
        assert clean_text("  Government Rajaji Hospital  ") == "Government Rajaji Hospital"

    def test_the_fallback_is_used_only_when_blank(self):
        assert clean_text(NAN, "hospital") == "hospital"
        assert clean_text("school", "hospital") == "school"


class TestCleanNumber:
    @pytest.mark.parametrize("blank", [NAN, None, "", "abc", float("inf")])
    def test_unusable_cells_become_none(self, blank):
        assert clean_number(blank) is None

    def test_numbers_come_through_as_floats(self):
        assert clean_number("25.18") == 25.18
        assert clean_number(25) == 25.0


class TestSitesFromTable:
    def test_a_blank_row_is_ignored_silently(self):
        sites, problems = sites_from_table(table([{"name": NAN, "lat": NAN, "lon": NAN, "type": NAN}]))
        assert sites == []
        assert problems == []

    def test_no_site_is_ever_called_nan(self):
        """The reported bug: a row with no name became a site named 'nan'."""
        sites, _ = sites_from_table(
            table([{"name": NAN, "lat": 25.18, "lon": 75.83, "type": "hospital"}])
        )
        assert sites == []

    def test_coordinates_without_a_name_are_reported_not_dropped(self):
        _, problems = sites_from_table(
            table([{"name": NAN, "lat": 25.18, "lon": 75.83, "type": "hospital"}])
        )
        assert len(problems) == 1
        assert "no name" in problems[0]

    def test_a_missing_coordinate_names_which_one(self):
        _, problems = sites_from_table(
            table([{"name": "Half a site", "lat": 25.2, "lon": NAN, "type": "school"}])
        )
        assert "longitude" in problems[0]
        assert "Half a site" in problems[0]

    def test_swapped_coordinates_are_caught_and_the_swap_is_suggested(self):
        _, problems = sites_from_table(
            table([{"name": "Swapped", "lat": 75.83, "lon": 25.18, "type": "health camp"}])
        )
        assert "swapped" in problems[0].lower()
        assert "25.18, 75.83" in problems[0]

    def test_somewhere_outside_india_is_refused(self):
        sites, problems = sites_from_table(
            table([{"name": "Paris", "lat": 48.85, "lon": 2.35, "type": "health camp"}])
        )
        assert sites == []
        assert "outside India" in problems[0]

    def test_a_good_row_passes_through_cleanly(self):
        sites, problems = sites_from_table(
            table([{"name": "City Hospital", "lat": 25.18, "lon": 75.83, "type": "hospital"}])
        )
        assert problems == []
        assert sites == [
            {"name": "City Hospital", "lat": 25.18, "lon": 75.83, "type": "hospital"}
        ]

    def test_a_blank_type_falls_back_to_hospital(self):
        sites, _ = sites_from_table(
            table([{"name": "Clinic", "lat": 25.18, "lon": 75.83, "type": NAN}])
        )
        assert sites[0]["type"] == "hospital"

    def test_good_rows_survive_alongside_bad_ones(self):
        sites, problems = sites_from_table(
            table([
                {"name": "Good one", "lat": 25.18, "lon": 75.83, "type": "hospital"},
                {"name": NAN, "lat": NAN, "lon": NAN, "type": NAN},
                {"name": "Bad one", "lat": 25.2, "lon": NAN, "type": "school"},
            ])
        )
        assert [s["name"] for s in sites] == ["Good one"]
        assert len(problems) == 1


class TestEmptySites:
    def test_it_starts_empty_with_the_right_columns(self):
        """It used to be seeded with a Madurai hospital, which then failed the
        district check in every other district."""
        frame = empty_sites()
        assert len(frame) == 0
        assert list(frame.columns) == ["name", "lat", "lon", "type"]

    def test_an_empty_table_yields_no_sites_and_no_complaints(self):
        sites, problems = sites_from_table(empty_sites())
        assert sites == []
        assert problems == []


class TestPanelHasNoAxisFurniture:
    """Panels must not carry chart axis labels.

    GeoPandas writes "Easting [metre]" and "Northing [metre]" onto any plot
    whose data is in a projected coordinate system. That is useful on an
    analyst's chart and meaningless on a locator map. Turning the whole axis
    off used to hide them, but that also hides the spines, and the spines draw
    the panel frame - so they have to be cleared explicitly.
    """

    def test_the_frame_clears_both_axis_labels(self):
        import inspect

        from locator import render

        source = inspect.getsource(render._frame_panel)
        assert 'set_xlabel("")' in source
        assert 'set_ylabel("")' in source

    def test_a_rendered_panel_carries_no_axis_label(self):
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        from locator.render import _frame_panel
        from locator.style import load_brand

        figure, ax = plt.subplots()
        # What geopandas does to a projected plot.
        ax.set_xlabel("Easting [metre]")
        ax.set_ylabel("Northing [metre]")

        _frame_panel(ax, load_brand())

        assert ax.get_xlabel() == ""
        assert ax.get_ylabel() == ""
        assert ax.get_xticks().size == 0
        assert ax.get_yticks().size == 0
        # The frame itself must survive: it is what draws the panel border.
        assert all(spine.get_visible() for spine in ax.spines.values())
        plt.close(figure)


class TestMultipleDistricts:
    """Several districts at once, which produces a state coverage map.

    The three-panel locator answers "where is this one place". Picking several
    districts answers a different question - where across a state a programme
    runs - so it produces one state map with each district marked, because the
    third panel would have nothing to show.
    """

    def aliases(self):
        from locator import data as data_module
        from locator.names import load_aliases

        return load_aliases(data_module.data_dir() / "aliases.csv")

    def test_one_district_still_gives_the_three_panel_map(self):
        from locator.validate import validate_request

        _, target = validate_request(
            state="Tamil Nadu", districts=["Madurai"], aliases=self.aliases()
        )
        assert target.multi_district is False
        assert target.district_names == ["Madurai"]

    def test_several_districts_are_all_resolved(self):
        from locator.validate import validate_request

        report, target = validate_request(
            state="Karnataka",
            districts=["Mysore", "Mandya", "Hassan", "Tumkur"],
            aliases=self.aliases(),
        )
        assert report.errors == []
        assert target.multi_district is True
        # Older spellings resolve to what LGD actually calls them.
        assert target.district_names == ["Mysuru", "Mandya", "Hassan", "Tumakuru"]

    def test_the_whole_state_is_still_carried_for_context(self):
        from locator.validate import validate_request

        _, target = validate_request(
            state="Karnataka", districts=["Mysuru", "Mandya"], aliases=self.aliases()
        )
        assert len(target.districts) == 31, "every district is drawn, two are marked"

    def test_a_wrong_name_among_several_is_named(self):
        from locator.validate import validate_request

        report, target = validate_request(
            state="Karnataka",
            districts=["Mysuru", "Nowhere At All"],
            aliases=self.aliases(),
        )
        assert target is None
        assert "Nowhere At All" in report.errors[0].message

    def test_duplicates_are_folded_together(self):
        from locator.validate import validate_request

        _, target = validate_request(
            state="Karnataka",
            districts=["Mysuru", "Mysore", "Mandya"],
            aliases=self.aliases(),
        )
        assert target.district_names == ["Mysuru", "Mandya"]

    def test_blocks_cannot_be_marked_across_several_districts(self):
        from locator.validate import validate_request

        report, target = validate_request(
            state="Karnataka",
            districts=["Mysuru", "Mandya"],
            blocks=["Some block"],
            aliases=self.aliases(),
        )
        assert target is None
        assert "one district at a time" in report.errors[0].message

    def test_the_old_single_district_spelling_still_works(self):
        from locator.validate import validate_request

        _, target = validate_request(
            state="Tamil Nadu", district="Madurai", aliases=self.aliases()
        )
        assert target.district_names == ["Madurai"]
