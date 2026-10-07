import json
import unittest

from azurai.data import json_metadata


class MetadataTests(unittest.TestCase):
    def test_nonfinite_scheduler_values_become_valid_json_without_losing_other_data(self):
        original = {"scheduler": {"lambda_min_clipped": float("-inf")},
                    "values": [float("inf"), float("nan"), 7.5], "seed": 42}
        normalized = json_metadata(original)
        encoded = json.dumps(normalized, allow_nan=False)
        restored = json.loads(encoded)
        self.assertEqual(restored["scheduler"]["lambda_min_clipped"], "-Infinity")
        self.assertEqual(restored["values"], ["Infinity", "NaN", 7.5])
        self.assertEqual(restored["seed"], 42)
        self.assertIsInstance(original["scheduler"]["lambda_min_clipped"], float)
