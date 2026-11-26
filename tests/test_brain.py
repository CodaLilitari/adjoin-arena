"""Persistent BrainStore: decisions, edge stats, edge model, promotion gates."""
from __future__ import annotations

import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from bots import coach as coach_module
from bots.brain import (BrainStore, EDGE_FEATURES, export_edge_native,
                        fit_decision_model, fit_edge_model,
                        ingest_bot_decision_log, ingest_decision_log,
                        ingest_duel_log, ingest_match_log,
                        leave_one_map_out, leave_one_map_out_decisions,
                        load_decision_model, load_edge_model, parse_edge_native,
                        predict_decision, predict_edge, save_decision_model,
                        qualify_decision_candidate, reward_from_outcome,
                        export_red_neural, predict_red_neural,
                        save_edge_model, suggest_tactics,
                        train_decision_from_store, train_outcome_from_store)


class BrainStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "brain"

    def test_decisions_persist_across_reopen(self):
        store = BrainStore(self.root, "red")
        row = store.append_decision(
            "pickup_engage", {"health": 88, "enemy_mm": 465},
            teacher=1, selected=0, applied=1, candidates=[0, 1],
            outcome={"damage_dealt": 20}, map_sha="m" * 64, scope="ffa/guns/force")
        self.assertGreater(row, 0)
        store.close()
        reopened = BrainStore(self.root, "red")
        rows = reopened.decisions("pickup_engage")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["teacher"], 1)
        self.assertEqual(rows[0]["features"]["enemy_mm"], 465)
        self.assertEqual(rows[0]["outcome"], {"damage_dealt": 20})
        reopened.close()

    def test_edge_stats_accumulate_and_estimate(self):
        store = BrainStore(self.root, "red")
        for success, seconds in ((True, 2.0), (True, 4.0), (False, 9.0)):
            store.record_edge("a" * 64, "ffa/guns/force", "f1", "t1", 0,
                              success, seconds=seconds, damage=1.0,
                              features={"distance": 1.0})
        estimate = store.edge_estimate("a" * 64, "ffa/guns/force", "f1", "t1", 0)
        self.assertEqual((estimate["attempts"], estimate["successes"]), (3, 2))
        self.assertAlmostEqual(estimate["probability"], 3 / 5)
        self.assertAlmostEqual(estimate["mean_seconds"], 5.0)
        # An untried edge on the same map stays at the neutral prior.
        fresh = store.edge_estimate("a" * 64, "ffa/guns/force", "x", "y", 0)
        self.assertEqual(fresh["attempts"], 0)
        self.assertAlmostEqual(fresh["probability"], 0.5)
        store.close()

    def test_ingest_nav_log_and_v1_file(self):
        store = BrainStore(self.root, "red")
        log = ("BOT_NAV_LEARN name=Bot_Red t=1.0 event=stall from=0 to=1 "
               "from_key=aa to_key=bb edge=0 before=0 after=2 saved=1\n"
               "BOT_NAV_LEARN name=Bot_Red t=2.0 event=arrive from=0 to=1 "
               "from_key=aa to_key=bb edge=0 before=2 after=0 saved=1\n")
        self.assertEqual(store.ingest_nav_log(log, "b" * 64, "ffa/guns/noforce"), 2)
        nav = Path(self.tmp.name) / "x.nav"
        nav.write_text("cc dd 3 2 1700000000\n", encoding="ascii")
        self.assertEqual(store.ingest_nav_file(nav, "b" * 64, "ffa/guns/noforce"), 1)
        estimate = store.edge_estimate("b" * 64, "ffa/guns/noforce", "cc", "dd", 3)
        self.assertEqual((estimate["attempts"], estimate["failures"]), (2, 2))
        store.close()

    def test_ingest_duel_log_into_ledger(self):
        store = BrainStore(self.root, "red")
        log = ("BOT_DUEL name=Bot_Red t=1.0 seq=1 life=1 target=3 item=4 "
               "f=88,78,465,3383,5,76,0,0,7 teacher=1 selected=0 applied=1 "
               "owner=engage model=teacher forward=-1.0 slide=0.5 fire1=1 fire2=0\n")
        self.assertEqual(ingest_duel_log(store, log, "d" * 64, "ffa/guns/force"), 1)
        rows = store.decisions("pickup_engage")
        self.assertEqual(rows[0]["features"]["enemy_mm"], 465)
        self.assertEqual((rows[0]["teacher"], rows[0]["selected"]), (1, 0))
        store.close()

    def test_ingest_existing_decision_telemetry(self):
        store = BrainStore(self.root, "red")
        log = ("BOT_GEAR name=Bot_Red t=1.0 event=plan item=29 guid=7 signature=9 "
               "pack=0 anchor=12 direct=1\n"
               "BOT_SWITCH name=Bot_Red from=2 to=9 dist=3.50 los=1 air=0 why=unsafe\n"
               "BOT_FORCE_INPUT name=Bot_Red bin=31 level=4 mana=120.0 hold=0.46\n")
        counts = ingest_decision_log(store, log, "e" * 64, "ffa/guns/force",
                                     pace="2x", build="pace-build-x")
        self.assertEqual(counts, {"goal_plan": 1, "weapon_switch": 1, "force_cast": 1})
        goal = store.decisions("goal_plan")[0]
        self.assertEqual(goal["outcome"]["choice_item"], 29)
        self.assertEqual(goal["pace"], "2x")
        weapon = store.decisions("weapon_switch")[0]
        self.assertEqual(weapon["outcome"], {"choice_weapon": 9, "why": "unsafe"})
        force = store.decisions("force_cast")[0]
        self.assertEqual((force["selected"], force["features"]["bin"]), (1, 31))
        store.close()

    def test_ingest_bot_decision_telemetry(self):
        store = BrainStore(self.root, "red")
        log = (
            "BOT_DECISION name=Bot_Red t=3.000 seq=1 kind=goal choice=12 item=29 "
            "graph_dist_milli=2500 health_milli=80000 shields_milli=50000 "
            "mana_milli=100000 weapon=9 target=-1 objective=0\n"
            "BOT_DECISION name=Bot_Red t=3.100 seq=2 kind=weapon choice=9 from=2 "
            "score_milli=88000 dist_milli=3500 los=1 air=0 health_milli=80000 "
            "shields_milli=50000 mana_milli=90000 target=1 why=score\n"
            "BOT_DECISION name=Bot_Red t=3.200 seq=3 kind=force choice=31 "
            "level_milli=4000 mana_milli=90000 hold_milli=460 health_milli=80000 "
            "shields_milli=50000 target=1 weapon=9\n")
        self.assertEqual(
            ingest_bot_decision_log(store, log, "f" * 64, "ffa/guns/force", pace="2x"), 3)
        self.assertEqual(store.decisions("goal")[0]["outcome"], {"choice": 12})
        self.assertEqual(store.decisions("weapon")[0]["outcome"],
                         {"choice": 9, "why": "score"})
        force = store.decisions("force")[0]
        self.assertEqual(force["features"]["hold_milli"], 460)
        self.assertEqual(force["pace"], "2x")
        store.close()

    def test_match_log_attributes_outcomes(self):
        store = BrainStore(self.root, "red")
        log = (
            "BOT_STATUS name=Bot_Red t=1.0 sector=2 pos=0,0,0 health=100.0 weapon=9 "
            "target=1 goal=3 path=1/4 kills=0 deaths=0 vz=0\n"
            "BOT_DECISION name=Bot_Red t=2.000 seq=1 kind=weapon choice=9 from=2 "
            "score_milli=88000 dist_milli=3500 los=1 air=0 health_milli=100000 "
            "shields_milli=0 mana_milli=0 target=1 why=score\n"
            "BOT_STATUS name=Bot_Red t=4.0 sector=2 pos=0,0,0 health=80.0 weapon=9 "
            "target=1 goal=3 path=2/4 kills=1 deaths=0 vz=0\n"
            "BOT_DECISION name=Bot_Red t=20.000 seq=2 kind=goal choice=5 item=29 "
            "graph_dist_milli=1000 health_milli=80000 shields_milli=0 mana_milli=0 "
            "weapon=9 target=-1 objective=0\n"
            "BOT_STATUS name=Bot_Red t=30.0 sector=2 pos=0,0,0 health=80.0 weapon=9 "
            "target=-1 goal=5 path=0/1 kills=1 deaths=0 vz=0\n"
            "BOT_EDGE_ATTEMPT name=Bot_Red t=21.0 event=arrive from_key=aa to_key=bb "
            "edge=0 dist_mm=1000 dz_mm=0 from_water=0 to_water=0 dest_item=1 "
            "base_cost_milli=1000 degree_from=2 degree_to=2\n")
        counts = ingest_match_log(store, log, "a" * 64, "ffa/guns/force", pace="2x")
        self.assertEqual(counts["bot_decision"], 2)
        self.assertEqual(counts["attributed"], 1)
        self.assertEqual(counts["edges"], 1)
        weapon = store.decisions("weapon")[0]
        self.assertEqual(weapon["outcome"]["kill"], 1)
        self.assertEqual(weapon["outcome"]["damage_taken"], 20.0)
        goal = store.decisions("goal")[0]
        self.assertNotIn("kill", goal["outcome"])
        store.close()

    def test_match_log_attributes_from_red_state(self):
        store = BrainStore(self.root, "red")
        log = (
            "BOT_RED_STATE name=Bot_Red t=1.000 life=1 game_ms=1000 hp=100 "
            "shields=100 kills=0 deaths=0 dead=0\n"
            "BOT_DECISION name=Bot_Red t=1.5 seq=1 kind=weapon choice=9 from=2 "
            "score_milli=88000 dist_milli=3500 los=1 air=0 health_milli=100000 "
            "shields_milli=100000 mana_milli=90000 target=1 why=score\n"
            "BOT_RED_STATE name=Bot_Red t=3.0 life=1 game_ms=3000 hp=92 "
            "shields=81 kills=1 deaths=0 dead=0\n")
        counts = ingest_match_log(store, log, "a" * 64, "ffa/guns/force")
        self.assertEqual(counts["attributed"], 1)
        outcome = store.decisions("weapon")[0]["outcome"]
        self.assertEqual(outcome["kill"], 1)
        self.assertEqual(outcome["damage_taken"], 8.0)
        store.close()

    def test_ingest_edge_attempt_telemetry(self):
        store = BrainStore(self.root, "red")
        log = ("BOT_EDGE_ATTEMPT name=Bot_Red t=3.0 event=arrive from_key=aa "
               "to_key=bb edge=0 dist_mm=1500 dz_mm=-250 from_water=0 to_water=1 "
               "dest_item=1 base_cost_milli=2500 degree_from=3 degree_to=2\n")
        self.assertEqual(store.ingest_edge_log(log, "c" * 64, "ffa/guns/force"), 1)
        rows = store.edge_rows()
        self.assertEqual(rows[0]["features"]["distance"], 1.5)
        self.assertEqual(rows[0]["features"]["dz"], -0.25)
        self.assertEqual(rows[0]["successes"], 1)
        store.close()

    def test_pace_provenance_separates_evidence(self):
        store = BrainStore(self.root, "red")
        store.record_edge("a" * 64, "ffa/guns/force", "f1", "t1", 0, True, pace="1x")
        store.record_edge("a" * 64, "ffa/guns/force", "f1", "t1", 0, False, pace="2x")
        self.assertEqual(store.edge_estimate(
            "a" * 64, "ffa/guns/force", "f1", "t1", 0, pace="1x")["successes"], 1)
        self.assertEqual(store.edge_estimate(
            "a" * 64, "ffa/guns/force", "f1", "t1", 0, pace="2x")["failures"], 1)
        store.append_decision("pickup_engage", {"health": 90}, teacher=1,
                              pace="replay-uncapped", build="pace-build-abc")
        row = store.decisions("pickup_engage")[0]
        self.assertEqual((row["pace"], row["build"]), ("replay-uncapped", "pace-build-abc"))
        self.assertEqual({r["pace"] for r in store.edge_rows()}, {"1x", "2x"})
        store.close()

    def test_coach_memory_roundtrip_both_formats(self):
        store = BrainStore(self.root, "red")
        stored = {
            "native": {"build": "sha256:abc", "arms": {
                "duel": {"plays": 3, "total": 1.5}, "bad": {"plays": -1, "total": 0}}},
            "legacy": {"roam": {"plays": 2, "total": -1.0}},
        }
        self.assertEqual(store.import_coach_memory(stored), 2)
        store.record_coach("native", "sha256:abc", "duel", 0.5)
        self.assertEqual(store.coach_arms("native", "sha256:abc"),
                         {"duel": {"plays": 4, "total": 2.0}})
        exported = store.export_coach_memory()
        self.assertEqual(exported["native"]["arms"]["duel"], {"plays": 4, "total": 2.0})
        self.assertEqual(exported["legacy"]["build"], "unrecorded")
        store.close()

    def test_coach_helpers_use_brainstore_backend(self):
        store = BrainStore(self.root, "coach")
        record = {"duel": {"plays": 2, "total": 1.25}}
        coach_module.save_brain_memory(store, "oasis", record, "build-a")
        self.assertEqual(coach_module.load_brain_memory(store, "oasis", "build-a"), record)
        self.assertEqual(coach_module.load_brain_memory(store, "oasis", "build-b"), {})
        resumed = coach_module.Bandit(
            ["duel"], record=coach_module.load_brain_memory(store, "oasis", "build-a"))
        self.assertEqual(resumed.export(), record)
        store.close()

    def test_qualify_candidate_gates(self):
        store = BrainStore(self.root, "red")
        for map_sha in ("a" * 64, "b" * 64):
            for _ in range(20):
                store.append_decision("engage", {"distance": 1.0}, teacher=1,
                                      outcome={"kill": 1}, map_sha=map_sha)
                store.append_decision("engage", {"distance": 5.0}, teacher=0,
                                      outcome={"death": 1}, map_sha=map_sha)
        good = train_decision_from_store(store, "engage", ["distance"])
        verdict = qualify_decision_candidate(store, "engage", good, min_rows=10)
        self.assertTrue(verdict["ok"], verdict["reasons"])
        bad = dict(good)
        bad["weights"] = [-w for w in good["weights"]]
        bad["bias"] = -good["bias"]
        refused = qualify_decision_candidate(store, "engage", bad, min_rows=10)
        self.assertFalse(refused["ok"])
        self.assertTrue(any("balanced accuracy" in r for r in refused["reasons"]))
        store.close()

    def test_promotion_requires_gates_and_rolls_back(self):
        store = BrainStore(self.root, "red")
        first = Path(self.tmp.name) / "m1.weights"
        first.write_bytes(b"weights-one")
        second = Path(self.tmp.name) / "m2.weights"
        second.write_bytes(b"weights-two")
        sha1 = store.register_model(first, "pickup_engage", "ffa/guns/force|map1")
        sha2 = store.register_model(second, "pickup_engage", "ffa/guns/force|map1")
        self.assertEqual(sha1, hashlib.sha256(b"weights-one").hexdigest())
        with self.assertRaises(ValueError):
            store.promote_model(sha1, safety_ok=True, heldout_ok=False)
        store.promote_model(sha1, safety_ok=True, heldout_ok=True)
        store.promote_model(sha2, safety_ok=True, heldout_ok=True)
        self.assertEqual(store.active_model("pickup_engage", "ffa/guns/force|map1")["sha256"], sha2)
        self.assertEqual(store.rollback("pickup_engage", "ffa/guns/force|map1"), sha1)
        self.assertEqual(store.active_model("pickup_engage", "ffa/guns/force|map1")["sha256"], sha1)
        store.close()
        reopened = BrainStore(self.root, "red")
        self.assertEqual(reopened.active_model("pickup_engage", "ffa/guns/force|map1")["sha256"], sha1)
        reopened.close()


