"""Persistent route costs start empty and improve from actual edge outcomes."""
import tempfile
import unittest
from pathlib import Path
from bots.brain import parse_edge_native, predict_edge
from bots.navigation_memory import LiveNavigationMemory, NavigationMemory, navigation_rules, parse_observation

STALL = "BOT_EDGE_ATTEMPT name=Jan t=8.200 event=stall from_key=ad to_key=fe edge=1 dist_mm=600 dz_mm=400 from_water=0 to_water=0 dest_item=0 base_cost_milli=1500 degree_from=2 degree_to=3"
ARRIVE = STALL.replace("event=stall", "event=arrive")
FEATURES = dict(distance=.6, dz=.4, abs_dz=.4, mode=1, from_water=0, to_water=0,
                dest_item=0, base_cost=1.5, degree_from=2, degree_to=3)


class NavigationMemoryTests(unittest.TestCase):
    def test_cold_start_restart_and_direction(self):
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "learning"
            first = NavigationMemory(db, "jan", "a"*64)
            self.assertIsNone(first.snapshot())
            bad = parse_observation(STALL, "Jan")
            first.observe("game1", 1, [bad] * 3)
            second = NavigationMemory(db, "jan", "a"*64)
            raw, digest, count = second.snapshot()
            self.assertEqual(count, 3)
            score = predict_edge(parse_edge_native(raw), FEATURES)
            second.observe("game1", 1, [bad] * 3)
            self.assertEqual(second.snapshot()[1], digest)
            second.observe("game2", 1, [parse_observation(ARRIVE, "Jan")]*4)
            self.assertGreater(predict_edge(parse_edge_native(second.snapshot()[0]), FEATURES), score)
            self.assertIsNone(NavigationMemory(db,"jan","b"*64).snapshot())
            self.assertIsNone(NavigationMemory(db,"red","a"*64).snapshot())

    def test_force_rules_keep_separate_weights(self):
        with tempfile.TemporaryDirectory() as d:
            nf = NavigationMemory(d, "jan", "a"*64, "nf-sabers")
            nf.observe("match", 1, [parse_observation(STALL, "Jan")])
            self.assertIsNone(NavigationMemory(d, "jan", "a"*64, "ff-guns").snapshot())
            self.assertEqual(NavigationMemory(d, "jan", "a"*64, "nf-sabers").snapshot()[2], 1)

    def test_live_multibank_batch_retry_is_idempotent(self):
        import sqlite3
        from contextlib import closing

        with tempfile.TemporaryDirectory() as directory:
            memory = LiveNavigationMemory(directory, "jan", "c"*64, 8)
            edge = parse_observation(ARRIVE, "Jan")
            batch = [("ff-guns", edge), ("nf-sabers", edge)]
            first, second = memory.bank("ff-guns"), memory.bank("nf-sabers")
            with closing(sqlite3.connect(second.db)) as writer:
                writer.execute("BEGIN IMMEDIATE")
                with self.assertRaises(sqlite3.OperationalError):
                    memory.observe("one-match", 1, batch)
                self.assertEqual(first.snapshot()[2], 1)
            memory.observe("one-match", 1, batch)
            memory.observe("one-match", 1, batch)
            self.assertEqual((first.snapshot()[2], second.snapshot()[2]), (1, 1))
            memory.observe("one-match", 3, [("ff-guns", edge)])
            self.assertEqual(first.snapshot()[2], 2)
            self.assertIsNone(navigation_rules(4, True, True))
            self.assertEqual(navigation_rules(4, True, False), "nf-sabers")

    def test_native_log_resumes_after_busy_db_with_bounded_queue(self):
        import sqlite3
        from contextlib import closing
        from types import SimpleNamespace
        from bots.run import Child, inspect_log

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "native.log"
            log.write_text((ARRIVE + "\n") * 260, encoding="ascii")
            memory = NavigationMemory(root / "memory", "jan", "c"*64)
            child = Child("Jan", None, SimpleNamespace(name=log), record={"joined": True},
                          memory=memory, navigation_session="game")
            with closing(sqlite3.connect(memory.db)) as competing:
                competing.execute("BEGIN IMMEDIATE")
                inspect_log(child)
                self.assertIn("navigation_memory_error", child.record)
                self.assertEqual(child.record["navigation_pending"], 256)
                self.assertEqual(child.record["navigation_discarded"], 4)
            # No new log bytes are needed when storage becomes writable again.
            inspect_log(child, final=True)
            self.assertEqual(memory.snapshot()[2], 256)
            self.assertEqual(child.record["navigation_pending"], 0)
            self.assertNotIn("navigation_memory_error", child.record)
            with log.open("a", encoding="ascii") as stream:
                stream.write((STALL + "\n") * 260)
            inspect_log(child)
            self.assertEqual(memory.snapshot()[2], 516)
            self.assertEqual(child.observations, 516)
            self.assertEqual(child.record["navigation_discarded"], 4)

    def test_only_owned_well_formed_engine_observations(self):
        self.assertIsNotNone(parse_observation(STALL, "Jan"))
        for msg in ("CHAT " + STALL, STALL+" suffix", STALL.replace("edge=1", "edge=10000"),
                    STALL.replace("dist_mm=600", "dist_mm=-600"), STALL.replace("name=Jan", "name=Red")):
            self.assertIsNone(parse_observation(msg, "Jan"))

