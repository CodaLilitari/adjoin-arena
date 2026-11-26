import unittest
from types import SimpleNamespace

from bots.jhs_roof import RoofLift, VERIFIED


class RoofTests(unittest.TestCase):
    def setUp(self):
        episode, level = next(iter(VERIFIED))
        self.room = dict(episode_sha256=episode, map_sha256=level, seat="lily", map="jhs.jkl")
        self.roof = RoofLift(self.room)
        self.log, self.sent = [], []
        self.seat = SimpleNamespace(mode="auto", lease={}, cred={}, say=lambda name, **kw: self.log.append((name, kw)),
                                    request=lambda cred, kind, body: self.sent.append((kind, body)))

    def step(self, sample, *, sector=79, clock=0, world=1, target=None, owner="baseline", seq=0, pos=None):
        pos = pos or ([.2, -3.023, 2.82] if sector != 0 else [.54, -3.02, 4.665])
        sense = dict(sample_id=sample, self={"sector": sector, "health": 100}, owner=owner, phase="running",
                     action_seq=seq, position=pos, velocity=[0, 0, 0], facing=[1, 0, 0], head_pitch=0, supported=True)
        observation = dict(run_id="room", world_epoch=world, life_epoch=1, native_active=True,
                           lily={"sense": sense, "age_seconds": {"sense": .05}},
                           state=dict(game_time=clock, target=target))
        self.roof.update(self.seat, observation, clock)

    def test_exact_episode_and_level(self):
        for key in ("episode_sha256", "map_sha256", "seat", "map"):
            with self.assertRaises(ValueError):
                RoofLift(dict(self.room, **{key: "other"}))
        self.step(1, world=2)
        self.assertEqual(self.sent, [])

    def test_joining_owner_requires_the_same_verified_hosted_room(self):
        metadata = dict(self.room, relay="ws://127.0.0.1:8123/relay", episode="jhs")
        host = dict(hosted=dict(metadata, seat="red"), room_id=6)
        owner = dict(adaptive_lily=True, external=dict(metadata, id=6))
        self.assertEqual(RoofLift.from_session(host, owner).identity, "original")
        owner["external"]["id"] = 9
        with self.assertRaises(ValueError):
            RoofLift.from_session(host, owner)

    def test_one_successor_per_motor_and_roof_handoff(self):
        self.step(1)
        self.step(2, clock=.1, owner="motor", seq=1)
        self.step(3, clock=.2, owner="motor", seq=1)
        self.assertEqual(len(self.sent), 2)
        self.step(4, clock=.3, sector=0, owner="motor", seq=2)
        self.step(5, clock=.4, sector=0, owner="motor", seq=2)
        self.assertEqual(self.log[-1][1]["reason"], "supported_roof")
        self.step(6, clock=32)
        self.assertEqual(len(self.sent), 3)

    def test_combat_manual_and_retry_limit(self):
        self.step(1)
        self.step(2, clock=.1, target=dict(position=[.2, -3.4, 2.8], age=.1))
        self.assertEqual(self.log[-1][1]["reason"], "combat")
        self.step(3, clock=5)
        self.assertEqual(len(self.sent), 1)
        self.step(4, clock=21)
        self.seat.mode = "manual"
        self.step(5, clock=22)
        self.assertEqual(self.log[-1][1]["reason"], "handoff")
        self.seat.mode = "auto"
        self.step(6, clock=65)
        self.assertEqual(len(self.sent), 2)

    def test_departure_and_time_budget(self):
        self.step(1, sector=5)
        self.assertEqual(self.sent, [])
        self.step(2)
        self.step(3, clock=31)
        self.assertEqual(self.log[-1][1]["reason"], "timeout_or_departure")

    def test_shuttle_exit_clears_both_lips(self):
        sense = dict(position=[-.63, -4.44, 4.52], facing=[0, 1, 0], velocity=[0, 0, 0],
                     supported=True, self={"sector": 16})
        self.assertEqual(self.roof.shuttle_step(sense)["buttons"], 1)
        sense.update(position=[-.63, -4.01, 4.54], self={"sector": 19})
        self.assertEqual(self.roof.shuttle_step(sense)["buttons"], 1)
        sense["supported"] = False
        self.assertEqual(self.roof.shuttle_step(sense)["buttons"], 0)

    def test_default_lilivane_only_exits_a_previously_observed_ride(self):
        self.roof = RoofLift(self.room, opportunistic=True)
        self.seat.mode = "lilivane"
        self.step(1, sector=5, pos=[-.59, -12.44, .12])
        self.step(2)
        self.step(3, sector=16, pos=[-.63, -4.45, 4.515])
        self.assertFalse(self.sent)
        self.step(4, sector=16, pos=[-.63, -5.83, 3.1])
        self.step(5, sector=16, pos=[-.63, -4.45, 4.515])
        self.assertTrue(self.sent)
