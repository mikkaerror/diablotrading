import unittest
import tempfile
import pathlib
import inferno_ai_basket_signal_history as sh


def review(leaders, reduce, avoid, invested, cash, beating, nlv=706.41,
           rs=None, top_bucket=60, date="2026-07-20"):
    # LEADER/REDUCE are above the 200-day; AVOID is below it (breadth math)
    ranking = ([{"tag": "LEADER", "composite": 90, "above200": True, "above50": True} for _ in range(leaders)]
               + [{"tag": "REDUCE", "composite": 40, "above200": True, "above50": False} for _ in range(reduce)]
               + [{"tag": "AVOID", "composite": 5, "above200": False, "above50": False} for _ in range(avoid)])
    return {
        "composite": {"signalsTrusted": True, "ranking": ranking,
                      "generatedAt": date + "T12:00:00-06:00"},
        "benchmark": {"namesBeatingSector": beating, "basketBeatsBenchmark": False,
                      "concentration": {"AI-capex hardware complex": {"pct": top_bucket}}},
        "sizing": {"investedWeight": invested, "cashWeight": cash,
                   "params": {"nlv": nlv}},
        "holdings": {"nlv": nlv},
    }


class SnapshotTests(unittest.TestCase):
    def test_snapshot_extracts_the_scalars(self):
        s = sh.snapshot(review(2, 23, 5, 0.36, 0.64, 10))
        self.assertEqual(s["leaders"], 2)
        self.assertEqual(s["reduce"], 23)
        self.assertEqual(s["avoid"], 5)
        self.assertEqual(s["investedPct"], 36.0)
        self.assertEqual(s["cashPct"], 64.0)
        self.assertEqual(s["namesBeatingSector"], 10)
        self.assertEqual(s["date"], "2026-07-20")
        self.assertEqual(s["nlv"], 706.41)

    def test_snapshot_handles_missing_pieces(self):
        s = sh.snapshot({"composite": {"ranking": []}})
        self.assertEqual(s["leaders"], 0)
        self.assertEqual(s["avgRS"], "")

    def test_breadth_counts_above_trend_lines(self):
        s = sh.snapshot(review(2, 23, 5, 0.36, 0.64, 10))
        self.assertEqual(s["breadth200"], 25)   # 2 leaders + 23 reduce above 200d
        self.assertEqual(s["breadth50"], 2)     # only the 2 leaders above 50d

    def test_breadth_falls_back_to_tag_math_without_flags(self):
        ranking = ([{"tag": "LEADER", "composite": 90}] * 4
                   + [{"tag": "AVOID", "composite": 5}] * 6)
        s = sh.snapshot({"composite": {"signalsTrusted": True, "ranking": ranking}})
        self.assertEqual(s["breadth200"], 4)    # 10 - 6 avoid
        self.assertEqual(s["breadth50"], "")    # unknown without flags


class AppendTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = pathlib.Path(self._tmp.name) / "hist.csv"

    def tearDown(self):
        self._tmp.cleanup()

    def test_append_then_load_roundtrips(self):
        sh.append(sh.snapshot(review(7, 15, 8, 0.8, 0.2, 15, date="2026-07-06")), self.path)
        rows = sh.load(self.path)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["leaders"], "7")

    def test_same_date_replaces_not_duplicates(self):
        sh.append(sh.snapshot(review(7, 15, 8, 0.8, 0.2, 15, date="2026-07-06")), self.path)
        sh.append(sh.snapshot(review(2, 23, 5, 0.36, 0.64, 10, date="2026-07-06")), self.path)
        rows = sh.load(self.path)
        self.assertEqual(len(rows), 1)                 # replaced
        self.assertEqual(rows[0]["leaders"], "2")      # newest wins

    def test_rows_stay_date_sorted(self):
        sh.append(sh.snapshot(review(2, 23, 5, 0.36, 0.64, 10, date="2026-07-20")), self.path)
        sh.append(sh.snapshot(review(7, 15, 8, 0.80, 0.20, 15, date="2026-07-06")), self.path)
        dates = [r["date"] for r in sh.load(self.path)]
        self.assertEqual(dates, ["2026-07-06", "2026-07-20"])


class DeltaTests(unittest.TestCase):
    def test_no_delta_with_single_run(self):
        self.assertIsNone(sh.deltas([{"date": "d", "leaders": "2"}]))

    def test_delta_computes_week_over_week(self):
        hist = [
            {"date": "2026-07-06", "leaders": "7", "reduce": "15", "avoid": "8",
             "avgRS": "55", "investedPct": "80", "cashPct": "20",
             "namesBeatingSector": "15", "topBucketPct": "60"},
            {"date": "2026-07-20", "leaders": "2", "reduce": "23", "avoid": "5",
             "avgRS": "45", "investedPct": "36", "cashPct": "64",
             "namesBeatingSector": "10", "topBucketPct": "60"},
        ]
        d = sh.deltas(hist)
        self.assertEqual(d["changes"]["leaders"], -5)
        self.assertEqual(d["changes"]["cashPct"], 44)
        self.assertEqual(d["changes"]["namesBeatingSector"], -5)
        self.assertEqual(d["from"], "2026-07-06")

    def test_record_and_trend_end_to_end(self):
        with tempfile.TemporaryDirectory() as t:
            p = pathlib.Path(t) / "h.csv"
            sh.record_and_trend(review(7, 15, 8, 0.8, 0.2, 15, date="2026-07-06"), path=p)
            r = sh.record_and_trend(review(2, 23, 5, 0.36, 0.64, 10, date="2026-07-20"), path=p)
            self.assertEqual(r["historyLen"], 2)
            self.assertEqual(r["deltas"]["changes"]["leaders"], -5)


if __name__ == "__main__":
    unittest.main()
