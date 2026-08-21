import unittest

from ml.multisport.windows import WINDOWS, partition_fixed_window, row_season


def row(event_time, season=None):
    value = {"event_id": event_time, "event_time": event_time, "knowledge_time": event_time, "features": {}, "label": 1}
    if season is not None:
        value["season"] = season
    return value


class FixedSeasonWindowTests(unittest.TestCase):
    def test_football_and_nfl_windows_match_the_required_holdouts(self):
        self.assertEqual(WINDOWS["football"].development, tuple(range(2018, 2024)))
        self.assertEqual(WINDOWS["football"].holdout, (2024, 2025))
        self.assertEqual(WINDOWS["american-football"].development, tuple(range(2018, 2024)))
        self.assertEqual(WINDOWS["american-football"].holdout, (2024, 2025))

    def test_football_season_uses_the_july_boundary(self):
        self.assertEqual(row_season(row("2024-05-20T12:00:00+00:00"), "football"), 2023)
        self.assertEqual(row_season(row("2024-08-20T12:00:00+00:00"), "football"), 2024)

    def test_partition_fails_instead_of_silently_shrinking_the_required_window(self):
        rows = [row(f"{season}-08-20T12:00:00+00:00", season) for season in range(2019, 2026)]
        with self.assertRaisesRegex(ValueError, "missing development"):
            partition_fixed_window(rows, "football")

    def test_holdouts_are_disjoint_from_development(self):
        rows = [row(f"{season}-08-20T12:00:00+00:00", season) for season in range(2018, 2026)]
        partition = partition_fixed_window(rows, "football")
        self.assertEqual({item["_season"] for item in partition["development"]}, set(range(2018, 2024)))
        self.assertEqual({item["_season"] for item in partition["holdout"]}, {2024, 2025})


if __name__ == "__main__":
    unittest.main()
