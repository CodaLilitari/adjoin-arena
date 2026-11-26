"""Protect the shipped engine pins and reproduce candidate staging when source is available."""
import json
import os
from pathlib import Path
import tempfile
import unittest

from scripts.bot_development import stage_navigation_candidate as candidate


class NavigationCandidateTest(unittest.TestCase):
    def setUp(self):
        self.receipt = json.loads((candidate.ROOT / "qa/navigation-candidate-source.json").read_text())

    def test_packaged_and_candidate_inputs_match_receipts(self):
        for target, row in self.receipt.items():
            with self.subTest(target=target):
                manifest, sources = candidate.packaged(target)
                self.assertEqual(candidate.sha(manifest), row["packaged_manifest_sha256"])
                self.assertEqual(sources, row["input_files"])
                actual = [{"operation": op, "path": f"{target}/{name}",
                           "sha256": candidate.sha(candidate.ROOT / target / name)} for op, name in candidate.STEPS]
                self.assertEqual(actual, row["steps"])

    def test_landing_overlay_keeps_previous_candidate_reproducible(self):
        landing = json.loads((candidate.ROOT / "qa/navigation-landing-source.json").read_bytes())
        for target, row in self.receipt.items():
            with self.subTest(target=target):
                newer = landing[target]
                self.assertEqual(row["steps"], newer["steps"][:-1])
                step = newer["steps"][-1]
                self.assertEqual(step["path"], target + "/candidate/jhs-landing.patch")
                self.assertEqual(step["sha256"], candidate.sha(candidate.ROOT / step["path"]))
                self.assertEqual([k for k in row["output_files"] if
                                  row["output_files"][k] != newer["output_files"][k]], [candidate.HINT])

    def test_rejects_changed_source_before_creating_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "engine"
            (source / "src/AI").mkdir(parents=True)
            (source / candidate.BASE_FILES[0]).write_text("different")
            output = root / "candidate"
            with self.assertRaisesRegex(ValueError, "assembled packaged engine"):
                candidate.stage("native", source, output)
            self.assertFalse(output.exists())

    def test_stage_available_packaged_sources(self):
        found = False
        for target, row in self.receipt.items():
            source = os.environ.get("ADJOIN_PACKAGED_" + target.upper() + "_SOURCE")
            if source:
                found = True
                with self.subTest(target=target), tempfile.TemporaryDirectory() as tmp:
                    out = Path(tmp) / "candidate"
                    record = candidate.stage(target, Path(source), out, os.environ.get("PATCH", "patch"))
                    self.assertEqual(record, row)
                    self.assertEqual(json.loads((out / "manifest.json").read_text()), row)
                    newer = candidate.stage(target, Path(source), Path(tmp) / "landing",
                                            os.environ.get("PATCH", "patch"), jhs_landing=True)
                    expected = json.loads((candidate.ROOT / "qa/navigation-landing-source.json").read_bytes())
                    self.assertEqual(newer, expected[target])
                    step = candidate.stage(target, Path(source), Path(tmp) / "step",
                                           os.environ.get("PATCH", "patch"), jhs_landing_step=True)
                    expected = json.loads((candidate.ROOT / "qa/navigation-landing-step-source.json").read_bytes())
                    self.assertEqual(step, expected[target])
        if not found:
            self.skipTest("set ADJOIN_PACKAGED_NATIVE_SOURCE or ADJOIN_PACKAGED_WEB_BOTS_SOURCE")
