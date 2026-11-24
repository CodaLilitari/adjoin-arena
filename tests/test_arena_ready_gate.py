"""Exercise the public ready-gate verifier without running or distributing a game."""
import contextlib
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts.bot_development import controlled_opening, ready_gate
from scripts.bot_development.legacy import native_force_observation as launcher


def record(name, *values):
    return "\n".join(map(str, (name, *values))) + "\n"


WORLD = "OpenJKDF2: sithWorld_Load -> m10.jkl\n"
GO = record("GATE_TRIGGER_DIAG", 7312, 1, 7312, 2, 7312)
BOTS = {"dark": {"joined": {"slot": 1, "net": 3}}, "light": {"joined": {"slot": 2, "net": 7}}}


def ready(slot, seen):
    return record("GATE_OBS_READY", slot, 0.1, seen)


def owner_log(slot, net):
    sector, position = controlled_opening.STARTS[slot]
    pose = "<" + " ".join(map(str, position)) + ">"
    local_release = 4.5 if slot == 1 else 0.2
    data = [WORLD, f"BOT_JOINED slot={slot} net={net}\n", record("GATE_SCRIPT_LOADED", 0),
            record("GATE_SPAWN_INVENTORY", *([0] * 15)), record("GATE_HELD", slot, 0, pose),
            record("ADJOIN_OPENING", slot, sector, pose, 0, 0), record("ADJOIN_RIFLE_BASE", 0),
            "BOT_FORCE_STATE name=bot immobile=1 mana=400.00 active=0x0\n",
            "BOT_GEAR name=bot t=0.00 event=plan item=29 direct=1\n",
            record("GATE_POST_LOADOUT", 0.1, *ready_gate.LOADOUT), record("GATE_SEND_READY", slot, 0, 0, 0)]
    if slot == 1:
        data.extend([ready(1, 0.1), ready(2, 4.4), record("GATE_COORDINATOR_GO", 3, 4.4)])
    data.extend([GO, record("GATE_LOCAL_RELEASE", slot, 4.4, local_release, 2, 0, 0, 0, pose, 0),
                 record("GATE_UNLOCK_APPLIED", slot, 0, 1, 1, 4.4, local_release)])
    if slot == 1:
        data.append(record("ADJOIN_RIFLE_CHANGE", 0, 1, 5.5))
    return "".join(data)


class ReadyGateTests(unittest.TestCase):
    def setUp(self):
        self.folder = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.logs = {side: owner_log(**seat["joined"]) for side, seat in BOTS.items()}
        # ACK arrival order can differ from the game seats' join order.
        self.logs["server"] = (WORLD + record("GATE_SCRIPT_LOADED", 1) + ready(1, 3) + ready(2, 8) +
                               GO + record("GATE_HOST_GO_SEEN", 3, 4.4, 8) +
                               record("GATE_HOST_ACK", 2, 2, 4.4, 8.01) + record("GATE_HOST_ACK", 1, 3, 4.4, 8.03))

    def verify(self, edits=()):
        logs = self.logs.copy()
        for side, old, new in edits:
            self.assertEqual(logs[side].count(old), 1, old)
            logs[side] = logs[side].replace(old, new)
        for side, contents in logs.items():
            (self.folder / (side + ".log")).write_text(contents, encoding="ascii")
        return ready_gate.qualify(self.folder, controlled_opening.qualify(self.folder, BOTS))

    def test_gate_binds_three_game_clocks_and_tracks_plans_and_post_release_rifle(self):
        outcome = self.verify()
        self.assertEqual(outcome["status"], "qualified")
        self.assertEqual([ack["slot"] for ack in outcome["host_acknowledgements"]], [2, 1])
        self.assertEqual(outcome["owners"]["dark"]["first_rifle_gain_after_release_s"], 1)
        self.assertIsNone(outcome["owners"]["light"]["first_rifle_gain_after_release_s"])
        self.assertEqual(outcome["owners"]["light"]["pre_release_plans"], [{"item": 29, "bot_time_s": 0}])

    def test_missing_mismatched_and_duplicate_release_is_rejected(self):
        for edit in (("server", record("GATE_HOST_ACK", 1, 3, 4.4, 8.03), ""),
                     ("server", record("GATE_HOST_ACK", 2, 2, 4.4, 8.01), record("GATE_HOST_ACK", 2, 1, 4.4, 8.01)),
                     ("server", ready(2, 8), ""),
                     ("dark", record("GATE_COORDINATOR_GO", 3, 4.4), record("GATE_COORDINATOR_GO", 1, 4.4)),
                     ("light", GO, GO.replace("7312\n1\n", "7312\n2\n")),
                     ("light", GO, GO + GO),
                     ("light", record("GATE_UNLOCK_APPLIED", 2, 0, 1, 1, 4.4, 0.2), ""),
                     ("light", record("GATE_UNLOCK_APPLIED", 2, 0, 1, 1, 4.4, 0.2),
                      record("GATE_UNLOCK_APPLIED", 2, 0, 1, 1, 4.5, 0.2)),
                     ("dark", record("GATE_SEND_READY", 1, 0, 0, 0), record("GATE_SEND_READY", 1, 0, 0.001, 0))):
            with self.subTest(edit=edit), self.assertRaises(ValueError):
                self.verify([edit])

    def test_early_acquisition_active_controls_or_clocks_reject(self):
        gain = record("ADJOIN_RIFLE_CHANGE", 0, 1, 5.5)
        with self.assertRaises(ValueError):
            self.verify([("dark", gain, ""), ("dark", GO, gain + GO)])
        for edit in (("dark", gain, record("ADJOIN_RIFLE_CHANGE", 0, 1, 2.0)),
                     ("dark", GO, "BOT_FIRE_INPUT name=bot\n" + GO),
                     ("light", GO, "BOT_FORCE_INPUT name=bot\n" + GO),
                     ("light", "immobile=1", "immobile=0"),
                     ("dark", ready(2, 4.4), ready(2, 4.6)),
                     ("server", ready(1, 3), record("GATE_OBS_READY", 1, "nan", 3)),
                     ("dark", "GATE_POST_LOADOUT\n0.1", "GATE_POST_LOADOUT\n<1 2 3>")):
            with self.subTest(edit=edit), self.assertRaises(ValueError):
                self.verify([edit])

    def test_ready_gate_host_uses_line_buffering_without_camera(self):
        engine = "/private/openjkdf2"
        with patch.dict(launcher.CHILDREN, clear=True), patch.dict(launcher.READERS, clear=True), \
             patch.object(launcher.subprocess, "Popen") as spawn:
            launcher.boot("server", [engine, "-dedicated"], self.folder, {}, self.folder, line_buffered=True)
            self.addCleanup(launcher.READERS["server"].close)
            self.assertEqual(spawn.call_args.args[0], ["stdbuf", "-oL", engine, "-dedicated"])
            self.assertIs(launcher.CHILDREN["server"], spawn.return_value)

    def test_ready_gate_cli_requires_private_canyon_and_a_single_scenario(self):
        basic = ["launcher", "--repo", "unused", "--data", "unused", "--output", "unused", "--ready-gate"]
        for extra in (["--map", "m10.jkl"], ["--arena-baseline", "--map", "m2.jkl"],
                      ["--arena-baseline", "--map", "m10.jkl", "--controlled-opening"]):
            with self.subTest(extra=extra), patch.object(sys, "argv", basic + extra), \
                 contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as invalid:
                launcher.main()
            self.assertEqual(invalid.exception.code, 2)
