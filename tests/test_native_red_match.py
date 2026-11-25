import io
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.bot_development.legacy import native_red_match as red
from scripts.bot_development.legacy.native_observation_pace import NativePace


class NativeRedMatchTests(unittest.TestCase):
    def test_starts_clock_after_roster_without_waiting_for_game_gate(self):
        experiment = {"speed":2,"requested_game_seconds":90}
        pace = NativePace(io.StringIO(), experiment, ungated=True)
        self.assertFalse(pace.poll(2000))
        self.assertEqual(experiment["roster_observed_monotonic_ns"], 2000)
        for idx in range(15):
            when = 2000 + idx * 85_000_000
            for role in ("host","dark","light"):
                pace.observe(role, 1, f"ARENA_PACE role={role} pid=1 rate=2 frame={idx*5} "
                             f"game_ms={idx*170} mono_ns={when} step_ms=34 applied_ms=34")
            pace.poll(when)
        self.assertEqual(experiment["start_monotonic_ns"], 2000 + 12 * 85_000_000)
        self.assertEqual(pace.released, set())

    def test_records_real_movement_before_second_native_join(self):
        receipt={"pace_experiment":{"loaded_images":{"host":{"pid":30},"dark":{"pid":40},"light":{"pid":50}}},
                 "red_policy":{"model_side":None,"weights_sha256":None},
                 "bots":{"dark":{"joined":{"slot":1}},"light":{"joined":{"slot":2}}}}
        with TemporaryDirectory() as d:
            dest=Path(d)
            (dest/"pace-trace.jsonl").write_text('{"role":"host","pid":30,"mono_ns":80}\n')
            for side,pid,slot,base in (("dark",40,1,100),("light",50,2,200)):
                state="BOT_RED_STATE hp=100 shields=50 weapons=6 life=1 game_ms=5 mono_ns=20 kills=0 deaths=0 dead=0\n"
                text=(f"BOT_RED_MODEL name={side} pid={pid} mode=teacher model=teacher status=ready\n"
                      f"BOT_RED_JOIN name={side} pid={pid} slot={slot} mono_ns={base}\n"
                      f"BOT_RED_FIRST name={side} pid={pid} frame=1 mono_ns={base+1}\n"
                      f"BOT_RED_APPLY name={side} pid={pid} frame=1 mono_ns={base+2} fwd=1 slide=0\n"
                      +state+state.replace("weapons=6","weapons=518"))
                (dest/(side+".log")).write_text(text)
            r=red.first_controls(dest,receipt)
            self.assertEqual(r["owners"]["dark"]["eligible_to_movement_frames"], 0)
            self.assertEqual(r["owners"]["dark"]["owner_state"]["weapon_gains"][0]["bin"], 9)
            self.assertAlmostEqual(r["first_seat_move_before_second_join_wall_s"], 98e-9)
            path=dest/"dark.log"
            path.write_text(path.read_text().replace("mono_ns=102", "mono_ns=290"))
            with self.assertRaisesRegex(ValueError,"not_before_second_join"):
                red.first_controls(dest,receipt)

    def test_gate_or_planning_intent_cannot_certify_nonzero_movement(self):
        with TemporaryDirectory() as d:
            p=Path(d)/"actor.log";p.write_text("GATE_HELD\n")
            with self.assertRaisesRegex(ValueError, "unexpected_start_gate"):
                red.read_owner(p)
            p.write_text("BOT_DUEL teacher=fight\nBOT_GEAR event=plan item=29\n")
            evidence=red.read_owner(p)
            self.assertEqual(evidence["first_movement_by_life"],[])
            self.assertIsNone(evidence["last_native_score_sample"])
