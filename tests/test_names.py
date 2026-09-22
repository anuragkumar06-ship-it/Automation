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
