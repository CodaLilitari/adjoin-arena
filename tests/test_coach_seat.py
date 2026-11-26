"""PR4 coach and coach-seat regressions. Wren (AI collaborator, via Grok Bot)."""
import json
import tempfile
import unittest
from pathlib import Path

from bots import coach as C
from bots import coach_seat as S


class FakeHub:
    """Companion hub double. `statuses` decides each sent command's outcome."""
    def __init__(self, statuses=None):
        self.statuses = list(statuses or [])
        self.kills = self.deaths = 0
        self.sent, self.attaches, self.releases = [], 0, 0
        self.life = 1
        self.results = {}

    def request(self, cred, route, body=None):
        if route == "observation":
            return {"run_id": "r", "world_epoch": 1, "life_epoch": self.life, "native_active": True,
                    "state": {"kills": self.kills, "deaths": self.deaths, "health": 100}}
        if route == "attach":
            self.attaches += 1
            return {"lease_id": "L%d" % self.attaches}
        if route == "renew":
            return {}
        if route == "release":
            self.releases += 1
            return {}
        if route in ("tactics", "strategy", "say"):
            self.sent.append((route, {k: v for k, v in body.items()
                                      if k not in ("run_id", "world_epoch", "life_epoch", "lease_id", "request_id")}))
            status = self.statuses.pop(0) if self.statuses else "applied"
            self.results[body["request_id"]] = status
            return {"status": "pending"}
        if route.startswith("commands/"):
            status = self.results[route[9:]]
            # "lost" models a command whose acknowledgement never arrives in time.
            return {"status": "expired" if status == "lost" else status}
        raise AssertionError(route)


def run_session(statuses, seconds=200):
    hub = FakeHub(["applied"] + statuses * 50)
    clock = {"t": 0.0}
    def sleep(dt):
        clock["t"] += dt
        if clock["t"] >= 100:
            hub.kills = 2   # evidence after the first dwell
    coach = C.Coach(C.Bandit(["default", "hunter"]), dwell_seconds=90.0)
    C.session({}, coach, seconds=seconds, poll=5.0, clock=lambda: clock["t"], sleep=sleep,
              request=hub.request, log=lambda *_: None)
    return coach, hub


class CoachWindow(unittest.TestCase):
    def test_refused_or_lost_command_grades_window_once(self):
        for status in ("rejected", "rate_limited", "expired", "lost"):
            with self.subTest(status=status):
                coach, hub = run_session([status])
                self.assertEqual(sum(coach.bandit.plays.values()), 1, (status, coach.bandit.plays, hub.sent))

    def test_applied_commands_still_rotate(self):
        coach, hub = run_session(["applied"], seconds=400)
        self.assertGreaterEqual(sum(coach.bandit.plays.values()), 2)


