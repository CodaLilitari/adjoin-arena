import copy
from pathlib import Path
import tempfile
import unittest

from scripts.bot_development import controlled_opening as opening


def life_log(slot, net):
    sector, position = opening.STARTS[slot]
    coords = " ".join(map(str, position))
    return (f"OpenJKDF2: sithWorld_Load -> m10.jkl\nBOT_JOINED slot={slot} net={net}\n"
            f"ADJOIN_OPENING\n{slot}\n{sector}\n<{coords}>\n0\n0\nADJOIN_RIFLE_BASE\n0\n")


class ControlledOpeningTests(unittest.TestCase):
    def setUp(self):
        work = tempfile.TemporaryDirectory()
        self.addCleanup(work.cleanup)
        self.root = Path(work.name)
        self.seats = {"dark": {"joined": {"slot": 1, "net": 3}}, "light": {"joined": {"slot": 2, "net": 7}}}
        self.dark = self.root / "dark.log"
        self.dark.write_text(life_log(1, 3), encoding="ascii")
        (self.root / "light.log").write_text(life_log(2, 7), encoding="ascii")

    def test_two_openings_and_a_rifle_transition(self):
        self.dark.write_text(life_log(1, 3) + "ADJOIN_RIFLE_CHANGE\n0\n1\n1.124\n", encoding="ascii")
        result = opening.qualify(self.root, self.seats)
        self.assertEqual([e["kind"] for e in result["dark"]["events"]],
                         ["opening", "life_initial_inventory", "sampled_inventory_change"])
        self.assertEqual(result["dark"]["events"][-1]["level_time_s"], 1.124)
        self.assertEqual(result["light"]["events"][0]["sector"], 18)

    def test_first_respawn_uses_normal_mask_and_new_inventory_baseline(self):
        self.dark.write_text(life_log(1, 3) + "ADJOIN_RIFLE_CHANGE\n0\n1\n1.124\n"
                             "ADJOIN_RESPAWN\n1\n20\n<1 2 3>\n0\nADJOIN_RIFLE_BASE\n0\n"
                             "BOT_RESPAWN name=Bot_BobaFett health=100.0\n", encoding="ascii")
        events = opening.qualify(self.root, self.seats)["dark"]["events"]
        self.assertEqual([e["life_ordinal"] for e in events], [1, 1, 1, 2, 2])

    def test_wrong_owner_world_pose_or_restore_fails(self):
        initial = life_log(1, 3)
        for original, new in (("m10.jkl", "m2.jkl"), ("slot=1", "slot=2"), ("net=3", "net=4"),
                              ("\n41\n", "\n40\n"), ("2.39995", "2.49995"),
                              ("0\n0\nADJOIN_RIFLE", "0\n-3\nADJOIN_RIFLE")):
            with self.subTest(original=original):
                self.dark.write_text(initial.replace(original, new), encoding="ascii")
                with self.assertRaises(ValueError):
                    opening.qualify(self.root, self.seats)
        self.dark.write_text(initial * 2, encoding="ascii")
        with self.assertRaises(ValueError):
            opening.qualify(self.root, self.seats)

    def test_evidence_must_follow_the_map_load_and_join(self):
        initial = life_log(1, 3)
        head, records = initial.split("ADJOIN_OPENING", maxsplit=1)
        for forged in ("ADJOIN_OPENING" + records + head,
                       initial + "BOT_RESPAWN name=Bot_BobaFett health=100.0\n"):
            with self.subTest(forged=forged):
                self.dark.write_text(forged, encoding="ascii")
                with self.assertRaises(ValueError):
                    opening.qualify(self.root, self.seats)

    def test_invalid_inventory_histories_are_rejected(self):
        for tail in ("ADJOIN_RIFLE_CHANGE\n1\n0\n1.0\n",
                     "ADJOIN_RIFLE_CHANGE\n0\n2\n1.0\n", "ADJOIN_RIFLE_CHANGE\n0\n1\nnan\n",
                     "ADJOIN_RIFLE_CHANGE\n0\n1\n1.0\nADJOIN_RIFLE_CHANGE\n1\n0\n0.5\n",
                     "ADJOIN_RIFLE_BASE\n0\n", "ADJOIN_RESPAWN\n1\n41\n<0 0 0>\n0\n"):
            with self.subTest(tail=tail):
                self.dark.write_text(life_log(1, 3) + tail, encoding="ascii")
                with self.assertRaises(ValueError):
                    opening.qualify(self.root, self.seats)

    def test_distinct_peer_identities_required(self):
        seats = copy.deepcopy(self.seats)
        seats["light"]["joined"]["net"] = 3
        (self.root / "light.log").write_text(life_log(2, 3), encoding="ascii")
        with self.assertRaises(ValueError):
            opening.qualify(self.root, seats)

    def test_input_guards_leave_files_intact(self):
        source = self.root / "stock.gob"
        target = self.root / "new.gob"
        source.write_bytes(b"another episode")
        with self.assertRaises(ValueError):
            opening.build(source, target)
        self.assertFalse(target.exists())
        self.assertEqual(source.read_bytes(), b"another episode")
        with self.assertRaises(ValueError):
            opening.patch_level(b"a different map")
