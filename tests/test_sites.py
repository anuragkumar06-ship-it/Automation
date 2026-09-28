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