class CoachMemory(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory(); self.addCleanup(d.cleanup)
        self.path = Path(d.name) / "coach.json"

    def test_builds_are_not_mixed(self):
        C.save_memory(self.path, "oasis", {"hunter": {"plays": 3, "total": 2.0}}, "sha256:aaaa")
        self.assertEqual(C.load_memory(self.path, "oasis", "sha256:aaaa")["hunter"]["plays"], 3)
        self.assertEqual(C.load_memory(self.path, "oasis", "sha256:bbbb"), {})
        C.save_memory(self.path, "oasis", {"dry": {"plays": 1, "total": 0.5}}, "sha256:bbbb")
        stored = json.loads(self.path.read_text())
        self.assertEqual(stored["oasis"]["build"], "sha256:bbbb")
        self.assertEqual(stored["oasis@sha256:aaaa"]["arms"]["hunter"]["plays"], 3)

    def test_return_to_earlier_build_restores_latest_snapshot(self):
        for build, plays in (("A", 1), ("B", 8), ("A", 3), ("C", 9)):
            C.save_memory(self.path, "arena", {"hunter": {"plays": plays}}, build)
        self.assertEqual(C.load_memory(self.path, "arena", "A")["hunter"]["plays"], 3)
        self.assertEqual(C.load_memory(self.path, "arena", "B")["hunter"]["plays"], 8)

    def test_pr3_format_is_read_as_unrecorded(self):
        self.path.write_text(json.dumps({"oasis": {"hunter": {"plays": 2, "total": 1.0}}}))
        self.assertEqual(C.load_memory(self.path, "oasis")["hunter"]["plays"], 2)
        self.assertEqual(C.load_memory(self.path, "oasis", C.UNRECORDED)["hunter"]["plays"], 2)
        self.assertEqual(C.load_memory(self.path, "oasis", "sha256:cccc"), {})

    def test_build_id_hashes_engine(self):
        engine = self.path.with_name("openjkdf2.wasm"); engine.write_bytes(b"\0asm")
        self.assertTrue(C.build_id(engine).startswith("sha256:"))
        self.assertEqual(C.build_id(None), C.UNRECORDED)


class Seat(unittest.TestCase):
    def make(self, statuses=None, start="auto", control=None):
        self.hub = FakeHub(statuses)
        self.clock = {"t": 0.0}
        coach = C.Coach(C.Bandit(["default", "hunter"]), dwell_seconds=90.0)
        self.lines = []
        return S.CoachSeat({}, coach, request=self.hub.request, clock=lambda: self.clock["t"],
                           log=self.lines.append, start=start, control=control)

    def ticks(self, seat, n, dt=1.0):
        for _ in range(n):
            seat.tick(); self.clock["t"] += dt

    def test_lilivane_ack_dwell_and_manual_handback(self):
        seat = self.make(statuses=["rejected"], start="lilivane")
        original = self.hub.request
        state = {"weapon": 1, "shields": 40, "health": 100}
        def observe(cred, route, body=None):
            reply = original(cred, route, body)
            if route == "observation":
                reply["state"].update(state)
            return reply
        seat.request = observe
        self.ticks(seat, 4)
        self.assertEqual([v["preset"] for _, v in self.hub.sent], ["arsenal", "arsenal"])
        state["health"] = 10
        self.ticks(seat, 5)
        self.assertEqual(len(self.hub.sent), 2)
        self.clock["t"] += 12
        self.ticks(seat, 2)
        self.assertEqual(self.hub.sent[-1][1]["preset"], "standoff")
        seat.command("preset hunter")
        self.ticks(seat, 2)
        self.assertEqual(seat.mode, "manual")
        seat.command("lilivane")
        self.ticks(seat, 2)
        self.assertEqual(self.hub.sent[-1][1]["preset"], "standoff")
        self.assertEqual(sum(seat.coach.bandit.plays.values()), 0)

    def test_lilivane_does_not_seek_guns_in_saber_match(self):
        from bots.lilivane_policy import Policy
        policy = Policy(weapons="sabers")
        self.assertEqual(policy.choose(1, {"health": 100, "weapon": 1, "shields": 30}), "default")

    def test_auto_applies_coach_preset_with_reset(self):
        seat = self.make()
        self.ticks(seat, 3)
        self.assertEqual(self.hub.sent[0], ("tactics", {"preset": "default", "reset": True}))
        self.assertEqual(seat.coach.current, "default")

    def test_takeover_drops_window_and_handback_resumes(self):
        seat = self.make()
        self.ticks(seat, 3)
        self.hub.kills = 5
        seat.command("preset hunter")
        self.ticks(seat, 3)
        self.assertEqual(seat.mode, "manual")
        self.assertEqual(self.hub.sent[-1], ("tactics", {"preset": "hunter", "reset": True}))
        self.assertEqual(seat.manual, "preset hunter")
        self.clock["t"] += 500; self.ticks(seat, 3)
        self.assertEqual(sum(seat.coach.bandit.plays.values()), 0, "manual time is never graded")
        seat.command("auto")
        self.ticks(seat, 3)
        self.assertEqual(seat.mode, "auto")
        self.assertIsNotNone(seat.coach.current)
        self.assertEqual(self.hub.sent[-1][0], "tactics")

    def test_strategy_and_set_and_errors(self):
        seat = self.make(start="manual")
        seat.command("strategy pressure ttl=8 risk=0.7")
        self.ticks(seat, 2)
        self.assertEqual(self.hub.sent[-1], ("strategy", {"mode": "pressure", "ttl_seconds": 8.0, "risk": 0.7}))
        seat.command("set run=0 gun_far=3")
        self.ticks(seat, 2)
        self.assertEqual(self.hub.sent[-1], ("tactics", {"values": {"run": 0.0, "gun_far": 3.0}}))
        n = len(self.hub.sent)
        for bad in ("preset nope", "set nope=1", "set run=7", "strategy fly", "dance"):
            seat.command(bad)
        self.ticks(seat, 2)
        self.assertEqual(len(self.hub.sent), n)
        self.assertTrue(any('"kind": "error"' in l or "error" in l for l in self.lines))

    def test_commands_arriving_together_are_all_sent(self):
        """Live JKWeb run: 'set' then 'strategy' in one batch lost the 'set'."""
        seat = self.make(start="manual")
        seat.command("set run=1")
        seat.command("strategy pressure ttl=8")
        self.ticks(seat, 5)
        self.assertEqual([r for r, _ in self.hub.sent[-2:]], ["tactics", "strategy"])
        self.assertEqual(self.hub.sent[-2][1], {"values": {"run": 1.0}})

    def test_stale_state_keeps_the_lease(self):
        """Live JKZone run: Red's state went stale for a few seconds; the seat
        dropped its own valid lease and was then locked out ('A controller holds
        this bot') until the hub expired it 30 s later."""
        seat = self.make()
        real = self.hub.request
        state = {"stale": False, "held": None}
        def request(cred, route, body=None):
            if route == "attach":
                if state["held"]:
                    raise ValueError("HTTP 409: A controller holds this bot.")
                out = real(cred, route, body); state["held"] = out["lease_id"]; return out
            if route == "renew" and state["stale"]:
                raise ValueError("HTTP 409: Waiting for native state.")
            if route == "renew" and body.get("lease_id") != state["held"]:
                raise ValueError("HTTP 409: Controller lease expired or invalid.")
            return real(cred, route, body)
        seat.request = request
        def step(n):
            for _ in range(n):
                try:
                    seat.tick(); seat.waiting = False
                except ValueError as error:
                    seat.refused(error)
                self.clock["t"] += 1.0
        step(3)
        self.assertEqual(self.hub.attaches, 1)
        state["stale"] = True
        step(5)
        self.assertIsNotNone(seat.lease)
        state["stale"] = False
        step(3)
        self.assertEqual(self.hub.attaches, 1)
        self.assertFalse(any("controller holds" in l for l in self.lines))
        self.assertEqual(sum('Waiting for native state' in l for l in self.lines), 1)

    def test_refused_manual_command_is_reported(self):
        seat = self.make(statuses=["rate_limited"], start="manual")
        seat.command("preset dry")
        self.ticks(seat, 3)
        self.assertIsNone(seat.manual)
        self.assertTrue(any(h["kind"] == "result" and h["status"] == "rate_limited" for h in seat.history))

    def test_new_life_reattaches(self):
        seat = self.make()
        self.ticks(seat, 2)
        self.hub.life = 2
        self.ticks(seat, 2)
        self.assertEqual(self.hub.attaches, 2)

    def test_release_and_quit(self):
        seat = self.make()
        self.ticks(seat, 2)
        seat.command("release")
        self.assertEqual(self.hub.releases, 1)
        self.assertEqual(seat.mode, "released")
        self.ticks(seat, 3)
        self.assertEqual(self.hub.attaches, 1, "a released seat does not take the bot back")
        self.assertFalse(seat.command("quit"))

    def test_control_directory(self):
        d = tempfile.TemporaryDirectory(); self.addCleanup(d.cleanup)
        control = S.ControlFile(Path(d.name))
        seat = self.make(control=control)
        (Path(d.name) / "commands.txt").open("a").write("preset standoff\nstatus\n")
        clock = self.clock
        S.run(seat, seconds=5, poll=1.0, sleep=lambda dt: clock.__setitem__("t", clock["t"] + dt))
        status = json.loads((Path(d.name) / "status.json").read_text())
        self.assertTrue(status["stopped"])
        self.assertEqual(status["manual"], "preset standoff")
        self.assertIn(("tactics", {"preset": "standoff", "reset": True}), self.hub.sent)
        self.assertTrue((Path(d.name) / "log.jsonl").read_text().count("operator") >= 2)


if __name__ == "__main__":
    unittest.main()
