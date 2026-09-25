"""Validation behaviour, checked against the real boundary layers.

These tests need the files in data/raw. If they are not downloaded yet the
module is skipped rather than failing, so a fresh clone can still run the rest
of the suite.
"""

import pytest

from locator import data as data_module
from locator.names import load_aliases
from locator.validate import validate_request

def _boundaries_available() -> bool:
    """Whether these tests can run at all.

    The prepared cache is enough - that is all a deployment ships, and all the
    app reads. Falling back to the raw files covers a checkout that has not
    been prepared yet. Checking only for raw files, as this used to, meant the
    whole suite skipped itself on a fresh clone while still reporting success.
    """
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

# Looked up against OpenStreetMap, not typed from memory. An earlier value
# here was 1,482 m out and passed every check, which is the whole reason the
# project treats a plausible coordinate as more dangerous than a wrong one.
GRH = {
    "name": "Government Rajaji Hospital (GRH)",
    "lat": 9.9270866,
    "lon": 78.1304238,
    "type": "hospital",
}


@pytest.fixture(scope="module")
def aliases():
    return load_aliases(data_module.data_dir() / "aliases.csv")


def run(aliases, **kwargs):
    defaults = {"state": "Tamil Nadu", "district": "Madurai", "blocks": [], "sites": []}
    defaults.update(kwargs)
    return validate_request(aliases=aliases, **defaults)


class TestMaduraiCase:
    """Case 1 from the brief, which the old AI-generated map got wrong."""

    def test_passes_with_no_errors_or_warnings(self, aliases):
        report, target = run(aliases, blocks=["Madurai West"], sites=[GRH])
        assert report.errors == []
        assert report.warnings == []
        assert target is not None

    def test_madurai_has_exactly_thirteen_blocks(self, aliases):
        _, target = run(aliases, blocks=["Madurai West"])
        assert len(target.blocks) == 13

    def test_tamil_nadu_has_thirty_eight_districts(self, aliases):
        _, target = run(aliases, blocks=["Madurai West"])
        assert len(target.districts) == 38

    def test_mayiladuthurai_is_present(self, aliases):
        _, target = run(aliases, blocks=["Madurai West"])
        assert "mayiladuthurai" in set(target.districts["name_key"])

    @pytest.mark.parametrize(
        "invented",
        ["Kallandiri", "Othakadai", "Ayilangudi", "Sakkimangalam", "Vellikundram", "Mathur"],
    )
    def test_blocks_invented_by_the_old_map_are_rejected(self, aliases, invented):
        report, target = run(aliases, blocks=[invented])
        assert report.errors, f"{invented} should not be accepted as a Madurai block"
        assert target is None


class TestSpellingVariants:
    def test_brief_spelling_of_thirumangalam_is_accepted(self, aliases):
        report, target = run(aliases, blocks=["Thirumangalam"])
        assert report.errors == []
        assert target.target_block_names == ["TIRUMANGALAM"]

    def test_brief_spelling_of_thiruparankundram_is_accepted(self, aliases):
        report, target = run(aliases, blocks=["Thiruparankundram"])
        assert report.errors == []
        assert target.target_block_names == ["TIRUPPARANGUNRAM"]

    def test_spacing_of_t_kallupatti_does_not_matter(self, aliases):
        report, target = run(aliases, blocks=["T. Kallupatti"])
        assert report.errors == []
        assert target.target_block_names == ["T.KALLUPATTI"]


class TestSiteChecks:
    def test_site_in_a_different_block_warns_and_names_the_real_one(self, aliases):
        report, _ = run(aliases, blocks=["Madurai East"], sites=[GRH])
        warnings = " ".join(i.message for i in report.warnings)
        assert "Madurai West" in warnings

    def test_site_outside_the_district_is_an_error(self, aliases):
        chennai = {"name": "Somewhere in Chennai", "lat": 13.0827, "lon": 80.2707}
        report, target = run(aliases, blocks=["Madurai West"], sites=[chennai])
        assert report.errors
        assert target is None

    def test_swapped_latitude_and_longitude_is_caught(self, aliases):
        swapped = {"name": "Swapped", "lat": 78.1193, "lon": 9.9195}
        report, target = run(aliases, blocks=["Madurai West"], sites=[swapped])
        assert report.errors
        assert target is None


