"""Motor-model contracts; synthetic cases here are unit evidence, not gameplay."""
import copy
import importlib.util
import json
import math
from pathlib import Path
import tempfile
import unittest

from bots.lily.motor_model import FEATURES, OUTPUTS, features, predict, validate_model
from bots.lily.train_motor import dataset, fit, split_episodes
from bots.lily.export_motor_policy import policy_source


def sample(goal=None):
    return {"sense": {"position": [0, 0, 0], "velocity": [.1, .2, -.1],
        "facing": [1, 0, 0], "up": [0, 0, 1], "head_pitch": 20,
        "supported": 0, "medium": "water", "breath_used_ms": 5000,
        "tick_ms": 33.333, "axes": [.5, 0, -.2, .4], "buttons": 1,
        "action_seq": 11, "revision": 1, "owner_sample_id": 7},
        "state": {"health": 80, "shields": 70, "mana": 300},
        "goal": goal or {"direction": [1, .5, .25], "distance": .3}}


def constant_model():
    return {"schema": 1, "feature_names": list(FEATURES), "output_names": list(OUTPUTS),
        "normalization": {"mean": [0.] * len(FEATURES), "scale": [1.] * len(FEATURES)},
        "w1": [[0.] * len(FEATURES)], "b1": [0.],
        "w2": [[0.] for _ in OUTPUTS], "b2": [.25, -.5, 0., .75, 2., -2.],
        "provenance": {"fixture": "synthetic unit test"}}


class MotorModelTests(unittest.TestCase):
    def test_relative_features_do_not_depend_on_world_rotation(self):
        a = sample()
        b = copy.deepcopy(a)
        rotate = lambda v: [-v[1], v[0], v[2]]
        for name in ("position", "velocity", "facing", "up"):
            b["sense"][name] = rotate(b["sense"][name])
        b["goal"]["direction"] = rotate(b["goal"]["direction"])
        for x, y in zip(features(**{k:a[k] for k in ("sense", "state", "goal")}),
                        features(**{k:b[k] for k in ("sense", "state", "goal")})):
            self.assertAlmostEqual(x, y)

    def test_nonfinite_and_wrong_contract_models_are_rejected(self):
        bad = constant_model(); bad["w1"][0][0] = float("nan")
        with self.assertRaises(ValueError): validate_model(bad)
        bad = constant_model(); bad["feature_names"].reverse()
        with self.assertRaises(ValueError): validate_model(bad)
        bad = constant_model(); bad["normalization"]["scale"][0] = 0
        with self.assertRaises(ValueError): validate_model(bad)

    def test_inference_is_bounded_and_exported_policy_uses_same_weights(self):
        model = constant_model(); row = sample()
        expected = predict(model, features(row["sense"], row["state"], row["goal"]))
        self.assertAlmostEqual(expected[0], math.tanh(.25))
        scope = {}; exec(compile(policy_source(model), "generated-policy", "exec"), scope)
        observation = {"lily": {"sense": row["sense"]}, "state": row["state"]}
        context = {"undertaking": None, "directive": {"goal": "learned-motor",
            "parameters": {**row["goal"], "duration_ms": 300}}}
        result = scope["decide"](observation, context)
        self.assertEqual(result["action"], "motor")
        for name, value in zip(OUTPUTS[:4], expected[:4]):
            self.assertAlmostEqual(result["steps"][0][name], value)
        self.assertEqual(result["steps"][0]["buttons"], 1)
        self.assertEqual(scope["decide"](observation, {"undertaking": {"action_seq": 3}}), {"action": "wait"})
        self.assertEqual(scope["decide"](observation, {"undertaking": None})["action"], "baseline")

    def test_dataset_excludes_censored_and_unattributed_controls(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "trace.jsonl"
            rows=[]
            for ident, success in (("success", True), ("censored", None), ("failed", False)):
                rows += [{"schema":1,"event":"observation","episode_id":ident,
                    "policy_hash":"p",**sample()},
                    {"schema":1,"event":"outcome","episode_id":ident,
                     "action_seq":11,"physical_success":success,"status":"motor_goal_reached"}]
            rows.insert(1,{"schema":1,"event":"observation","episode_id":"success",
                           "policy_hash":"p",**sample()})
            rows[1]["sense"]["action_seq"] = 12
            path.write_text("\n".join(json.dumps(row) for row in rows))
            loaded = dataset([path])
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0]["episode_id"], "success")
            self.assertEqual(loaded[0]["target"][-2:], [1., 0.])

    def test_holdout_keeps_whole_episodes_separate(self):
        rows = [{"episode_id":str(i//4),"features":[0]*len(FEATURES),"target":[0]*len(OUTPUTS)} for i in range(20)]
        train, held = split_episodes(rows, .4, 17)
        self.assertTrue(train); self.assertTrue(held)
        self.assertFalse({x["episode_id"] for x in train} & {x["episode_id"] for x in held})
        with self.assertRaises(ValueError): split_episodes(rows[:4], .2, 17)

    def test_related_demonstrations_stay_in_one_split(self):
        rows=[{"episode_id":str(i),"split_group":str(i//4)} for i in range(12)]
        train,held=split_episodes(rows,.3,9)
        self.assertFalse({r["split_group"] for r in train}&{r["split_group"] for r in held})
        with self.assertRaises(ValueError):
            split_episodes([*rows,{"episode_id":"0","split_group":"new"}],.3,9)

    @unittest.skipUnless(importlib.util.find_spec("numpy"), "optional training dependency")
    def test_trained_artifact_improves_held_out_action_fit(self):
        rows=[]
        for episode in range(6):
            for index in range(16):
                x = (index-7.5)/7.5
                vector=[0.]*len(FEATURES); vector[0]=x
                rows.append({"episode_id":str(episode),"features":vector,
                             "target":[.6*x,0,0,0,float(x>0),float(x<0)]})
        model, metrics = fit(rows, epochs=80, hidden=8, seed=3)
        validate_model(model)
        self.assertLess(metrics["heldout_axis_mse"], metrics["initial_heldout_axis_mse"])
        self.assertLess(metrics["heldout_axis_mse"], .025)
        self.assertEqual(len(metrics["train_episode_ids"])+len(metrics["heldout_episode_ids"]),6)


if __name__ == "__main__":
    unittest.main()
