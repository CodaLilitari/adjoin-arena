import os
from pathlib import Path
import tempfile
import time
import unittest

from bots.lily.memory import ExperienceStore
from bots.lily.runtime import Supervisor


def policy(turn=1, extra=""):
    return ("ABI_VERSION=1\n" + extra + "\ndef decide(observation,context):\n"
            " return {'action':'motor','skill':'test','steps':[{'duration_ms':200,'turn':"
            + str(turn) + "}]}\n")


def observation():
    return {"run_id": "test", "world_epoch": 1, "life_epoch": 1, "native_active": True,
            "state": {"health": 100, "shields": 20, "ammo": {}}, "lily": {
                "age_seconds": {"sense": 0, "offers": 0, "progress": 0}, "offers": None, "progress": None,
                "sense": {"sample_id": 1, "revision": 0, "action_seq": 0, "owner_sample_id": 0,
                         "owner": "baseline", "phase": "idle", "safe_handover": True,
                         "position": [0, 0, 0], "facing": [0, 1, 0], "medium": "air", "supported": True,
                         "axes": [0] * 4, "buttons": 0, "peers": []}}}


class Link:
    def __init__(self):
        self.actions = []
        self.seq = 0

    def __call__(self, op, body=None):
        if op == "attach":
            return {"lease_id": "only-owner", "expires_in": 30}
        if op == "renew":
            return {"expires_in": 30}
        if op.startswith("commands/"):
            return {"status": "applied"}
        self.seq += 1
        self.actions.append((op, body))
        return {"status": "applied", "action_seq": self.seq}


class SupervisorTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.policy = Path(temp.name) / "policy.py"
        self.policy.write_text(policy())
        self.memory = ExperienceStore(Path(temp.name) / "db")
        self.addCleanup(self.memory.close)
        self.link = Link()
        self.obs = observation()
        self.log = []
        self.sup = Supervisor(self.policy, self.memory, "level", self.link, trace=self.log.append,
                              startup_timeout=1, decision_timeout=.20, stage_interval=.01)
        self.addCleanup(self.sup.close)

    def until(self, predicate, limit=3):
        end = time.monotonic() + limit
        while time.monotonic() < end:
            self.obs["lily"]["sense"]["sample_id"] += 1
            self.sup.step(self.obs)
            if predicate():
                return
            time.sleep(.007)
        self.fail(str([r["event"] for r in self.log][-18:]))

    def motors(self):
        return [body for kind, body in self.link.actions if kind == "motor"]

    def start(self):
        self.until(lambda:len(self.motors()) == 1)
        self.original = self.sup.active.digest

    def finish(self):
        sense = self.obs["lily"]["sense"]
        cmd = self.motors()[-1]
        self.obs["lily"]["progress"] = dict(action_seq=self.link.seq, revision=cmd["revision"],
            sample_id=cmd["sample_id"], owner="motor", phase="completed", reason="none", outcome="playback",
            applied_ms=202, node=-1)
        sense["sample_id"] += 1

    def test_equal_length_hot_swap_at_physical_boundary(self):
        self.start()
        stat = self.policy.stat()
        self.policy.write_text(policy(0))
        os.utime(self.policy, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        self.until(lambda:any(r["event"] == "candidate_ready" and r["policy_hash"] != self.original for r in self.log))
        self.assertEqual(self.original, self.sup.active.digest)
        self.obs["lily"]["sense"]["safe_handover"] = False
        self.finish()
        self.until(lambda:any(r["event"] == "outcome" for r in self.log))
        self.assertEqual(self.original, self.sup.active.digest)
        self.obs["lily"]["sense"]["safe_handover"] = True
        self.until(lambda:len(self.motors()) == 2)
        self.assertEqual(self.motors()[-1]["steps"][0]["turn"], 0)
        self.assertNotEqual(self.original, self.sup.active.digest)

    def test_bad_candidate_keeps_live_controller(self):
        self.start()
        for source in (policy(extra="import time; time.sleep(20)"),
                       "ABI_VERSION=1\ndef decide(o,c):\n while True: pass",
                       "ABI_VERSION=1\ndef decide(o,c): return {'action':'wait','state':{'x':float('nan')}}",
                       "ABI_VERSION=1\ndef decide(o,c): return {'action':'motor','skill':'x','steps':[]}",
                       "raise RuntimeError('unusable')"):
            count = sum(r["event"] == "rejected" for r in self.log)
            self.policy.write_text(source)
            self.until(lambda:sum(r["event"] == "rejected" for r in self.log) > count)
            self.assertEqual(self.original, self.sup.active.digest)
            self.finish()
            n = len(self.motors())
            self.until(lambda:len(self.motors()) > n)
        self.assertTrue(all(x["steps"][0]["turn"] == 1 for x in self.motors()))

    def test_worker_death_and_stale_fence(self):
        self.start()
        self.sup.active.process.kill()
        self.until(lambda:any(r["event"] == "fallback" for r in self.log))
        self.assertTrue(any(k == "release" for k, _ in self.link.actions))
        self.assertIsNone(next(r["physical_success"] for r in self.log if r["event"] == "outcome"))
        self.obs["life_epoch"] = 2
        self.obs["native_active"] = False
        self.until(lambda:self.sup.undertaking is None)
        self.assertEqual(len(self.motors()), 1)

    def test_active_keeps_playing_during_hung_import(self):
        self.start()
        self.policy.write_text(policy(extra="import time; time.sleep(30)"))
        self.until(lambda:self.sup.candidate is not None)
        self.finish()
        self.until(lambda:len(self.motors()) == 2)
        self.assertTrue(self.sup.candidate and self.sup.candidate.process.poll() is None)
        self.assertEqual(self.sup.active.digest, self.original)

    def test_roll_back_to_known_good_after_active_crash(self):
        self.start()
        self.policy.write_text(policy(0))
        self.until(lambda:self.sup.candidate_ready)
        self.finish()
        self.until(lambda:len(self.motors()) == 2)
        self.sup.active.process.kill()
        self.until(lambda:any(r["event"] == "fallback" for r in self.log))
        self.obs["lily"]["sense"]["sample_id"] += 1
        self.until(lambda:len(self.motors()) == 3)
        self.assertEqual(self.original, self.sup.active.digest)
        self.assertEqual(self.motors()[-1]["steps"][0]["turn"], 1)

    def test_directive_renewal_preserves_action_fence_change_censors(self):
        import json
        directive = dict(id="order-one", goal="motor", provenance="operator", parameters={"skill": "sidestep"},
                       run_id="test", world_epoch=1, life_epoch=1, expires_at=time.time() + 20)
        self.sup.directive_file = self.policy.with_suffix(".json")
        self.sup.directive_file.write_text(json.dumps(directive))
        self.start()
        episode = self.sup.undertaking["episode_id"]
        directive["expires_at"] += 40
        self.sup.directive_file.write_text(json.dumps(directive))
        self.sup.step(self.obs)
        self.assertEqual(episode, self.sup.undertaking["episode_id"])
        self.assertEqual(1, len(self.motors()))
        self.obs["life_epoch"] += 1
        self.obs["native_active"] = False
        self.sup.step(self.obs)
        self.assertIsNone(self.sup.directive)
        self.assertIsNone(self.sup.undertaking)
        terminal = next(r for r in self.log if r["event"] == "outcome")
        self.assertIsNone(terminal["physical_success"])
        self.assertEqual((terminal["life_epoch"], terminal["status"]), (1, "fence_changed"))

    def test_only_matching_applied_pose_displacement_counts(self):
        source = policy().replace("'skill':'test'", "'skill':'test','goal':{'distance':.1,'direction':[1,0,0]}")
        self.policy.write_text(source)
        self.start()
        sense = self.obs["lily"]["sense"]
        cmd = self.motors()[0]
        sense.update(sample_id=2, action_seq=99, revision=cmd["revision"], owner_sample_id=cmd["sample_id"],
                     owner="motor", phase="running", safe_handover=False, position=[10, 0, 0])
        self.sup.step(self.obs)
        sense.update(sample_id=3, action_seq=1, position=[20, 0, 0])
        self.sup.step(self.obs)
        self.assertEqual(self.sup.undertaking["max_projection"], 0)
        sense.update(sample_id=4, position=[20.3, 0, 0])
        self.sup.step(self.obs)
        self.finish()
        terminal = self.obs["lily"]["progress"]
        self.obs["lily"]["terminals"] = [terminal]
        self.obs["lily"]["progress"] = dict(terminal, action_seq=99, phase="running", outcome="none")
        self.sup.step(self.obs)
        self.sup.step(self.obs)
        outcomes = [r for r in self.log if r["event"] == "outcome"]
        self.assertEqual([(r["physical_success"], r["status"]) for r in outcomes], [(True, "motor_goal_reached")])
        self.assertEqual(1, self.memory.estimate(next(r["key"] for r in self.log if r["event"] == "attempt"))["wins"])


class LocalCompanionTest(unittest.TestCase):
    def test_fenced_native_receipt_and_persistent_policy_choice_across_runs(self):
        """Real HTTP auth, codec, pipes and sqlite. Native progress is a synthetic fixture."""
        import json
        import struct
        from bots import companion
        from bots.companion_cli import call
        from bots.lily import protocol
        from bots.lily.policies import adaptive

        def run(tmp, tag, nodes, learn):
            directory = tmp / tag
            directory.mkdir()
            hub = companion.Hub(directory, ["lily"], 0, experimental_ids=["lily"])
            sock = hub.take_socket("lily")
            credential = json.loads((hub.directory / "lily.json").read_text())
            db = ExperienceStore(tmp / "persistent.db")
            log = []
            supervisor = Supervisor(Path(adaptive.__file__), db, "one-level", lambda r, b=None:call(credential, r, b),
                                    trace=log.append)

            def feed(kind, seq, payload):
                sock.send(companion.frame(kind, 1, 1, seq, payload))
                hub.pump()

            def sense(sid, safe):
                return protocol.SENSE_HEADER.pack(sid, 0, 0, 0, -1, 0, 0, safe, 1, 0,
                    0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 16, 0, 0, 0, 0, 0, 0, 0, 0)

            try:
                stock = bytearray(144)
                struct.pack_into("<4I", stock, 0, 1, 42, 14, 88)
                struct.pack_into("<iII", stock, 60, -1, 4, 0xffffffff)
                feed(companion.STATE, 1, stock)
                feed(protocol.SENSE, 2, sense(73, 1))
                offers = protocol.OFFERS_HEADER.pack(73, 12, 2)
                for idx, node in enumerate(nodes):
                    offers += protocol.CHOICE.pack(node, 3, 0, 0, 1 + 3 * idx, 2, 0, 1, 1 + .1 * idx)
                feed(protocol.OFFERS, 3, offers)
                end = time.monotonic() + 2.
                packet = None
                while time.monotonic() < end:
                    supervisor.step(call(credential, "observation"))
                    hub.pump()
                    try:
                        packet = sock.recv(513)
                        break
                    except BlockingIOError:
                        time.sleep(.005)
                self.assertIsNotNone(packet)
                _, _, kind, _, _, _, seq = companion.HEADER.unpack_from(packet)
                self.assertEqual(kind, protocol.COMMIT)
                _, sample, revision, offer, node = protocol.COMMIT_HEADER.unpack_from(packet, companion.HEADER.size)
                self.assertEqual((sample, offer), (73, 12))
                if learn:
                    feed(companion.ACK, seq, struct.pack("<BBH", 0, kind, 0))
                    feed(protocol.SENSE, 4, sense(74, 0))
                    progress = protocol.ACTION.pack(seq, revision, sample, 1, 6, 5, 0, 410, node)
                    feed(protocol.PROGRESS, 5, progress)
                    supervisor.step(call(credential, "observation"))
                    feed(protocol.PROGRESS, 6, progress)
                    supervisor.step(call(credential, "observation"))
                    self.assertEqual([row["physical_success"] for row in log if row["event"] == "outcome"], [False])
                return node
            finally:
                supervisor.close()
                db.close()
                sock.close()
                hub.close()
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(run(Path(tmp), "first", (10, 20), True), 20)
            self.assertEqual(run(Path(tmp), "second", (123, 234), False), 123)