class EdgeModelTests(unittest.TestCase):
    def rows(self):
        rows = []
        for i in range(30):
            walk = {"distance": 0.5 + i * 0.01, "mode": 0}
            jump = {"distance": 2.0, "mode": 5, "dz": 1.5}
            rows.append((walk, 19, 1))
            rows.append((jump, 1, 19))
        return rows

    def test_global_edge_model_separates_modes_and_roundtrips(self):
        model = fit_edge_model(self.rows())
        self.assertEqual(tuple(model["features"]), EDGE_FEATURES)
        self.assertGreater(model["train"]["balanced_accuracy"], 0.9)
        self.assertGreater(predict_edge(model, {"distance": 0.6, "mode": 0}), 0.8)
        self.assertLess(predict_edge(model, {"distance": 2.0, "mode": 5, "dz": 1.5}), 0.2)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "edge.json"
            digest = save_edge_model(model, path)
            loaded = load_edge_model(path, digest)
            self.assertEqual(loaded["weights"], model["weights"])
            with self.assertRaises(ValueError):
                load_edge_model(path, "0" * 64)

    def test_native_export_parity(self):
        model = fit_edge_model(self.rows())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "edge.txt"
            digest = export_edge_native(model, path)
            self.assertEqual(digest, hashlib.sha256(path.read_bytes()).hexdigest())
            parsed = parse_edge_native(path.read_text(encoding="ascii"))
            for key in ("centers", "scales", "weights"):
                for got, want in zip(parsed[key], model[key]):
                    self.assertAlmostEqual(got, want, places=6)
            self.assertAlmostEqual(
                predict_edge(parsed, {"distance": 0.6, "mode": 0}),
                predict_edge(model, {"distance": 0.6, "mode": 0}), places=6)

    def test_leave_one_map_out_reports_per_map(self):
        rows = []
        for map_sha in ("a" * 64, "b" * 64, "c" * 64):
            for features, ok, bad in self.rows():
                rows.append({"map_sha": map_sha, "features": features,
                             "successes": ok, "failures": bad})
        report = leave_one_map_out(rows)
        self.assertEqual(set(report), {"a" * 64, "b" * 64, "c" * 64})
        for entry in report.values():
            self.assertGreater(entry["balanced_accuracy"], 0.85)
            self.assertEqual(entry["train_maps"], 2)

    def test_decision_distillation_and_map_holdout(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = BrainStore(Path(tmp.name) / "brain", "red")
        for map_sha in ("a" * 64, "b" * 64, "c" * 64):
            for i in range(20):
                store.append_decision(
                    "weapon_choice", {"distance": 0.5 + i * 0.05, "ammo": 10},
                    teacher=1, map_sha=map_sha)
                store.append_decision(
                    "weapon_choice", {"distance": 4.0 + i * 0.05, "ammo": 10},
                    teacher=0, map_sha=map_sha)
        model = train_decision_from_store(store, "weapon_choice",
                                          ["distance", "ammo"])
        self.assertGreater(model["train"]["balanced_accuracy"], 0.9)
        self.assertGreater(predict_decision(model, {"distance": 0.7}), 0.8)
        self.assertLess(predict_decision(model, {"distance": 4.2}), 0.2)
        report = leave_one_map_out_decisions(
            store.decisions("weapon_choice"), ["distance", "ammo"])
        self.assertEqual(len(report), 3)
        for entry in report.values():
            self.assertGreater(entry["balanced_accuracy"], 0.85)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "decision.json"
            digest = save_decision_model(model, path)
            self.assertEqual(load_decision_model(path, digest)["weights"],
                             model["weights"])
        store.close()

    def test_outcome_weighting_reverses_bad_teacher_region(self):
        self.assertEqual(reward_from_outcome({"kill": 1, "damage_taken": 50}), 2.0)
        self.assertIsNone(reward_from_outcome({"why": "score"}))
        self.assertIsNone(reward_from_outcome(None))
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = BrainStore(Path(tmp.name) / "brain", "red")
        # Near: action 1 dies, action 0 kills. Far: the reverse. Imitation
        # sees balanced labels; outcome weighting must split by distance.
        for _ in range(20):
            store.append_decision("engage", {"distance": 1.0}, teacher=1,
                                  outcome={"death": 1})
            store.append_decision("engage", {"distance": 1.0}, teacher=0,
                                  outcome={"kill": 1})
            store.append_decision("engage", {"distance": 5.0}, teacher=1,
                                  outcome={"kill": 1})
            store.append_decision("engage", {"distance": 5.0}, teacher=0,
                                  outcome={"death": 1})
        model = train_outcome_from_store(store, "engage", ["distance"])
        self.assertTrue(model["train"]["outcome_weighted"])
        self.assertLess(predict_decision(model, {"distance": 1.0}), 0.35)
        self.assertGreater(predict_decision(model, {"distance": 5.0}), 0.65)
        store.close()

    def test_red_neural_export_matches_logistic(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = BrainStore(Path(tmp.name) / "brain", "red")
        for i in range(30):
            store.append_decision("pickup_engage",
                                  {"health": 100, "enemy_mm": 9000, "item_mm": 500 + i},
                                  teacher=1)
            store.append_decision("pickup_engage",
                                  {"health": 40, "enemy_mm": 400, "item_mm": 5000 - i},
                                  teacher=0)
        model = train_decision_from_store(store, "pickup_engage", list(
            __import__("bots.brain", fromlist=["DUEL_FEATURES"]).DUEL_FEATURES))
        path = Path(tmp.name) / "pickup.weights"
        digest = export_red_neural(model, path)
        self.assertEqual(digest, hashlib.sha256(path.read_bytes()).hexdigest())
        text = path.read_text(encoding="ascii")
        self.assertTrue(text.startswith("RED_NEURAL_V1 9 8\n"))
        agree = total = 0
        for row in store.decisions("pickup_engage"):
            total += 1
            native = predict_red_neural(text, row["features"])
            brain = int(predict_decision(model, row["features"]) >= 0.5)
            agree += native == brain
        self.assertGreaterEqual(agree / total, 0.97)
        store.close()

    def test_suggest_tactics_moves_toward_reward(self):
        trials = []
        for conc in (8.0, 14.0, 20.0, 26.0, 32.0, 38.0):
            for travel in (0.2, 0.42, 0.7):
                reward = -((conc - 26.0) ** 2) / 100.0 - ((travel - 0.3) ** 2) * 10.0
                trials.append(({"value_conc": conc, "travel_cost": travel}, reward))
        suggestion = suggest_tactics(trials)
        self.assertGreater(suggestion["value_conc"], 18.0)
        self.assertLessEqual(suggestion["value_conc"], 30.0)
        self.assertLess(suggestion["travel_cost"], 0.42)
        with self.assertRaises(ValueError):
            suggest_tactics(trials[:2])

    def test_fit_rejects_bad_rows(self):
        with self.assertRaises(ValueError):
            fit_edge_model([])
        with self.assertRaises(ValueError):
            fit_edge_model([({"distance": float("nan")}, 1, 1)])
        with self.assertRaises(ValueError):
            fit_edge_model([({"unknown_feature": 1.0}, 1, 1)])

    def test_torch_backend_matches_numpy(self):
        try:
            import torch  # noqa: F401
        except ImportError:
            self.skipTest("torch not installed")
        with mock.patch.dict(os.environ, {"BRAIN_FIT_BACKEND": "numpy"}):
            expected = fit_edge_model(self.rows())
        with mock.patch.dict(os.environ, {"BRAIN_FIT_BACKEND": "torch:cpu"}):
            actual = fit_edge_model(self.rows())
        for key in ("centers", "scales", "weights"):
            for want, got in zip(expected[key], actual[key]):
                self.assertAlmostEqual(want, got, delta=1e-9)
        self.assertAlmostEqual(expected["bias"], actual["bias"], delta=1e-9)
        self.assertAlmostEqual(expected["train"]["balanced_accuracy"],
                               actual["train"]["balanced_accuracy"], delta=1e-9)

    def test_unknown_fit_backend_rejected(self):
        with mock.patch.dict(os.environ, {"BRAIN_FIT_BACKEND": "bogus"}):
            with self.assertRaises(ValueError):
                fit_edge_model(self.rows())


if __name__ == "__main__":
    unittest.main()
