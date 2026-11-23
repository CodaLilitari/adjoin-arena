"""Protect the experiment's denominator, immutable inputs, and advancement gates."""
import copy
import hashlib
import importlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from test_lily_outcome_search import row


class MemoryExperimentTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec("scripts.bot_development.analysis.run_memory_learning"),
                             "declared memory protocol is not implemented")
        self.r = importlib.import_module("scripts.bot_development.analysis.run_memory_learning")

    def test_schedule_rehearses_every_anchor_and_covers_all_old_training_once(self):
        ids = [f"train-pool-{i:02d}" for i in range(48)]+[f"train-shaft-{i:02d}" for i in range(16)]
        anchors = [f"development-shaft-{i}" for i in range(8)]
        batches = self.r.schedule(ids,anchors)
        self.assertEqual(len(batches),8)
        rotated = []
        for batch in batches:
            self.assertEqual(batch[:8],anchors)
            self.assertEqual(len(batch),16)
            self.assertEqual(sum("pool" in i for i in batch),6)
            rotated.extend(batch[8:])
        self.assertCountEqual(rotated,ids)
        self.assertEqual(batches,self.r.schedule(ids,anchors))
        self.assertEqual(self.r.execution_budget(False),dict(calibration=144,training=2304,open=160,transfer=0,diagnostics=0,total=2608))
        self.assertEqual(self.r.execution_budget(True)["total"],3030)
        with self.assertRaises(ValueError): self.r.schedule(ids[:-1]+[ids[0]],anchors)

    def test_frozen_file_verifier_detects_bytes_and_indirection(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root/"source.py").write_bytes(b"frozen\n")
            pinned = {"source.py":hashlib.sha256(b"frozen\n").hexdigest()}
            self.r.verify_files(root,pinned)
            (root/"source.py").write_bytes(b"changed\n")
            with self.assertRaisesRegex(ValueError,"frozen"):
                self.r.verify_files(root,pinned)
            (root/"source.py").unlink()
            (root/"outside").write_bytes(b"frozen\n")
            (root/"source.py").symlink_to(root/"outside")
            with self.assertRaises(ValueError): self.r.verify_files(root,pinned)
            with self.assertRaises(ValueError): self.r.verify_files(root,{"../escape":"ab"*32})

    def test_replication_checks_each_start_not_only_totals(self):
        expected = {"a":dict(physical_success=True,physics_steps=50,initial_observation_sha256="x"),
                    "b":dict(physical_success=False,physics_steps=9000,initial_observation_sha256="y")}
        actual = [dict(row("a","supported_dry",50),initial_observation_sha256="x"),
                  dict(row("b","sim_timeout",9000),initial_observation_sha256="y")]
        self.assertEqual(self.r.check_replication(actual,expected),2)
        changed = copy.deepcopy(actual)
        changed[0]["physical_success"],changed[1]["physical_success"] = False,True
        with self.assertRaises(ValueError): self.r.check_replication(changed,expected)
        changed = copy.deepcopy(actual)
        changed[0]["physics_steps"] = 51
        with self.assertRaises(ValueError): self.r.check_replication(changed,expected)

    def test_null_or_substituted_selection_cannot_admit_transfer(self):
        refs = {name:{"artifact":name,"canonical_sha256":name} for name in ("v3","g4","static","recurrent","no_history")}
        with self.assertRaisesRegex(ValueError,"selected"):
            self.r.transfer_arms(dict(selected=None,model=None),refs)
        with self.assertRaisesRegex(ValueError,"selected"):
            self.r.transfer_arms(dict(selected="recurrent",model=refs["static"]),refs)
        arms = self.r.transfer_arms(dict(selected="recurrent",model=refs["recurrent"]),refs)
        self.assertEqual(list(arms),["v3","g4","native","static","recurrent","no_history"])
        self.assertIsNone(arms["native"])

    def test_memory_benefit_needs_both_comparators_and_multiple_positions(self):
        ids = ["p1-yaw0","p1-yaw90","p2-yaw0","p2-yaw90"]
        def rows(winners):
            return [dict(row(e,"supported_dry",50) if e in winners else row(e,"sim_timeout",9000),case=e.split("-yaw")[0],target_sector=10) for e in ids]
        values = {"recurrent":rows(ids),"static":rows([]),"no_history":rows(ids)}
        result = self.r.memory_comparison(values,ids)
        self.assertFalse(result["meets_memory_criterion"])
        values["no_history"] = rows([ids[1],ids[3]])
        result = self.r.memory_comparison(values,ids)
        self.assertTrue(result["meets_memory_criterion"])
        self.assertEqual(result["against_no_history"]["net"],2)
        self.assertEqual(result["against_no_history"]["positions_with_positive_net"],2)

    def test_block_audit_reconstructs_and_rejects_changed_receipt(self):
        from test_lily_memory_rollouts import MemoryRolloutTests
        from scripts.bot_development.analysis import memory_rollouts as trial
        test = MemoryRolloutTests()
        test.setUp()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            a,work,case,policy,model,status = test.fixture(root)
            name = a["candidate_id"]
            artifact = root/"models"/name
            artifact.mkdir(parents=True)
            policy.rename(artifact/"policy.py")
            model.rename(artifact/"model.json")
            ref = dict(artifact=name,**a["model"])
            bank = dict(role="train",sha256="ab"*32,cases={case["case"]:case},jobs={(a["job"]["episode_id"],"every_tick"):a["job"]})
            ids = [a["job"]["episode_id"]]
            binding = {"fixture_source_sha256":a["fixture_source_sha256"]}
            ledger = self.r.old.assignments("calibration",bank,ids,{name:a["model"]},binding)
            directory = root/"calibration"
            directory.mkdir()
            work.rename(directory/ledger[0]["work_dir"])
            work = directory/ledger[0]["work_dir"]
            (work/"assignment.json").write_text(json.dumps(ledger[0]))
            trial.write(directory/"assignments.json",ledger)
            result = trial.audit_attempt(ledger[0],work,case,artifact/"policy.py",artifact/"model.json")
            block = dict(assignments_sha256=trial.motor.digest(directory/"assignments.json"),counts=self.r.old.counts_for([result]),attempts=[result],free_bytes_after=100000)
            trial.write(directory/"block.json",block)
            edges = {10:[result["row"][k] for k in ("seed","origin_sha256","target_position")]}
            _,rows,rebuilt = self.r.audit_block(root,"calibration",bank,ids,{name:ref},binding,edges)
            self.assertFalse(rows[name][0]["physical_success"])
            block["attempts"][0]["row"]["physical_success"] = True
            (directory/"block.json").write_text(json.dumps(block))
            with self.assertRaisesRegex(ValueError,"raw evidence"):
                self.r.audit_block(root,"calibration",bank,ids,{name:ref},binding,edges)

    def test_partial_block_preserves_censor_and_unrun_and_rejects_forged_control(self):
        from test_lily_memory_rollouts import MemoryRolloutTests
        from scripts.bot_development.analysis import memory_rollouts as trial
        test=MemoryRolloutTests()
        test.setUp()
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            a,work,case,policy,model,status=test.fixture(root)
            name=a["candidate_id"]
            artifact=root/"models"/name
            artifact.mkdir(parents=True)
            policy.rename(artifact/"policy.py")
            model.rename(artifact/"model.json")
            ref=dict(artifact=name,**a["model"])
            second=dict(case,case="pool-next")
            job2,=trial.motor.make_jobs([second],["every_tick"],False)
            ids=[a["job"]["episode_id"],job2["episode_id"]]
            bank=dict(role="train",sha256="ab"*32,cases={case["case"]:case,second["case"]:second},
                      jobs={(ids[0],"every_tick"):a["job"],(ids[1],"every_tick"):job2})
            binding={"fixture_source_sha256":a["fixture_source_sha256"]}
            ledger=self.r.old.assignments("calibration",bank,ids,{name:a["model"]},binding)
            directory=root/"blocks"/"calibration"
            directory.mkdir(parents=True)
            work.rename(directory/ledger[0]["work_dir"])
            work=directory/ledger[0]["work_dir"]
            (work/"assignment.json").write_text(json.dumps(ledger[0]))
            trial.write(directory/"assignments.json",ledger)
            (work/"process.json").unlink()
            self.assertTrue(hasattr(self.r,"audit_partial_block"),"partial evidence reconstruction is missing")
            result=self.r.audit_partial_block(root,"calibration",bank,ids,{name:ref},binding,{})
            self.assertEqual(result["counts"],dict(assigned=2,attempted=1,completed=0,wins=0,failed=0,censored=1,invalid=0,unrun=1))
            self.assertEqual([r["status"] for r in result["attempts"]],["censored","unrun"])
            frames=[json.loads(x) for x in (work/"motor.jsonl").read_bytes().splitlines()]
            frames[1]["axes"][0]=.031
            (work/"motor.jsonl").write_text("".join(json.dumps(x)+"\n" for x in frames))
            with self.assertRaises(ValueError):
                self.r.audit_partial_block(root,"calibration",bank,ids,{name:ref},binding,{})


if __name__ == "__main__":
    unittest.main()
