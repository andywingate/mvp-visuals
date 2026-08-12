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

from scrape_mvps import (
    _years_bucket,
    extract_search_profile,
    enrich_profile,
    build_summary,
)


class TestYearsBucket(unittest.TestCase):
    def test_zero_is_unknown(self):
        self.assertEqual(_years_bucket(0), "Unknown")

    def test_negative_is_unknown(self):
        self.assertEqual(_years_bucket(-1), "Unknown")

    def test_one_year(self):
        self.assertEqual(_years_bucket(1), "1 year")

    def test_two_to_three_years(self):
        self.assertEqual(_years_bucket(2), "2\u20133 years")
        self.assertEqual(_years_bucket(3), "2\u20133 years")

    def test_four_to_five_years(self):
        self.assertEqual(_years_bucket(4), "4\u20135 years")
        self.assertEqual(_years_bucket(5), "4\u20135 years")

    def test_six_to_ten_years(self):
        self.assertEqual(_years_bucket(6), "6\u201310 years")
        self.assertEqual(_years_bucket(10), "6\u201310 years")

    def test_over_ten_years(self):
        self.assertEqual(_years_bucket(11), "10+ years")
        self.assertEqual(_years_bucket(25), "10+ years")


class TestExtractSearchProfile(unittest.TestCase):
    def _raw(self, **overrides):
        base = {
            "userProfileIdentifier": "791c111d-ed9f-ea11-a811-000d3a8dfe0d",
            "firstName": "Alan",
            "lastName": "Murray",
            "addressCountryOrRegionName": "United Kingdom",
        }
        base.update(overrides)
        return base

    def test_basic_fields(self):
        p = extract_search_profile(self._raw())
        self.assertEqual(p["id"], "791c111d-ed9f-ea11-a811-000d3a8dfe0d")
        self.assertEqual(p["displayName"], "Alan Murray")
        self.assertEqual(p["country"], "United Kingdom")
        self.assertEqual(
            p["profileUrl"],
            "https://mvp.microsoft.com/en-US/MVP/profile/"
            "791c111d-ed9f-ea11-a811-000d3a8dfe0d",
        )
        # Enrichment defaults
        self.assertEqual(p["yearsInProgram"], 0)
        self.assertEqual(p["awardCategory"], "")
        self.assertEqual(p["techAreas"], [])

    def test_missing_fields_return_empty_strings(self):
        p = extract_search_profile({})
        self.assertEqual(p["id"], "")
        self.assertEqual(p["displayName"], "")
        self.assertEqual(p["country"], "")
        self.assertEqual(p["profileUrl"], "")
        self.assertEqual(p["techAreas"], [])

    def test_first_name_only(self):
        p = extract_search_profile(self._raw(lastName=""))
        self.assertEqual(p["displayName"], "Alan")

    def test_last_name_only(self):
        p = extract_search_profile(self._raw(firstName=""))
        self.assertEqual(p["displayName"], "Murray")


class TestEnrichProfile(unittest.TestCase):
    def _base_profile(self):
        return {
            "id": "abc-123",
            "displayName": "Test User",
            "country": "US",
            "profileUrl": "https://mvp.microsoft.com/en-US/MVP/profile/abc-123",
            "yearsInProgram": 0,
            "awardCategory": "",
            "techAreas": [],
        }

    def test_enrich_basic(self):
        profile = self._base_profile()
        detail = {
            "userProfile": {
                "yearsInProgram": 7,
                "awardCategory": "M365",
                "technologyFocusArea": ["Excel"],
            }
        }
        result = enrich_profile(profile, detail)
        self.assertEqual(result["yearsInProgram"], 7)
        self.assertEqual(result["awardCategory"], "M365")
        self.assertEqual(result["techAreas"], ["Excel"])

    def test_enrich_tech_area_as_string(self):
        profile = self._base_profile()
        detail = {
            "userProfile": {
                "yearsInProgram": 2,
                "awardCategory": "Azure",
                "technologyFocusArea": "Azure, Security",
            }
        }
        result = enrich_profile(profile, detail)
        self.assertEqual(result["techAreas"], ["Azure", "Security"])

    def test_enrich_missing_user_profile(self):
        profile = self._base_profile()
        result = enrich_profile(profile, {})
        self.assertEqual(result["yearsInProgram"], 0)
        self.assertEqual(result["awardCategory"], "")
        self.assertEqual(result["techAreas"], [])

    def test_enrich_returns_same_dict(self):
        profile = self._base_profile()
        result = enrich_profile(profile, {"userProfile": {}})
        self.assertIs(result, profile)


class TestBuildSummary(unittest.TestCase):
    def _profiles(self):
        return [
            {
                "country": "US",
                "techAreas": ["Excel", "Power BI"],
                "yearsInProgram": 2,
            },
            {
                "country": "UK",
                "techAreas": ["Excel"],
                "yearsInProgram": 12,
            },
            {
                "country": "US",
                "techAreas": ["Python"],
                "yearsInProgram": 0,
            },
        ]

    def test_by_country(self):
        s = build_summary(self._profiles())
        self.assertEqual(s["byCountry"]["US"], 2)
        self.assertEqual(s["byCountry"]["UK"], 1)

    def test_by_tech_area(self):
        s = build_summary(self._profiles())
        self.assertEqual(s["byTechArea"]["Excel"], 2)
        self.assertEqual(s["byTechArea"]["Power BI"], 1)
        self.assertEqual(s["byTechArea"]["Python"], 1)

    def test_by_length_of_service(self):
        s = build_summary(self._profiles())
        # yearsInProgram=2 -> "2-3 years"
        # yearsInProgram=12 -> "10+ years"
        # yearsInProgram=0 -> "Unknown"
        self.assertIn("2\u20133 years", s["byLengthOfService"])
        self.assertIn("10+ years", s["byLengthOfService"])
        self.assertIn("Unknown", s["byLengthOfService"])

    def test_empty_profiles(self):
        s = build_summary([])
        self.assertEqual(s["byCountry"], {})
        self.assertEqual(s["byTechArea"], {})
        self.assertEqual(s["byLengthOfService"], {})


if __name__ == "__main__":
    unittest.main()
