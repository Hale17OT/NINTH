import unittest

from ml.slips import parse_selection_text


SAMPLE = """21/07 15:39
Bet slip № 84697600807
22/07 02:07
213891 : Baseball. USA.
MLB. Toronto Blue Jays -
Tampa Bay Rays
Total
Over (6) 1.4
22/07 02:10
182355 : Baseball. USA.
MLB. Boston Red Sox - Baltimore Orioles
Total Under
(9.5)
1.49
21/07 15:39 Bonus. Bonuses. Bonuses - Accumulator bonus Bonus 1.11
22/07 03:05
219074 : Baseball. USA. MLB. Texas Rangers - Chicago White Sox W2 1.62
"""


class SlipParserTests(unittest.TestCase):
    def test_moneyline_and_total_rows_are_recognized(self):
        selections = parse_selection_text(SAMPLE, 2026)
        self.assertEqual(len(selections), 3)
        self.assertEqual([row["market"] for row in selections], ["totals", "totals", "moneyline"])
        self.assertEqual(selections[0]["total_side"], "over")
        self.assertEqual(selections[0]["total_line"], 6)
        self.assertEqual(selections[1]["total_side"], "under")
        self.assertEqual(selections[1]["total_line"], 9.5)
        self.assertEqual(selections[2]["selected_team"], "Chicago White Sox")


if __name__ == "__main__":
    unittest.main()
