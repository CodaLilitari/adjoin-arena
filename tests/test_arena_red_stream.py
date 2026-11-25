import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts.bot_development.analysis import red_policy_stream as stream
from scripts.bot_development.analysis import red_tactical_policy as policy


class StreamTests(unittest.TestCase):
    def test_held_out_names_and_traversal_are_rejected(self):
        with self.assertRaises(ValueError):
            stream.training_cells({"training": [{"name":"test-a"}], "test": [{"name":"test-a"}]}, False)
        with self.assertRaises(ValueError):
            stream.training_cells({"training": [{"name":"../unrelated"}]}, False)

    def test_challenger_is_scored_before_new_examples_enter_fit(self):
        class Candidate:
            def predict(self, x):
                return x[0]

        def row(i, y):
            return policy.Decision("dark", 1, i, float(i), i, i, (y,), y, y, y,
                                   "engage" if not y else "supply", "teacher", False, True)

        prior = {"matches": [{"candidate":"A","practice":None,"majority":1}]}
        with patch.object(stream, "load_weights", return_value=Candidate()):
            rare = stream.check_challenger(Path("."), prior, [row(1, 0), row(2, 1)])
            enough = stream.check_challenger(Path("."), prior, [row(i, i % 2) for i in range(4)])
        self.assertIsNone(rare["practice"])
        self.assertEqual(enough["practice"], "A")
        self.assertEqual(enough["trial"]["balanced_accuracy"], 1)
        self.assertEqual(enough["reference"]["balanced_accuracy"], .5)

    def test_resume_detects_replaced_receipt_and_waits_for_complete_match(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = root / "state"
            design = root / "schedule.json"
            design.write_text(json.dumps({"training":[{"name":"one","map":"m10.jkl"},{"name":"two","map":"m2.jkl"}]}))
            self.assertFalse(stream.sync(root, design, state)["matches"])
            (root/"one").mkdir()
            evidence = {"kind":"adjoin-arena-stock-red-policy","status":"live_join_and_loadout_verified",
                        "requested_map":"m10.jkl", "log_sha256":{"dark.log":"d","light.log":"l"},
                        "red_policy":{"build":{"binary_sha256":"build", "red_commit":"f453778a3cf670dea43c44315786ae4afc8ae440"},
                                      "elite":True,"model_side":None,"start_and_outcomes":{}}}
            receipt = root/"one/receipt.json"
            receipt.write_text(json.dumps(evidence))
            with patch.object(policy,"read_match",return_value=([], {"dark":"d","light":"l"})):
                done = stream.sync(root, design, state)
                self.assertEqual([x["name"] for x in done["matches"]], ["one"])
                self.assertEqual(stream.sync(root, design, state), done)
                receipt.write_text(json.dumps(evidence) + "\n")
                with self.assertRaisesRegex(ValueError, "changed"):
                    stream.sync(root, design, state)
