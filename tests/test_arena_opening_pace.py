import json
from pathlib import Path
import tempfile
import unittest

from scripts.bot_development.analysis import opening_pace as pace


def plan(item, time=0):
    return f"BOT_GEAR name=Bot_JanOrs t={time}.00 event=plan item={item} guid={item} signature=30 pack=0 anchor=30 direct=1"


class OpeningPaceTests(unittest.TestCase):
    def setUp(self):
        self.out = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.seat = dict(name="Bot_JanOrs", slot=1, sector=41, first_plan_item=29,
                         first_life_gain_seconds_after_release={"concussion_rifle": 1.122, "repeater": None})

    def path(self, lines, **fields):
        p = self.out / "owner.log"
        p.write_text("\n".join(["ADJOIN_OPENING", "GATE_UNLOCK_APPLIED", *lines]) + "\n", encoding="ascii")
        return pace.opening_path(p, {**self.seat, **fields})

    def test_path_preserves_returning_to_an_item_and_ignores_repeated_same_item_plans(self):
        normal = self.path([plan(29), plan(29), plan(11), plan(11), plan(29), "Concussion Rifle", plan(3)])
        fast = self.path([plan(29), "Concussion Rifle"])
        row = pace.paired_owner(normal, fast, .10, .20)
        self.assertEqual(row["target_sequences"], [[29, 11, 29], [29]])
        self.assertTrue(row["same_initial_target"])
        self.assertFalse(row["same_target_sequence"])
        self.assertTrue(row["exact_time"])

    def test_unmonitored_first_target_wrong_weapon_missing_or_ambiguous_are_not_timing_agreement(self):
        good = self.path([plan(29), "Concussion Rifle"])
        wrong = self.path([plan(500), plan(29), "Concussion Rifle"], first_plan_item=500)
        pack = self.path([plan(29).replace("pack=0", "pack=1"), "Concussion Rifle"])
        repeater = self.path([plan(29), "Repeater Gun"], first_life_gain_seconds_after_release={"repeater": 1.1})
        missing = self.path([plan(29), "ADJOIN_RESPAWN", "Concussion Rifle"])
        ambiguous = self.path([plan(29), "Concussion Rifle"], first_life_gain_seconds_after_release={
            "concussion_rifle": .9, "repeater": .9})
        no_plan = self.path(["Concussion Rifle", plan(29)])
        for result in (wrong, pack, repeater, missing, ambiguous, no_plan):
            with self.subTest(result=result):
                paired = pace.paired_owner(good, result, .1, .2)
                self.assertIsNone(paired["within_agreement_band"])
        paired = pace.paired_owner(good, repeater, .1, .2)
        self.assertFalse(paired["same_corroborated_weapon"])
        self.assertTrue(paired["same_target_sequence"])
        self.assertEqual(wrong["target_sequence"], [500, 29])
        self.assertIsNone(no_plan["first_target"])
        self.assertEqual(ambiguous["unresolved_reason"], "simultaneous_sampled_weapon_gains")

    def test_registered_signed_deltas_keep_microseconds_and_inclusive_boundaries(self):
        good = self.path([plan(29), "Concussion Rifle"])
        for delta, exact, fine, wide in [(0, True, True, True), (.000001, False, True, True),
                                         (-.100000, False, True, True), (.2, False, False, True),
                                         (-.200001, False, False, False)]:
            with self.subTest(delta=delta):
                fast = dict(good, qualified_gain_s=good["qualified_gain_s"]+delta)
                paired = pace.paired_owner(good, fast, .10, .20)
                self.assertEqual(paired["fast_minus_normal_game_s"], delta)
                self.assertEqual((paired["exact_time"], paired["within_secondary_band"], paired["within_agreement_band"]),
                                 (exact, fine, wide))
                if delta == .000001:
                    self.assertTrue(paired["same_rounded_elapsed_millisecond"])

    def fake_clocks(self):
        start = 10_000_000_000
        speed = 2
        experiment = dict(speed=speed, requested_game_seconds=22, start_monotonic_ns=start, roles={})
        gate = {"host_acknowledgements": [{"host_time_s": .2}], "owners": {s: {"release_time_s": .2, "unlock_time_s": .2} for s in ("dark", "light")}}
        owners = {s: {"qualified_gain_s": 1.12} for s in ("dark", "light")}
        rows_by_role = {}
        for k, (role, filename) in enumerate(pace.ROLE_LOGS.items(), 1):
            rows = [dict(role=role, pid=k, rate=speed, frame=5*(i+2), game_ms=340+170*i,
                         mono_ns=start+1000000*k+85000000*i, step_ms=34, applied_ms=34) for i in range(-1,131)]
            def marker(row):
                return "ARENA_PACE " + " ".join(f"{key}={value}" for key,value in row.items())
            gate_lines = ["GATE_HOST_ACK"] * 2 if role == "host" else ["GATE_UNLOCK_APPLIED"]
            lines = ["OpenJKDF2: sithWorld_Load -> m10.jkl", marker(rows[0]), *gate_lines, *map(marker,rows[1:])]
            (self.out / filename).write_text("\n".join(lines)+"\n", encoding="ascii")
            experiment["roles"][role] = dict(pid=k,first=rows[1],last=rows[-1],
                                             final_sample=rows[-1],observed_rate=2.0,measured_game_s=22.1,
                                             measured_wall_s=11.05,observed_game_tail_s=.1)
            rows_by_role[role]=rows
        trace=self.out / "pace-trace.jsonl"
        trace.write_text("".join(json.dumps(r)+"\n" for rows in rows_by_role.values() for r in rows))
        experiment.update(trace_sha256=pace.sha(trace), end_monotonic_ns=rows_by_role["light"][-1]["mono_ns"]+1000)
        return experiment, gate, owners

    def test_three_native_rate_proofs_and_opening_bracket(self):
        pace.check_schedule(json.loads(pace.SCHEDULE.read_bytes())["runs"])
        e,g,o = self.fake_clocks()
        clocks=pace.read_clocks(self.out,e,g,o)
        self.assertEqual({r["observed_rate"] for r in clocks.values()},{2.0})
        self.assertEqual(clocks["dark"]["opening_rate"]["observed_rate"],2)
        self.assertEqual(clocks["light"]["opening_rate"]["first_sample_minus_release_game_ms"],-30)

    def test_clock_evidence_fails_when_role_step_rate_cutoff_or_trace_is_wrong(self):
        for failure in ("role", "step", "rate", "target", "trace", "tail"):
            with self.subTest(failure=failure):
                e,g,o = self.fake_clocks()
                if failure=="target":
                    e["roles"]["dark"]["last"]=e["roles"]["dark"]["first"]
                elif failure=="tail":
                    e["roles"]["host"]["observed_game_tail_s"] = 0
                elif failure=="trace":
                    p=self.out/"pace-trace.jsonl"
                    rows=p.read_text().splitlines()
                    p.write_text("\n".join(rows[:10]+rows[11:])+"\n")
                    e["trace_sha256"]=pace.sha(p)
                elif failure=="rate":
                    e["roles"]["host"]["observed_rate"]=1.
                else:
                    p=self.out/"light.log"
                    before,after=("role=light","role=dark") if failure=="role" else ("applied_ms=34","applied_ms=40")
                    p.write_text(p.read_text().replace(before,after))
                with self.assertRaises(ValueError):
                    pace.read_clocks(self.out,e,g,o)
