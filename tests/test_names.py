"""Name normalisation, matching and display formatting."""

from locator.names import AliasTable, display, key, strip_diacritics


class TestKey:
    def test_strips_survey_of_india_diacritics(self):
        assert key("TAMIL NĀDU") == "tamil nadu"
        assert key("ARUNĀCHAL PRADESH") == "arunachal pradesh"

    def test_ignores_punctuation_so_initials_match(self):
        assert key("T. Kallupatti") == key("T.KALLUPATTI") == "t kallupatti"

    def test_expands_ampersand(self):
        assert key("Dadra & Nagar Haveli") == "dadra and nagar haveli"

    def test_collapses_case_and_spacing(self):
        assert key("  madurai   EAST ") == "madurai east"

    def test_handles_none_and_empty(self):
        assert key(None) == ""
        assert key("") == ""


class TestDisplay:
    def test_uppercase_data_becomes_proper_noun_case(self):
        assert display("MADURAI EAST") == "Madurai East"
        assert display("TIRUPPARANGUNRAM") == "Tirupparangunram"

    def test_keeps_initials_and_brackets_capitalised(self):
        assert display("T.KALLUPATTI") == "T.Kallupatti"
        assert display("KAIMUR (BHABUA)") == "Kaimur (Bhabua)"

    def test_lowercases_joining_words_but_not_the_first(self):
        assert display("JAMMU AND KASHMIR") == "Jammu and Kashmir"

    def test_strips_diacritics_for_display(self):
        assert display("CHHAtTĪSGARH") == "Chhattisgarh"


class TestStripDiacritics:
    def test_removes_combining_marks_only(self):
        assert strip_diacritics("BIHĀR") == "BIHAR"
        assert strip_diacritics("Madurai") == "Madurai"


class TestAliasTable:
    def build(self):
        return AliasTable(
            [
                {
                    "level": "block",
                    "alias": "Thirumangalam",
                    "canonical": "TIRUMANGALAM",
                    "note": "spelling variant",
                }
            ]
        )

    def test_resolves_a_known_variant_and_reports_it(self):
        canonical, hit = self.build().resolve("block", "Thirumangalam")
        assert canonical == "TIRUMANGALAM"
        assert hit is not None
        assert "Thirumangalam" in hit.message()

    def test_matching_ignores_case_and_punctuation(self):
        canonical, hit = self.build().resolve("block", "thirumangalam")
        assert canonical == "TIRUMANGALAM"
        assert hit is not None

    def test_unknown_name_passes_through_untouched(self):
        canonical, hit = self.build().resolve("block", "Melur")
        assert canonical == "Melur"
        assert hit is None

    def test_level_is_respected(self):
        canonical, hit = self.build().resolve("district", "Thirumangalam")
        assert hit is None


class TestGeocoderContract:
    """The geocoder must never invent a coordinate.

    These check the shape of the contract without touching the network; the
    live behaviour is exercised by hand because it depends on a third-party
    service that must not be hammered by a test suite.
    """

    def test_an_empty_query_returns_nothing_without_asking(self):
        from locator.geocode import search

        assert search("") == []
        assert search("   ") == []

    def test_a_place_carries_the_record_it_came_from(self):
        from locator.geocode import Place

        place = Place(
            name="Government Rajaji Hospital",
            address="Government Rajaji Hospital, Panagal Salai, Madurai",
            lat=9.9270866,
            lon=78.1304238,
            kind="hospital",
            osm_id="way/123",
            importance=0.4,
        )
        label = place.label()
        assert "Madurai" in label
        assert "hospital" in label
        assert "9.92709" in label

    def test_the_rate_limit_is_at_least_one_second(self):
        from locator import geocode

        assert geocode.MIN_INTERVAL_SECONDS >= 1.0

    def test_it_identifies_itself_as_nominatim_policy_requires(self):
        from locator import geocode

        assert "locator-maps" in geocode.USER_AGENT

    def test_attribution_names_openstreetmap(self):
        from locator.geocode import attribution

        assert "OpenStreetMap" in attribution()
