"""Roster bodies from a -path mod GOB, and per-seat saber colors. Wren (AI collaborator, via Grok Bot)."""
import struct
import tempfile
import unittest
from pathlib import Path

from web_bots.headless import build_parser
from web_bots.join_room import unsupported
from web_bots.serve import gob_names, seat_character


def tiny_gob(path, names):
    body = b"".join(b"x" for _ in names)
    index_at = 12 + len(body)
    index = struct.pack("<I", len(names)) + b"".join(
        struct.pack("<II", 12 + i, 1) + n.encode().ljust(128, b"\0") for i, n in enumerate(names))
    path.write_bytes(struct.pack("<4sII", b"GOB ", 0x14, index_at) + body + index)


class RosterTest(unittest.TestCase):
    def test_gob_index_names(self):
        with tempfile.TemporaryDirectory() as d:
            gob = Path(d) / "r.gob"
            tiny_gob(gob, ["3do\\T800HY4.3do", "misc/snd/dlil.snd"])
            self.assertEqual(gob_names(gob), {"3do\\t800hy4.3do", "misc\\snd\\dlil.snd"})

    def test_seats_wear_bodies_the_gob_carries(self):
        files = frozenset({"dlil.3do", "dlil.snd", "lvane.3do", "t800hy4.3do"})
        self.assertEqual(seat_character("lily", files)[1:3], ("dlil.3do", "dlil.snd"))
        self.assertEqual(seat_character("t800", files)[1:3], ("t800hy4.3do", "ky.snd"))
        self.assertEqual(seat_character("lilivane", files)[1:3], ("lvane.3do", "kyfemale.snd"))
        # Not in the GOB: the stock Kyle variant stays.
        self.assertEqual(seat_character("biddy", files)[1:3], ("ky.3do", "ky.snd"))
        self.assertEqual(seat_character("t800")[1:3], ("kyi14.3do", "kybossk.snd"))
        # A custom voice missing from the GOB falls back to the stock one.
        self.assertEqual(seat_character("lily", frozenset({"dlil.3do"}))[1:3], ("dlil.3do", "ky.snd"))

    def test_red_sabers_and_model_gob_flags(self):
        args = build_parser().parse_args(["join", "--room-id", "5", "--seats", "t800", "--data", "d", "--runtime", "r",
                                          "--red-sabers", "lily,t800", "--model-gob", "x.gob"])
        self.assertEqual(args.red_sabers, ("lily", "t800"))
        self.assertEqual(args.model_gob, Path("x.gob"))
        self.assertEqual(build_parser().parse_args(["join", "--room-id", "5", "--seats", "t800", "--data", "d",
                                                    "--runtime", "r"]).red_sabers, ("lily",))

    def test_mod_rooms_need_a_mod(self):
        game = {"game": "jk1", "net": 2, "locked": False, "mod": "companion", "players": 1, "max": 6,
                "episode": "JK1MP", "map": "m10.jkl"}
        self.assertEqual(unsupported(game), "requires a host mod")
        self.assertEqual(unsupported(game, allow_mod=True), "")


if __name__ == "__main__":
    unittest.main()
