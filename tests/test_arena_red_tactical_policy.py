from dataclasses import replace
import json
from importlib.util import find_spec
from pathlib import Path
import tempfile
import unittest

from scripts.bot_development.analysis import red_tactical_policy as policy


def sample():
    return policy.decision(
        "name=Bot Jan t=1.000 life=2 seq=3 target=7 item=42 f=90,50,423,916,2,10,0,0,4 "
        "teacher=0 selected=0 applied=0 owner=combat model=teacher forward=.5 slide=0 fire1=1 fire2=0",
        "dark")


class RedDecisionTests(unittest.TestCase):
    def test_transfer_uses_native_controls_and_clock_when_unfilmed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/"receipt.json"
            trace = path.parent/"pace-trace.jsonl"
            trace.write_bytes(b"clock fixture")
            moves = {s: {"events": {"BOT_RED_JOIN": {}, "BOT_RED_FIRST": {}},
                         "first_movement_by_life": [{"fwd": 0, "slide": .5}]} for s in policy.SEATS}
            outcome = {"first_seat_move_before_second_join_wall_s": 1, "owners": moves}
            native = {"qualification_errors": [], "owners": {s: {"movement_seen": True} for s in policy.SEATS}}
            record = {"mode_transfer": {"native": native, "content": {"map_sha256": "a"*64}},
                      "red_policy": {"start_and_outcomes": outcome}, "pace_experiment": {
                          "roles": {s: {"observed_rate": 2} for s in ("host", *policy.SEATS)},
                          "requested_game_seconds": 50, "trace_sha256": policy.digest(trace)}}
            match = {"map_sha256": "a"*64, "game_seconds": 50}
            policy.verify_transfer_match(record, match, path)
            moves["light"]["first_movement_by_life"] = []
            with self.assertRaisesRegex(ValueError, "missing native control"):
                policy.verify_transfer_match(record, match, path)

    def test_readback_requires_same_seat_life_and_sequence(self):
        duel = ("BOT_DUEL name=pilot t=1 seq=1 life=1 target=1 item=7 "
                "f=30,30,123,456,2,0,0,0,1 teacher=0 selected=0 applied=0 "
                "owner=engage model=teacher forward=-.35 slide=.1 fire1=1 fire2=0\n")
        read = "BOT_RED_READ name=pilot life=1 seq=1 axis=forward value=-.350000\n"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "example"
            folder.mkdir()
            (folder/"light.log").write_text("no eligible frames")
            path = folder/"dark.log"
            for evidence, expected in ((duel, None), (duel+read, 0)):
                path.write_text(evidence)
                rows, _ = policy.read_match(root, {"name": "example"})
                self.assertEqual(expected, policy.delivered_class(rows[0]))
            path.write_text(duel+read.replace("seq=1", "seq=2"))
            with self.assertRaisesRegex(ValueError, "no matching decision"):
                policy.read_match(root, {"name": "example"})

    def test_weighting_discards_repeat_frames_and_balances_encounters_and_matches(self):
        a = sample()
        b = replace(a, x=(*a.x[:-1], 3), teacher=1)
        late = replace(a, item=30, time=7)
        points = policy.weighted_rows([[a, a, a, b, late], [b]])
        mass = {(x, y): w for x, y, w in points}
        self.assertEqual(.75, mass[a.x, a.teacher])
        self.assertEqual(1.25, mass[b.x, b.teacher])
        self.assertEqual(["dark", 7, True, True], [a.seat, a.target, a.firing, a.moving])

    def test_network_sign_truncation_caps_and_roundtrip(self):
        self.assertEqual(-341, policy.fixed_input(-1, 0, 3))
        self.assertEqual(2048, policy.fixed_input(100000, 0, 1))
        q = policy.Q
        layer = ((0, q, *([0]*8)),) + ((0, *([0]*9)),)*7
        model = policy.Model((0,)*9, (3,)*9, layer, (-q*q//2, q, *([0]*7)))
        self.assertEqual(-q*q//2, model.logit((-1,)*9))
        self.assertEqual(1, model.predict((2,)*9))
        self.assertEqual(model, policy.Model.decode(model.encode()))
        with self.assertRaises(ValueError):
            policy.Model.decode(model.encode().replace(b"RED_NEURAL_V1", b"RED_NEURAL_V0"))

    def test_missing_class_and_empty_set(self):
        a = sample()
        self.assertEqual(None, policy.confusion([], lambda x: 0)["balanced_accuracy"])
        self.assertIsNone(policy.applied_class(replace(a, owner="stationary", moving=False)))
        self.assertEqual(0, policy.applied_class(replace(a, owner="engage")))
        self.assertEqual(1, policy.applied_class(replace(a, owner="supply", applied=1)))
        if find_spec("numpy"):
            with self.assertRaisesRegex(ValueError, "Both native teacher classes"):
                policy.fit([(a.x, 0, 1.)])

    @unittest.skipUnless(find_spec("numpy"), "Training requires NumPy")
    def test_corpus_reconstructs_learned_hidden_and_output_weights(self):
        # A numerical test fixture only. Game evidence always comes from native match logs.
        rows = []
        for i in range(20):
            a = sample()
            rows.append(replace(a, x=(90, 40, i*100, 600, 6, 20, 0, 0, 1),
                                seq=i+1, teacher=int(i >= 10), selected=int(i >= 10)))
        net = policy.fit(policy.weighted_rows([rows]))
        self.assertEqual(20, sum(net.predict(r.x) == r.teacher for r in rows))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            sources = {"example": policy.source_summary(rows, {"dark": "1"*64, "light": "2"*64})}
            corpus = path/"corpus.json.gz"
            policy.write_corpus(corpus, {"example": rows}, sources, "3"*64)
            receipt = {"training_schedule_sha256": "3"*64, "training_matches": ["example"],
                       "corpus_sha256": policy.digest(corpus), "training": sources,
                       "weights_sha256": policy.hashlib.sha256(net.encode()).hexdigest()}
            args = type("Args", (), dict(corpus=corpus, train_receipt=path/"train.json",
                                         model=path/"model.txt"))
            args.train_receipt.write_text(json.dumps(receipt), encoding="utf-8")
            self.assertTrue(policy.rebuild(args)["same_frozen_weights"])
            self.assertEqual(net.encode(), args.model.read_bytes())


if __name__ == "__main__":
    unittest.main()
