import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from bots.tactical_registry import resolve
from scripts.bot_development.analysis.qualify_red_policies import add_study


class TacticalRegistryTests(unittest.TestCase):
    def test_exact_rules_content_and_model_hash_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            weights = folder/"candidate.weights"
            weights.write_bytes(b"test artifact")
            config = dict(mode="tdm", combat="guns", force=False, map_sha256="a"*64)
            cell = dict(config, status="qualified_imitation", model=weights.name,
                        weights_sha256=hashlib.sha256(weights.read_bytes()).hexdigest())
            file = folder/"registry.json"
            file.write_text(json.dumps({"schema": 1, "cells": [cell]}))
            self.assertEqual("learned", resolve(file, **config)["controller"])
            for changed in ({"mode": "ctf"}, {"combat": "saber"}, {"force": True}, {"map_sha256": "b"*64}):
                self.assertEqual("teacher", resolve(file, **(config | changed))["controller"])
            weights.write_bytes(b"replaced")
            self.assertEqual("weight_hash_mismatch", resolve(file, **config)["reason"])
            file.write_text(json.dumps({"schema": 1, "cells": [cell, cell]}))
            self.assertEqual("ambiguous_registry_cell", resolve(file, **config)["reason"])
            file.write_text(json.dumps({"schema": 1, "cells": [1]}))
            self.assertEqual("invalid_registry_cells", resolve(file, **config)["reason"])

    def test_evidence_for_each_delivered_action_and_same_rules(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            weights = root/"candidate.weights"
            weights.write_bytes(b"test candidate")
            digest = hashlib.sha256(weights.read_bytes()).hexdigest()
            train, evaluation = root/"training.json", root/"heldout.json"
            scope = "tdm/guns/force"
            train.write_text(json.dumps(dict(weights_sha256=digest, training_schedule_sha256="a",
                                             rules_scope=scope, training_matches=["fit"])))
            base = dict(map="m10.jkl", map_sha256="a"*64)
            test = dict(weights_sha256=digest, schedule_sha256="a", rules_scope=scope,
                        matches={"control": dict(base, controller="teacher"),
                                 "candidate": dict(base, controller="model", model_selected_with_engine_read=[0, 11])},
                        offline_by_map={"m10.jkl": {"candidate": {"balanced_accuracy": .9},
                                                   "training_majority": {"balanced_accuracy": .5}}})
            def status():
                evaluation.write_text(json.dumps(test))
                cells = {}
                add_study(cells, root, scope, train, evaluation, weights)
                return next(iter(cells.values()))["status"]
            self.assertEqual("missing_live_model_movement_class", status())
            test["matches"]["candidate"]["model_selected_with_engine_read"] = [5, 11]
            self.assertEqual("qualified_imitation", status())
            test["offline_by_map"]["m10.jkl"]["candidate"]["balanced_accuracy"] = .5
            self.assertEqual("heldout_imitation_did_not_beat_majority", status())
            test["rules_scope"] = "tdm/guns/noforce"
            with self.assertRaisesRegex(ValueError, "different rules"):
                status()
