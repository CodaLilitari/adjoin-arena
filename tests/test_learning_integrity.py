import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from bots import brain
from scripts.bot_development.train_matches import ingest_receipt, match_command


def duel(t, owner, applied, *, teacher=1, policy="teacher", life=1):
    return (f"BOT_DUEL name=Red t={t} seq={t} life={life} f=90,30,90,100,2,1,0,0,0 "
            f"teacher={teacher} selected={teacher} applied={applied} owner={owner} model={policy}\n")


def state(t, *, weapons=2, kills=0, life=1, dead=0):
    return (f"BOT_RED_STATE name=Red t={t} life={life} hp=90 shields=20 weapons={weapons:#x} "
            f"kills={kills} deaths=0 dead={dead}\n")


class LearningIntegrity(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name)
        self.store = brain.BrainStore(self.path / "store", "red")
        self.addCleanup(self.store.close)

    def test_override_blocks_credit_for_previous_and_current_actions(self):
        for override in ("stationary", "late-override", "force", "route-other", "unknown"):
            with self.subTest(owner=override):
                text = state(1) + duel(2, "supply", 1) + duel(3, override, 0) + state(4, weapons=10, kills=1)
                brain.ingest_match_log(self.store, text, "map", "ffa/guns/noforce")
                prior, stopped = self.store.decisions("pickup_engage")[-2:]
                self.assertEqual(prior["outcome"], {"owner": "supply"})
                self.assertEqual(stopped["outcome"], {"owner": override})
                self.assertIsNone(brain._taken_label(stopped))
                self.assertEqual(stopped["teacher"], 1)
        self.assertIsNone(brain._duel_owner_label("engage", 1))

    def test_weapon_gain_requires_own_life_and_applied_supply(self):
        text = (state(1) + duel(2, "supply", 1) + state(3, weapons=10)
                + duel(4, "engage", 0) + state(5, weapons=26)
                + duel(6, "supply", 1) + state(7, weapons=58, life=2)
                + duel(8, "supply", 1, life=2) + state(9, weapons=122, life=2, dead=1))
        brain.ingest_match_log(self.store, text, "map", "ffa/guns/noforce")
        outcomes = [r["outcome"] for r in self.store.decisions("pickup_engage")]
        self.assertEqual([o.get("acquired_weapon", 0) for o in outcomes], [1, 0, 0, 0])
        self.assertEqual(brain.reward_from_outcome(outcomes[0]), 1)

    def test_unassigned_and_reimported_logs_do_not_become_practice(self):
        raw = (state(1) + duel(2, "engage", 0)).replace("\n", "\r\n").encode()
        directory = self.path / "match"
        directory.mkdir()
        hashes = {}
        for name, data in (("dark.log", raw), ("light.log", raw.replace(b"Red", b"Light")),
                           ("server.log", b"server")):
            (directory / name).write_bytes(data)
            hashes[name] = hashlib.sha256(data).hexdigest()
        receipt = {"status": "live_join_and_loadout_verified", "log_sha256": hashes,
                   "sha256": {"jkl/test.jkl": "a"*64}, "pace_experiment": {"speed": 1,
                       "requested_game_seconds": 20, "roles": {
                           seat: {"first": {"game_ms": 0}} for seat in ("dark", "light")}},
                   "red_policy": {"build": {"binary_sha256": "b"*64}}}
        (directory / "receipt.json").write_text(json.dumps(receipt))
        ingest_receipt(self.store, directory, split="holdout")
        with self.assertRaisesRegex(ValueError, "metadata"):
            brain.main(["--root", str(self.store.root), "ingest-decisions", str(directory / "dark.log"),
                        "--map-sha", "a"*64, "--scope", "ffa/guns/force", "--pace", "1x", "--build", "b"*64])
        brain.ingest_duel_log(self.store, raw.decode(), "map", "scope")
        self.assertEqual(len(self.store.decisions(split="unassigned")), 1)
        self.assertEqual(self.store.decisions(split="practice"), [])
        self.store.append_decision("curated", {"x": 1}, teacher=1)
        self.assertEqual([r["kind"] for r in self.store.decisions(split="practice")], ["curated"])

    def test_shadow_qualification_excludes_model_seat_and_requires_reward_coverage(self):
        teacher = state(1) + duel(2, "engage", 0) + state(3, kills=1)
        learned = state(1) + duel(2, "supply", 1, policy="candidate") + state(3, weapons=10)
        for text in (teacher, learned):
            brain.ingest_match_log(self.store, text, "map", "scope", match_id="match", split="holdout")
        model = {"schema": 1, "kind": "decision", "features": ["health"],
                 "centers": [0], "scales": [1], "weights": [0], "bias": -1}
        verdict = brain.qualify_decision_candidate(self.store, "pickup_engage", model,
            min_rows=1, min_balanced_accuracy=0, min_rewarded=1, require_maps=1)
        self.assertEqual(verdict["metrics"]["excluded_policy_rows"], 1)
        self.assertEqual(verdict["metrics"]["rewarded_by_action"], [1, 0])
        self.assertFalse(verdict["ok"])
        self.assertTrue(any("reward coverage" in reason for reason in verdict["reasons"]))

    def test_previous_schema_rows_survive_without_an_assumed_split(self):
        old = brain.BrainStore(self.path / "old", "red")
        old.append_decision("historic", {"x": 1}, teacher=1)
        with old.db:
            old.db.execute("ALTER TABLE decisions DROP COLUMN curated")
        old.close()
        upgraded = brain.BrainStore(self.path / "old", "red")
        self.addCleanup(upgraded.close)
        self.assertEqual(upgraded.decisions(split="practice"), [])
        self.assertEqual(upgraded.decisions(split="holdout"), [])
        self.assertEqual(upgraded.decisions(split="unassigned")[0]["kind"], "historic")

    def test_competitive_client_selects_the_competitive_harness_option(self):
        args = SimpleNamespace(repo="repo", data="data", map="m1.jkl", duration=10,
            pace_build="pace", rate=1, client_kind="competitive", client_build="client",
            mode="ctf", weapons="guns", force="off", episode_file="episode", episode_sha256="a",
            map_sha256="b", brain_edge_model=None, model_side=None, swap_join_order=False, harness_extra=[])
        command = match_command(args, 1, self.path / "match")[-1]
        self.assertIn("'--competitive-build' 'client'", command)
        self.assertNotIn("'--transfer-build'", command)
        self.assertIn("'--mode' 'ctf'", command)
        args.model_side, args.policy_weights, args.weights_digest = "light", "weights", "c"
        command = match_command(args, 1, self.path / "match")[-1]
        self.assertIn("'--trial-scope' 'ctf/guns/noforce'", command)
        self.assertIn("'--trial-map-sha256' 'b'", command)
        self.assertIn("'--trial-weights-sha256' 'c'", command)
