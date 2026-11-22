import json, os, sys, unittest
from datetime import date, timedelta
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import pause_agent as p

RULES = json.load(open(os.path.join(os.path.dirname(__file__), "..", "rules.json")))
END = date(2026, 11, 14)


def rows(ad, aset, days, spend, buys, budget=300, first=None):
    first = first or END - timedelta(days=days - 1)
    return [{"date": first + timedelta(days=i), "ad_id": ad, "ad_name": ad, "adset_id": aset,
             "spend": spend, "purchases": buys, "adset_daily_budget": budget} for i in range(days)]


class T(unittest.TestCase):
    def acts(self, rs, rules=RULES):
        return p.run(rs, rules, END)

    def test_pauses_ad_with_cpa_above_multiple(self):
        r = self.acts(rows("x", "s", 7, 300, 2))  # CPA 150 > 90, 14 purchases
        self.assertEqual([a["ad_id"] for a in r["actions"] if a["action"] == "pause_ad"], ["x"])

    def test_does_not_pause_below_min_purchases(self):
        r = self.acts(rows("x", "s", 7, 300, 1))  # CPA 300 but only 7 purchases
        self.assertEqual([a for a in r["actions"] if a["action"] == "pause_ad"], [])

    def test_does_not_pause_exactly_at_the_limit(self):
        r = self.acts(rows("x", "s", 7, 180, 2))  # 14 purchases, CPA exactly 90 = 3x target, not above
        self.assertEqual([a for a in r["actions"] if a["action"] == "pause_ad"], [])

    def test_pauses_zero_purchase_bleeder(self):
        r = self.acts(rows("x", "s", 7, 60, 0))
        self.assertEqual(len([a for a in r["actions"] if a["action"] == "pause_ad"]), 1)

    def test_new_ad_is_held_not_paused(self):
        r = self.acts(rows("x", "s", 2, 100, 0))
        self.assertEqual(r["actions"], [])
        self.assertEqual(len(r["held"]), 1)

    def test_raise_needs_every_day_under_target(self):
        good = rows("x", "s", 7, 100, 5)           # CPA 20 each day
        self.assertEqual([a["action"] for a in self.acts(good)["actions"] if a["action"] == "raise_budget"], ["raise_budget"])
        bad = rows("x", "s", 7, 100, 5)
        bad[-1]["purchases"] = 1                    # one bad day inside the streak
        self.assertEqual([a for a in self.acts(bad)["actions"] if a["action"] == "raise_budget"], [])

    def test_raise_is_blocked_by_the_daily_cap(self):
        r = self.acts(rows("x", "s", 7, 100, 5, budget=950))
        self.assertEqual([a for a in r["actions"] if a["action"] == "raise_budget"], [])
        self.assertEqual(len(r["blocked"]), 1)

    def test_nothing_is_ever_applied(self):
        r = self.acts(rows("x", "s", 7, 300, 2))
        self.assertEqual(r["mode"], "report-only")
        self.assertTrue(all(a["status"] == "proposed" for a in r["actions"]))

    def test_draft_requests_come_from_the_lowest_cpa_ad(self):
        r = self.acts(rows("lo", "s", 7, 100, 5) + rows("hi", "s2", 7, 100, 3))
        d = [a for a in r["actions"] if a["action"] == "draft_variants"]
        self.assertEqual((len(d), d[0]["from_ad"], d[0]["create_paused"]), (1, "lo", True))

    def test_report_runs_on_the_committed_fixture(self):
        fx = p.load(os.path.join(os.path.dirname(__file__), "..", "data", "ads-export.csv"))
        text = p.report(p.run(fx, RULES, END), RULES)
        self.assertIn("Nothing was changed in any ad account", text)


if __name__ == "__main__":
    unittest.main()
