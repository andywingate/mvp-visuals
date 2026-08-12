"""
Unit tests for scraper/scrape_mvps.py helper functions.

Run with:
    python -m pytest scraper/tests/test_scrape_mvps.py -v
or:
    python scraper/tests/test_scrape_mvps.py
"""

import sys
import os
import unittest

# Allow imports from the scraper directory
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scrape_mvps import _years_bucket, extract_profile, build_summary, CURRENT_YEAR


class TestYearsBucket(unittest.TestCase):
    def test_zero_is_unknown(self):
        self.assertEqual(_years_bucket(0), "Unknown")

    def test_negative_is_unknown(self):
        self.assertEqual(_years_bucket(-1), "Unknown")

    def test_one_year(self):
        self.assertEqual(_years_bucket(1), "1 year")

    def test_two_to_three_years(self):
        self.assertEqual(_years_bucket(2), "2–3 years")
        self.assertEqual(_years_bucket(3), "2–3 years")

    def test_four_to_five_years(self):
        self.assertEqual(_years_bucket(4), "4–5 years")
        self.assertEqual(_years_bucket(5), "4–5 years")

    def test_six_to_ten_years(self):
        self.assertEqual(_years_bucket(6), "6–10 years")
        self.assertEqual(_years_bucket(10), "6–10 years")

    def test_over_ten_years(self):
        self.assertEqual(_years_bucket(11), "10+ years")
        self.assertEqual(_years_bucket(25), "10+ years")


class TestExtractProfile(unittest.TestCase):
    def _raw(self, **overrides):
        base = {
            "userProfileIdentifier": "abc123",
            "firstName": "Jane",
            "lastName": "Doe",
            "screenNameLocalized": False,
            "addressCountryOrRegionName": "United States",
        }
        base.update(overrides)
        return base

    def _detail(self, **overrides):
        base = {
            "awardCategory": ["Azure", "Developer Technologies"],
            "yearsInProgram": 7,
        }
        base.update(overrides)
        return base

    def test_basic_fields(self):
        p = extract_profile(self._raw(), self._detail())
        self.assertEqual(p["id"], "abc123")
        self.assertEqual(p["displayName"], "Jane Doe")
        self.assertEqual(p["country"], "United States")
        self.assertEqual(p["stateOrProvince"], "")
        self.assertEqual(p["city"], "")
        self.assertEqual(p["techAreas"], ["Azure", "Developer Technologies"])
        self.assertEqual(p["consecutiveYears"], 7)
        self.assertEqual(p["firstAwardYear"], CURRENT_YEAR - 7 + 1)
        self.assertEqual(
            p["profileUrl"],
            "https://mvp.microsoft.com/en-US/mvp/profile/abc123",
        )

    def test_localized_name(self):
        raw = self._raw(
            screenNameLocalized=True,
            localizedFirstName="Janeth",
            localizedLastName="Doé",
        )
        p = extract_profile(raw)
        self.assertEqual(p["displayName"], "Janeth Doé")

    def test_unlocalized_name_falls_back_to_first_last(self):
        raw = self._raw(
            screenNameLocalized=False,
            localizedFirstName="Janeth",
            localizedLastName="Doé",
        )
        p = extract_profile(raw)
        self.assertEqual(p["displayName"], "Jane Doe")

    def test_tech_areas_as_string(self):
        p = extract_profile(self._raw(), {"awardCategory": "Azure, Security"})
        self.assertEqual(p["techAreas"], ["Azure", "Security"])

    def test_tech_areas_fallback_to_technologyFocusArea(self):
        p = extract_profile(self._raw(), {"technologyFocusArea": ["Cloud"]})
        self.assertEqual(p["techAreas"], ["Cloud"])

    def test_no_detail_returns_empty_tech_areas_and_zero_years(self):
        p = extract_profile(self._raw())
        self.assertEqual(p["techAreas"], [])
        self.assertEqual(p["firstAwardYear"], 0)
        self.assertEqual(p["consecutiveYears"], 0)

    def test_missing_id_returns_empty(self):
        raw = self._raw()
        del raw["userProfileIdentifier"]
        p = extract_profile(raw)
        self.assertEqual(p["id"], "")
        self.assertEqual(p["profileUrl"], "")

    def test_missing_fields_return_empty_strings(self):
        p = extract_profile({})
        self.assertEqual(p["id"], "")
        self.assertEqual(p["displayName"], "")
        self.assertEqual(p["country"], "")
        self.assertEqual(p["techAreas"], [])


class TestBuildSummary(unittest.TestCase):
    def _profiles(self):
        return [
            {
                "country": "US",
                "techAreas": ["Azure", "Security"],
                "firstAwardYear": 2024,
                "consecutiveYears": 1,
            },
            {
                "country": "UK",
                "techAreas": ["Azure"],
                "firstAwardYear": 2010,
                "consecutiveYears": 15,
            },
            {
                "country": "US",
                "techAreas": ["M365"],
                "firstAwardYear": 0,
                "consecutiveYears": 0,
            },
        ]

    def test_by_country(self):
        s = build_summary(self._profiles())
        self.assertEqual(s["byCountry"]["US"], 2)
        self.assertEqual(s["byCountry"]["UK"], 1)

    def test_by_tech_area(self):
        s = build_summary(self._profiles())
        self.assertEqual(s["byTechArea"]["Azure"], 2)
        self.assertEqual(s["byTechArea"]["Security"], 1)
        self.assertEqual(s["byTechArea"]["M365"], 1)

    def test_by_length_of_service(self):
        s = build_summary(self._profiles())
        # Using CURRENT_YEAR from the module:
        #   2024 → length = CURRENT_YEAR - 2024 + 1 = 2 → "2–3 years"
        #   2010 → length = CURRENT_YEAR - 2010 + 1 ≥ 11 → "10+ years"
        #   0    → length = 0 → "Unknown"
        self.assertIn("2–3 years", s["byLengthOfService"])
        self.assertIn("10+ years", s["byLengthOfService"])
        self.assertIn("Unknown", s["byLengthOfService"])

    def test_empty_profiles(self):
        s = build_summary([])
        self.assertEqual(s["byCountry"], {})
        self.assertEqual(s["byTechArea"], {})
        self.assertEqual(s["byLengthOfService"], {})


if __name__ == "__main__":
    unittest.main()
