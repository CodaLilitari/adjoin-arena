"""Persistent BrainStore: decisions, edge stats, edge model, promotion gates."""
from __future__ import annotations
import json

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
    def test_training_reads_new_evidence_after_100000_rows(self):
        store = BrainStore(self.root, "red")
        self.addCleanup(store.close)
        store.db.execute("""
            WITH RECURSIVE seq(i) AS (SELECT 1 UNION ALL SELECT i+1 FROM seq WHERE i < 100000)
            INSERT INTO decisions(ts,kind,map_sha,scope,policy_hash,features,teacher)
            SELECT i,'pickup','map','ffa/guns','', '{"near":0}',0 FROM seq
        """)
        store.append_decision("pickup", {"near": 1}, teacher=1, map_sha="map", scope="ffa/guns")
        rows = store.decisions("pickup")
        self.assertEqual(len(rows), 100001)
        self.assertEqual(rows[-1]["teacher"], 1)

    def test_training_refuses_to_pool_rules_or_speed_implicitly(self):
        store = BrainStore(self.root, "red")
        self.addCleanup(store.close)
        for scope, pace in (("ffa/guns", "1x"), ("ctf/guns", "max")):
            for label in (0, 1):
                store.append_decision("pickup", {"near": label}, teacher=label,
                                      scope=scope, pace=pace, build="test")
        with self.assertRaisesRegex(ValueError, "cohort"):
            train_decision_from_store(store, "pickup", ["near"])
        model = train_decision_from_store(store, "pickup", ["near"],
                                          scope="ffa/guns", pace="1x", build="test")
        self.assertEqual(model["train"]["rows"], 2)

    def test_reimport_is_atomic_and_a_match_cannot_change_partitions(self):
        store = BrainStore(self.root, "red")
        self.addCleanup(store.close)
        log = ("BOT_DECISION name=Red t=1.0 seq=1 kind=weapon choice=2 from=1\n"
               "BOT_EDGE_ATTEMPT name=Red t=1 event=arrive from_key=aa to_key=bb "
               "edge=0 dist_mm=1000 dz_mm=0 from_water=0 to_water=0 dest_item=1 "
               "base_cost_milli=1000 degree_from=2 degree_to=2\n")
        args = (store, log, "m", "ffa")
        ingest_match_log(*args, match_id="first")
        ingest_match_log(*args, match_id="first")
        self.assertEqual(len(store.decisions("weapon")), 1)
        self.assertEqual(store.edge_rows()[0]["attempts"], 1)
        with self.assertRaisesRegex(ValueError, "metadata"):
            ingest_match_log(*args, match_id="first", split="holdout")
        with self.assertRaisesRegex(ValueError, "metadata"):
            ingest_match_log(store, log.replace("Red", "Jan"), "m", "ffa",
                             match_id="first", split="holdout")

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

    def test_integer_candidate_requires_the_engine_dimensions(self):
        from bots.brain import DUEL_FEATURES
        malformed = "RED_NEURAL_V1 9 8\n" + "1\n" * 11
        with self.assertRaises(ValueError):
            predict_red_neural(malformed, {k: 1 for k in DUEL_FEATURES})

    def test_experimental_controls_keep_a_separate_training_cohort(self):
        from scripts.bot_development.train_matches import evidence_build
        binary = "a" * 64
        controls = dict(saber_tracking="both", light_loadout="competitive", force_controller="competitive")
        self.assertEqual(evidence_build(binary, controls), binary)
        self.assertNotEqual(evidence_build(binary, dict(controls, light_loadout="master")), binary)
        self.assertNotEqual(evidence_build(binary, dict(controls, saber_tracking="dark")),
                            evidence_build(binary, dict(controls, saber_tracking="light")))

    def test_verified_native_receipt_groups_seats_and_checks_bytes(self):
        from scripts.bot_development.train_matches import ingest_receipt
        import hashlib
        store = BrainStore(self.root, "red")
        self.addCleanup(store.close)
        directory = self.root / "match"
        directory.mkdir()
        logs = {}
        for side in ("dark", "light", "server"):
            raw = f"BOT_DECISION name={side} t=2.0 seq=1 kind=weapon choice=9\n".encode()
            (directory / (side + ".log")).write_bytes(raw)
            logs[side + ".log"] = hashlib.sha256(raw).hexdigest()
        receipt = {"status": "live_join_and_loadout_verified", "log_sha256": logs,
                   "sha256": {"jkl/m2.jkl": "b"*64}, "pace_experiment": {"speed": 1, "requested_game_seconds": 5,
                   "roles": {s: {"first": {"game_ms": 0}} for s in ("dark", "light")}},
                   "red_policy": {"build": {"binary_sha256": "a"*64}},
                   "mode_transfer": {"mode": "ffa", "weapons": "guns", "force": "off"}}
        (directory / "receipt.json").write_text(json.dumps(receipt))
        imported = ingest_receipt(store, directory, split="holdout")
        rows = store.decisions("weapon", split="holdout")
        self.assertEqual(len(rows), 2)
        self.assertEqual({r["match_id"] for r in rows}, {imported["match_id"]})
        self.assertEqual(rows[0]["build"], "a"*64)
        self.assertEqual(rows[0]["scope"], "ffa/guns/noforce")
        with self.assertRaisesRegex(ValueError, "metadata"):
            ingest_receipt(store, directory, split="practice")
        (directory / "light.log").write_text("wrong")
        with self.assertRaisesRegex(ValueError, "digest"):
            ingest_receipt(store, directory, split="holdout")

    def test_holdout_uses_only_the_recorded_game_window_but_keeps_the_original_log_identity(self):
        store = BrainStore(self.root, "red")
        self.addCleanup(store.close)
        log = "".join(f"BOT_DECISION name=Red t={t} seq=1 kind=weapon choice={t}\n"
                      for t in (1, 2, 3, 4))
        ingest_match_log(store, log, "map", "ffa", match_id="shared", split="holdout", game_window=(2000, 4000))
        self.assertEqual([r["outcome"]["choice"] for r in store.decisions("weapon")], [2, 3])
        with self.assertRaisesRegex(ValueError, "metadata"):
            ingest_match_log(store, log, "map", "ffa", match_id="shared", split="holdout")
        with self.assertRaisesRegex(ValueError, "metadata"):
            ingest_match_log(store, log, "map", "ffa")

    def test_one_frag_cannot_reward_every_decision_in_the_window(self):
        store = BrainStore(self.root, "red")
        self.addCleanup(store.close)
        log = ("BOT_RED_STATE name=Red t=1 life=1 hp=100 shields=30 kills=0 deaths=0 dead=0\n"
               "BOT_DUEL name=Red t=2 seq=1 life=1 f=100,30,50,30,2,1,0,0,0 teacher=1 selected=1 applied=1 owner=supply model=teacher\n"
               "BOT_DUEL name=Red t=3 seq=2 life=1 f=100,30,20,30,2,1,0,0,0 teacher=0 selected=0 applied=0 owner=fight model=teacher\n"
               "BOT_RED_STATE name=Red t=4 life=1 hp=100 shields=30 kills=1 deaths=0 dead=0\n"
               "BOT_RED_STATE name=Red t=5 life=2 hp=100 shields=30 kills=2 deaths=1 dead=0\n")
        ingest_match_log(store, log, "map", "ffa")
        rows = store.decisions("pickup_engage")
        self.assertEqual([r["outcome"].get("kill", 0) for r in rows], [0, 1])

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

    def test_matched_edge_telemetry_counts_one_traversal_and_separates_builds(self):
        store = BrainStore(self.root, "red")
        self.addCleanup(store.close)
        edge = ("BOT_EDGE_ATTEMPT name=Red t=3.0 event=arrive from_key=aa to_key=bb "
                "edge=0 dist_mm=1500 dz_mm=-250 from_water=0 to_water=1 dest_item=1 "
                "base_cost_milli=2500 degree_from=3 degree_to=2\n")
        recall = ("BOT_NAV_LEARN name=Red t=3.0 event=arrive from=0 to=1 from_key=aa "
                  "to_key=bb edge=0 before=2 after=0 saved=1\n")
        for build in ("old", "new"):
            log = edge + recall + "engine " + build
            self.assertEqual(ingest_match_log(store, log, "m", "ffa", build=build)["edges"], 1)
        for build in ("old", "new"):
            e = store.edge_estimate("m", "ffa", "aa", "bb", 0, build=build)
            self.assertEqual((e["attempts"], e["successes"]), (1, 1))
        self.assertEqual({r["build"] for r in store.edge_rows()}, {"old", "new"})

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
        self.assertFalse(qualify_decision_candidate(store, "engage", good)["ok"])
        for map_sha in ("a" * 64, "b" * 64):
            with store.match_log("log-" + map_sha, map_sha, map_sha, "", "unknown", "", "holdout", 5):
                for _ in range(10):
                    store.append_decision("engage", {"distance": 1.0}, teacher=1,
                                          outcome={"kill": 1}, map_sha=map_sha)
                    store.append_decision("engage", {"distance": 5.0}, teacher=0,
                                          outcome={"death": 1}, map_sha=map_sha)
        self.assertEqual(train_decision_from_store(store, "engage", ["distance"])["train"]["rows"], 80)
        verdict = qualify_decision_candidate(store, "engage", good, min_rows=10)
        self.assertTrue(verdict["ok"], verdict["reasons"])
        bad = dict(good)
        bad["weights"] = [-w for w in good["weights"]]
        bad["bias"] = -good["bias"]
        refused = qualify_decision_candidate(store, "engage", bad, min_rows=10)
        self.assertFalse(refused["ok"])
        self.assertTrue(any("balanced accuracy" in r for r in refused["reasons"]))
        store.close()

    def test_same_weights_can_qualify_and_roll_back_on_two_independent_maps(self):
        store = BrainStore(self.root, "red")
        self.addCleanup(store.close)
        weights = self.root / "duel"
        weights.write_bytes(b"same weights")
        sha = store.register_model(weights, "pickup_engage", "nf|map1")
        store.register_model(weights, "pickup_engage", "nf|map2")
        with self.assertRaisesRegex(ValueError, "scope"):
            store.promote_model(sha, safety_ok=True, heldout_ok=True)
        for scope in ("nf|map1", "nf|map2"):
            store.promote_model(sha, safety_ok=True, heldout_ok=True, kind="pickup_engage", scope=scope)
        store.rollback("pickup_engage", "nf|map2")
        self.assertIsNone(store.active_model("pickup_engage", "nf|map2"))
        self.assertEqual(store.active_model("pickup_engage", "nf|map1")["status"], "active")

    def test_independent_coaches_preserve_models_and_can_return_to_script(self):
        a = BrainStore(self.root, "red")
        b = BrainStore(self.root, "red")
        self.addCleanup(a.close)
        self.addCleanup(b.close)
        model = self.root / "model"
        model.write_bytes(b"A")
        first = a.register_model(model, "decision", "nf")
        model.write_bytes(b"B")
        second = b.register_model(model, "decision", "nf")
        a.promote_model(first, safety_ok=True, heldout_ok=True)
        b.promote_model(second, safety_ok=True, heldout_ok=True)
        self.assertEqual(a.active_model("decision", "nf")["sha256"], second)
        self.assertEqual(a.rollback("decision", "nf"), first)
        self.assertIsNone(b.rollback("decision", "nf"))
        self.assertIsNone(a.active_model("decision", "nf"))

    def test_next_rollout_selects_exact_cell_and_restores_script_after_rollback(self):
        from bots.brain import DUEL_FEATURES
        from scripts.bot_development.train_matches import active_pickup
        store = BrainStore(self.root, "red")
        self.addCleanup(store.close)
        model = self.root / "native.weights"
        source = fit_decision_model([({name: n for name in DUEL_FEATURES}, int(n > 0))
                                     for n in (-2, -1, 1, 2)], DUEL_FEATURES)
        export_red_neural(source, model)
        cell = ("ffa/guns/noforce", "1"*64, "2"*64)
        sha = store.register_model(model, "pickup_engage", "|".join(cell))
        self.assertIsNone(active_pickup(store, *cell))
        store.promote_model(sha, safety_ok=True, heldout_ok=True)
        self.assertEqual(active_pickup(store, *cell).read_bytes(), model.read_bytes())
        self.assertIsNone(active_pickup(store, cell[0], "3"*64, cell[2]))
        self.assertIsNone(active_pickup(store, "ctf/guns/force", cell[1], cell[2]))
        store.rollback("pickup_engage", "|".join(cell))
        self.assertIsNone(active_pickup(store, *cell))

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

    def test_teacher_anchor_keeps_unrewarded_demonstrations_in_the_fit(self):
        from bots.brain import fit_outcome_model
        rows = [{"features": {"x": i}, "teacher": int(i > 0), "applied": int(i > 0),
                 "outcome": {"kill": 1} if abs(i) == 1 else {}} for i in (-3, -2, -1, 1, 2, 3)]
        model = fit_outcome_model(rows, ["x"], teacher_fraction=0.5)
        self.assertEqual(model["train"]["teacher_rows"], 6)
        self.assertEqual(model["train"]["rows"], 2)
        self.assertLess(predict_decision(model, {"x": -2}), 0.5)
        self.assertGreater(predict_decision(model, {"x": 2}), 0.5)

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