class TestUnknownNames:
    def test_unknown_district_stops_the_render(self, aliases):
        report, target = run(aliases, district="Madurrai")
        assert report.errors
        assert target is None

    def test_unknown_district_suggests_the_right_one(self, aliases):
        report, _ = run(aliases, district="Madurrai")
        assert "Madurai" in " ".join(i.message for i in report.errors)

    def test_unknown_state_stops_the_render(self, aliases):
        report, target = run(aliases, state="Tamil Nadoo", district="Madurai")
        assert report.errors
        assert target is None

    def test_unknown_block_lists_the_real_blocks(self, aliases):
        report, _ = run(aliases, blocks=["Nowhere"])
        message = " ".join(i.message for i in report.errors)
        assert "Alanganallur" in message and "Vadipatti" in message


class TestForceBehaviour:
    def test_force_does_not_override_errors(self, aliases):
        report, _ = run(aliases, district="Madurrai")
        assert report.blocks_render(force=True) is True

    def test_force_overrides_warnings_only(self, aliases):
        report, _ = run(aliases, blocks=["Madurai East"], sites=[GRH])
        assert report.warnings
        assert report.blocks_render(force=False) is True
        assert report.blocks_render(force=True) is False


class TestBhagalpurCase:
    """Case 2 from the brief."""

    def test_bhagalpur_passes_with_sixteen_blocks(self, aliases):
        report, target = validate_request(
            state="Bihar",
            district="Bhagalpur",
            blocks=["Sabour"],
            sites=[],
            aliases=aliases,
        )
        assert report.errors == []
        assert report.warnings == []
        assert len(target.blocks) == 16


class TestTehsilFallback:
    """Districts created after the block register was last published.

    Seventeen Rajasthan districts have a district boundary but no blocks. The
    tehsils that make them up do exist, filed under the district each was
    carved out of, so they are picked up by location instead of by code.
    """

    def test_a_district_without_blocks_still_produces_a_map(self, aliases):
        report, target = validate_request(
            state="Rajasthan", district="Balotra", blocks=[], sites=[], aliases=aliases
        )
        assert report.errors == []
        assert target is not None

    def test_it_falls_back_to_tehsils_not_blocks(self, aliases):
        _, target = validate_request(
            state="Rajasthan", district="Balotra", blocks=[], sites=[], aliases=aliases
        )
        assert target.unit_level == "tehsil"
        assert target.block_level_label == "tehsil"
        assert len(target.blocks) > 0

    def test_the_tehsils_cover_the_district(self, aliases):
        _, target = validate_request(
            state="Rajasthan", district="Balotra", blocks=[], sites=[], aliases=aliases
        )
        assert target.unit_coverage > 0.9

    def test_a_named_tehsil_can_be_highlighted(self, aliases):
        report, target = validate_request(
            state="Rajasthan",
            district="Balotra",
            blocks=["Pachpadra"],
            sites=[],
            aliases=aliases,
        )
        assert report.errors == []
        assert target.target_block_names == ["Pachpadra"]

    def test_a_name_that_is_not_a_tehsil_is_rejected(self, aliases):
        report, target = validate_request(
            state="Rajasthan",
            district="Balotra",
            blocks=["Nowhere"],
            sites=[],
            aliases=aliases,
        )
        assert report.errors
        assert target is None

    def test_districts_with_blocks_are_unaffected(self, aliases):
        _, target = validate_request(
            state="Tamil Nadu", district="Madurai", blocks=[], sites=[], aliases=aliases
        )
        assert target.unit_level == "block"
