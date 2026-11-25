"""PR4 headless launcher and hosted seat. Wren (AI collaborator, via Grok Bot)."""
import tempfile
import unittest
from pathlib import Path

from web_bots import headless as H
from web_bots.join_room import ZONE_RELAY

LOCAL = "ws://127.0.0.1:18080/relay"


class Seats(unittest.TestCase):
    def test_parse_seats_limits(self):
        self.assertEqual(H.parse_seats("red,biddy"), ["red", "biddy"])
        for bad, kw in (("red,red", {}), ("nobody", {}), ("lily,red", {"host_seat": "lily"}),
                        (",".join(["red"] * 1), {"host_seat": "lily", "max_players": 1})):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                H.parse_seats(bad, **kw)
        with self.assertRaises(ValueError):
            H.parse_seats(",".join(list(H.ROOM_PLAYERS)[1:8]), host_seat="lily", max_players=6)

    def test_find_hosted_requires_one_exact_room(self):
        games = [dict(id=3, name="Canyon_A", max=12), dict(id=4, name="Canyon_B", max=12)]
        self.assertEqual(H.find_hosted(games, "Canyon_A", 12), 3)
        self.assertIsNone(H.find_hosted(games, "Canyon_A", 4))
        self.assertIsNone(H.find_hosted(games + [dict(id=5, name="Canyon_A", max=12)], "Canyon_A", 12))


class Validation(unittest.TestCase):
    def parse(self, *argv):
        parser = H.build_parser()
        args = parser.parse_args(list(argv))
        H.validate(args, parser)
        return args

    def common(self):
        return ["--seats", "red,lilivane", "--data", "/tmp", "--runtime", "/tmp"]

    def test_public_host_needs_confirmation(self):
        with self.assertRaises(SystemExit):
            self.parse("host", "--relay", ZONE_RELAY, *self.common())
        args = self.parse("host", "--relay", ZONE_RELAY, "--public-room", *self.common())
        self.assertEqual(args.max_players, 12)
        self.assertEqual(args.map, "m10.jkl")
        self.assertEqual(args.mode, "ff-guns")

    def test_local_host_and_bad_values(self):
        self.assertEqual(self.parse("host", "--relay", LOCAL, *self.common()).seat_list, ["red", "lilivane"])
        for extra in (["--max-players", "1"], ["--max-players", "17"], ["--map", "../x.jkl"],
                      ["--room-name", "has space"], ["--adaptive-lily", "--host-seat", "red", "--seats", "biddy"]):
            with self.subTest(extra=extra), self.assertRaises(SystemExit):
                self.parse("host", "--relay", LOCAL, *self.common(), *extra)
        with self.assertRaises(SystemExit):
            self.parse("join", "--relay", "ws://localhost:1/relay", "--room-id", "4", *self.common())


class BrowserBridge(unittest.TestCase):
    def test_client_forwards_every_plain_command(self):
        """CP_TACTICS (21) was silently dropped in the page; the coach saw only 'unconfirmed'."""
        import re
        from bots.companion import KINDS, LILY_COMMANDS
        text = (Path(H.__file__).parent / "client.js").read_text()
        plain = re.search(r"const allowed = \[([0-9,]+)\]\.includes\(data\[5\]\)", text)
        lily = re.search(r"adaptiveLily && \[([0-9,]+)\]\.includes\(data\[5\]\)\);", text)
        self.assertEqual({int(x) for x in plain.group(1).split(",")},
                         set(KINDS.values()) - set(LILY_COMMANDS.values()))
        self.assertEqual({int(x) for x in lily.group(1).split(",")}, set(LILY_COMMANDS.values()))


class HostedSeat(unittest.TestCase):
    def test_hosted_boot_environment(self):
        from web_bots.serve import Host
        d = tempfile.TemporaryDirectory(); self.addCleanup(d.cleanup)
        root = Path(d.name)
        data = root / "JK"
        for name in ("resource/Res1hi.gob", "resource/Res2.gob", "resource/jk_.cd", "episode/JK1MP.gob"):
            (data / name).parent.mkdir(parents=True, exist_ok=True); (data / name).write_bytes(b"x")
        engine = root / "engine"; engine.mkdir()
        for name in ("openjkdf2.js", "openjkdf2.wasm"):
            (engine / name).write_bytes(b"x")
        hosted = H.HostedRoom(LOCAL, "lily", 12, "m10.jkl", "Canyon_T")
        host = Host(data, engine, root / "run", "Canyon_T", None, False, "ff-guns", hosted=hosted)
        self.addCleanup(host.close)
        self.assertEqual(tuple(host.seats), ("lily",))
        self.assertEqual(host.outside_relay, LOCAL)
        with self.assertRaises(ValueError):
            Host(data, engine, root / "run2", "Canyon_T", None, False, external=object(), hosted=hosted)


if __name__ == "__main__":
    unittest.main()
