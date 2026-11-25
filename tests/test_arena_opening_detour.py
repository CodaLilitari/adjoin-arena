from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.bot_development.analysis.opening_detour import read_opening_detour


def plan(item, direct=1, name="Bot_JanOrs"):
    return (f"BOT_GEAR name={name} t=1.02 event=plan item={item} guid={item} "
            f"signature={item + 1} pack=0 anchor=3 direct={direct}")


class OpeningDetourTests(unittest.TestCase):
    def read(self, lines, first=29, time=1.2):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "light.log"
            path.write_bytes(("\n".join(lines) + "\n").encode("ascii"))
            return read_opening_detour(path, "Bot_JanOrs", first, {"concussion_rifle": time, "repeater": time})

    def test_other_weapon_hud_does_not_end_the_initial_plan_window(self):
        rows = ["ADJOIN_OPENING", plan(29), "GATE_LOCAL_RELEASE", plan(11), "Rail Detonator",
                plan(11, 0), plan(29), "\r       \rConcussion Rifle", plan(34)]
        result = self.read(rows)
        self.assertEqual(result["status"], "qualified")
        self.assertEqual(result["pickup"], dict(line=8, hud="Concussion Rifle", weapon="concussion_rifle",
                                                owner_gain_seconds_after_release=1.2))
        self.assertEqual([p["item"] for p in result["plans"]], [29, 11, 11, 29])
        self.assertEqual([p["change"] for p in result["plans"]],
                         ["initial", "changed_target", "same_item_replan", "changed_target"])
        self.assertTrue(result["post_release_different_item_plan_before_pickup"])

    def test_same_item_replan_and_release_boundary(self):
        for original in (10, 34):
            rows = ["ADJOIN_OPENING", plan(original), "GATE_LOCAL_RELEASE", plan(original, 0), "Repeater Gun"]
            result = self.read(rows, first=original)
            self.assertFalse(result["different_item_plan_before_pickup"])
            self.assertEqual([p["after_release"] for p in result["plans"]], [False, True])
        rows = ["ADJOIN_OPENING", plan(29), plan(11), "GATE_LOCAL_RELEASE", plan(29), "Concussion Rifle"]
        result = self.read(rows)
        self.assertTrue(result["different_item_plan_before_pickup"])
        self.assertFalse(result["post_release_different_item_plan_before_pickup"])

    def test_two_repeater_racks_are_distinct_targets_for_the_same_hud(self):
        result = self.read(["ADJOIN_OPENING", plan(34), "GATE_LOCAL_RELEASE",
                            plan(10), "Repeater Gun"], first=34)
        self.assertTrue(result["post_release_different_item_plan_before_pickup"])
        self.assertEqual(result["pickup"]["weapon"], "repeater")

    def test_missing_or_later_life_evidence_is_unknown(self):
        rows = ["ADJOIN_OPENING", plan(29), "GATE_LOCAL_RELEASE", plan(11)]
        for tail in ([], ["Picked up Concussion Rifle"], ["ADJOIN_RESPAWN", "Concussion Rifle"],
                     ["BOT_RESPAWN name=Bot_JanOrs health=100.0", "Concussion Rifle"]):
            result = self.read(rows + tail)
            self.assertEqual(result["status"], "unobserved")
            self.assertIsNone(result["different_item_plan_before_pickup"])
        self.assertEqual(self.read(rows + ["Concussion Rifle"], time=None)["reason"],
                         "missing_first_life_inventory_gain")
        self.assertEqual(self.read([plan(29), "Concussion Rifle"])["reason"], "missing_opening")
        self.assertEqual(self.read(rows, first=11)["reason"], "unmonitored_initial_item")

    def test_reject_mismatched_native_evidence(self):
        for first in (plan(34), plan(29, name="Bot_BobaFett"), plan(29).replace("direct=1", "direct=3")):
            with self.assertRaises(ValueError):
                self.read(["ADJOIN_OPENING", first, "GATE_LOCAL_RELEASE", "Concussion Rifle"])
        result = self.read(["ADJOIN_OPENING", plan(29), "Concussion Rifle", "GATE_LOCAL_RELEASE"])
        self.assertEqual(result["reason"], "hud_precedes_plan_or_release")
