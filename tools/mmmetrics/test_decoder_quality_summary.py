"""Check that uncertainty is paired over assets and failures remain in counts."""

import unittest

from summarize_decoder_quality import KEYS, paired_interval, summarize


class SummaryTest(unittest.TestCase):
    def test_asset_pairing_and_failure_accounting(self):
        rows = []
        for index, delta in enumerate((-1., 1.)):
            before = {key: 2. for key in KEYS}
            after = {key: 2.+delta for key in KEYS}
            rows.append({"split": "validation", "file_id": index, "preparation_status": "prepared",
                         "variants": {"base": {"triangles": 10, "mean": before},
                                      "fixed": {"triangles": 10, "mean": after}},
                         "decode_status": {"fixed": "decoded", "refine": "local flip"}})
        rows.append({"split": "validation", "file_id": 2,
                     "preparation_status": "rejected", "reason": "bad topology"})
        summary = summarize({"scope": "test", "records": rows})["splits"]["validation"]
        self.assertEqual(summary["attempted_assets"], 3)
        self.assertEqual(len(summary["preparation_failures"]), 1)
        self.assertEqual(len(summary["decode_failures"]), 2)
        metric = summary["comparisons"]["fixed_vs_base"]["metrics"]["flip"]["paired_delta"]
        self.assertEqual(metric["assets"], 2)
        self.assertEqual(metric["mean_delta"], 0.)
        self.assertEqual(metric["bootstrap_95_percent"], [-1., 1.])

    def test_empty_and_constant_intervals(self):
        self.assertIsNone(paired_interval([]))
        self.assertEqual(paired_interval([.5, .5])["bootstrap_95_percent"], [.5, .5])


if __name__ == "__main__":
    unittest.main()
