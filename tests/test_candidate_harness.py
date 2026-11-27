"""Candidate-lane client kind: runner flags and pinned client resolution."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

from scripts.bot_development.legacy import native_red_match as red
from scripts.bot_development.train_matches import match_command

ROOT = Path(__file__).resolve().parents[1]


def file_digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fake_args(kind, out):
    return type("Args", (), {
        "repo": ROOT, "data": out, "map": "c3.jkl", "duration": 60,
        "pace_build": out, "rate": 0, "client_kind": kind, "client_build": out,
        "mode": "ctf", "weapons": "guns", "force": "on",
        "episode_file": out / "jk1ctf.gob", "episode_sha256": "e" * 64,
        "map_sha256": "m" * 64, "brain_edge_model": None,
        "model_side": None, "policy_weights": None, "weights_digest": "w" * 64,
        "swap_join_order": False, "harness_extra": [],
    })()


class MatchCommandTests(unittest.TestCase):
    def test_candidate_and_custom_flags(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            for kind, flag in (("candidate", "--candidate-build"), ("custom", "--custom-build"),
                               ("transfer", "--transfer-build"), ("competitive", "--competitive-build")):
                command = match_command(fake_args(kind, out), 0, out / "match-0000")
                joined = " ".join(command)
                self.assertIn(flag, joined)
                self.assertIn("--nav-cache", joined)
                self.assertIn("--mode", joined)

    def test_policy_flag_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            args = fake_args("policy", out)
            args.mode, args.weapons, args.force = "ffa", "guns", "on"
            joined = " ".join(match_command(args, 0, out / "match-0000"))
            self.assertIn("--red-policy-build", joined)
            self.assertNotIn("--candidate-build", joined)


class ResolveCandidateTests(unittest.TestCase):
    def test_candidate_requires_transfer_without_custom(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            pace = {"bot": {"gns_sha256": "0" * 64}}
            with self.assertRaises(ValueError):
                red.resolve_client(ROOT, out, pace, file_digest, transfer=False, candidate=True)
            with self.assertRaises(ValueError):
                red.resolve_client(ROOT, out, pace, file_digest, transfer=True, custom=True, candidate=True)

    @unittest.skipUnless(os.environ.get("ADJOIN_CANDIDATE_BUILD"),
                         "set ADJOIN_CANDIDATE_BUILD to a lane build output directory")
    def test_candidate_resolves_real_lane_build(self):
        build_dir = Path(os.environ["ADJOIN_CANDIDATE_BUILD"])
        receipt = json.loads((ROOT / "native/red-candidate-build.json").read_bytes())
        pace = {"bot": {"gns_sha256": receipt["gns_sha256"]}}
        client, build = red.resolve_client(ROOT, build_dir, pace, file_digest,
                                           transfer=True, candidate=True)
        self.assertEqual(client, build_dir / "jk-bot-client")
        self.assertEqual(build["binary_sha256"], receipt["binary_sha256"])


if __name__ == "__main__":
    unittest.main()
