import unittest

import pandas as pd

from jobspy.e2e import _filter_it_jobs, _filter_usa_only


class TestE2EFilters(unittest.TestCase):
    def test_strict_usa_filter_keeps_only_us_locations(self):
        df = pd.DataFrame(
            [
                {"title": "Software Engineer", "description": "Python", "location": "Miami, FL, US"},
                {"title": "Developer", "description": "Java", "location": "Toronto, ON, Canada"},
                {"title": "Data Engineer", "description": "AWS", "location": "Austin, TX"},
            ]
        )

        filtered = _filter_usa_only(df, strict=True)
        self.assertEqual(len(filtered), 2)
        self.assertTrue(all("canada" not in loc.lower() for loc in filtered["location"].tolist()))

    def test_strict_usa_filter_drops_unknown_locations(self):
        df = pd.DataFrame(
            [
                {"title": "Software Engineer", "description": "Python", "location": "Remote"},
                {"title": "Developer", "description": "Java", "location": "United States"},
            ]
        )

        filtered = _filter_usa_only(df, strict=True)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered.iloc[0]["location"], "United States")

    def test_it_filter_keeps_it_roles(self):
        df = pd.DataFrame(
            [
                {"title": "Software Engineer", "description": "Build cloud platform", "location": "Orlando, FL, US"},
                {"title": "Cyber Security Analyst", "description": "InfoSec and SIEM", "location": "Miami, FL, US"},
            ]
        )

        filtered = _filter_it_jobs(df)
        self.assertEqual(len(filtered), 2)

    def test_it_filter_drops_non_it_roles(self):
        df = pd.DataFrame(
            [
                {"title": "Senior Cook", "description": "Kitchen operations", "location": "Miami, FL, US"},
                {"title": "Warehouse Associate", "description": "Forklift and shipping", "location": "Orlando, FL, US"},
            ]
        )

        filtered = _filter_it_jobs(df)
        self.assertEqual(len(filtered), 0)


if __name__ == "__main__":
    unittest.main()
