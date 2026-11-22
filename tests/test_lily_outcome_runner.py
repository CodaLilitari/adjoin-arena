"""The outcome ledger controls dispatch, batch coverage and the sealed gate."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from scripts.bot_development.analysis import run_outcome_learning as run


class RunnerTests(unittest.TestCase):
    def test_single_declared_output_and_stage_claim(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            with self.assertRaises(ValueError):
                run.canonical_output("lily-outcome-learning-20261122-01", p)
            run.claim(p/"train")
            with self.assertRaises(FileExistsError):
                run.claim(p/"train")

    def test_wrong_case_role_and_digest_rejected(self):
        good = {"path":"native/tests/stock_water_replay/bank_cases.tsv"}
        with self.assertRaisesRegex(ValueError, "role"):
            run.load_bank("stress", good)
        with self.assertRaisesRegex(ValueError, "identity"):
            run.load_bank("original", dict(good, sha256="0"*64))

    def test_one_censor_stops_dispatch_and_counts_every_assignment(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/"block"
            assignments = [{"work_dir":str(i)} for i in range(6)]
            seen = []
            def attempt(a, work):
                self.assertTrue((work/"assignment.json").is_file())
                seen.append(a["work_dir"])
                return dict(status="censored", row=None)
            with self.assertRaises(run.BlockStopped):
                run.dispatch(path, assignments, 1, attempt)
            self.assertEqual(seen, ["0"])
            block = run.read(path/"block.json")
            self.assertEqual(block["counts"], dict(assigned=6, attempted=1, completed=0, wins=0,
                                                  failed=0, censored=1, invalid=0, unrun=5))
            self.assertEqual([a["status"] for a in block["attempts"]], ["censored"]+["unrun"]*5)
            with self.assertRaises(FileExistsError):
                run.dispatch(path, assignments, 1, attempt)
            self.assertEqual(seen, ["0"])

    def test_all_13_candidate_banks_have_identical_order_and_case_job(self):
        spec = {"path":"native/tests/stock_water_replay/bank_cases.tsv"}
        spec["sha256"] = run.motor.digest(run.ROOT/spec["path"])
        import csv
        with (run.ROOT/spec["path"]).open() as f:
            rows = list(csv.DictReader(f, delimiter="\t"))
        spec["episode_ids"] = [j["episode_id"] for j in run.motor.make_jobs(rows, ["every_tick"], True)]
        bank = run.load_bank("original", spec)
        names = [f"g01-c{i:02d}" for i in range(13)]
        ids = spec["episode_ids"][2:10]
        assignments = run.assignments("g01", bank, ids, dict.fromkeys(names, {"model_sha256":"fixed"}), {})
        self.assertEqual([(a["candidate_id"],a["job"]["episode_id"]) for a in assignments],
                         [(n,i) for n in names for i in ids])
        self.assertEqual(len({a["work_dir"] for a in assignments}), 104)

    def test_no_selection_cannot_open_evaluation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            freeze = dict(selected=None, model=None)
            opener = Mock(side_effect=AssertionError("opened held-out bank"))
            with self.assertRaisesRegex(ValueError, "selected"):
                run.evaluate_blocks(root, {}, {}, freeze, opener)
            opener.assert_not_called()
            self.assertFalse((root/"evaluate").exists())

    def test_training_stops_on_first_incomplete_generation_and_keeps_exact_parent_bytes(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            run.claim(output/"models")
            run.claim(output/"train")
            parent = run.ROOT/run.PARENT["model"]
            binding = dict(run_sha256="a"*64, declaration_sha256="b"*64)
            bank = {"ids": ["e"+str(i) for i in range(8)]}
            seen = []
            def interrupted(o, stage, label, b, ids, refs, bind, edges, workers):
                seen.append(label)
                self.assertEqual(list(refs), [f"g01-c{i:02d}" for i in range(13)])
                self.assertEqual((o/"models/g01-c00/model.json").read_bytes(), parent.read_bytes())
                self.assertEqual(ids, bank["ids"])
                self.assertEqual(bind["predecessor_sha256"], binding["run_sha256"])
                raise run.BlockStopped("one genuine censor")
            with patch.object(run,"run_block",interrupted), self.assertRaises(run.BlockStopped):
                run.train_generations(output, {"training_batches":[bank["ids"]]*8}, {"train":bank}, binding, {}, 1)
            self.assertEqual(seen, ["g01"])
            self.assertFalse((output/"training.json").exists())
            self.assertFalse((output/"models/g02-c00").exists())

    def test_inflight_sibling_is_preserved_and_unstarted_tail_stays_unrun(self):
        import threading
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/"test"
            both = threading.Barrier(2)
            ledger = [dict(work_dir=str(i)) for i in range(4)]
            def attempt(a, work):
                both.wait(5)
                if a["work_dir"]=="0":
                    return dict(status="censored",row=None)
                import time
                time.sleep(.08)
                return dict(status="complete",row=dict(physical_success=True))
            with self.assertRaises(run.BlockStopped):
                run.dispatch(path, ledger, 2, attempt)
            block = run.read(path/"block.json")
            self.assertEqual([a["status"] for a in block["attempts"]],["censored","complete","unrun","unrun"])
            self.assertEqual((block["counts"]["assigned"],block["counts"]["attempted"],block["counts"]["wins"]),(4,2,1))

    def test_measured_development_freeze_precedes_sealed_then_three_diagnostic_pairs(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            run.write(out/"training.json",{})
            ids = [f"i{i}" for i in range(32)]
            bank = dict(ids=ids, jobs={(i,"every_tick"):dict(target_sector=10 if n<24 else 41) for n,i in enumerate(ids)})
            checkpoints = {k:dict(artifact=k) for k in ("v3","g4","g8")}
            binding = dict(run_sha256="a"*64,declaration_sha256="b"*64)
            blocks = []
            def dev(o,stage,label,b,actual_ids,refs,bind,edges,workers):
                self.assertEqual(actual_ids, ids)
                self.assertEqual(list(refs), ["v3","g4","g8"])
                def row(i, win):
                    return dict(episode_id=i,owner="model",controller="every_tick",ownership_complete=True,
                                baseline_assisted=False,physical_success=win,physics_steps=46,
                                terminal="supported_dry" if win else "died")
                return {}, {k:[row(i,n>=24 or (k=="g4" and n==0)) for n,i in enumerate(ids)] for k in refs}
            with patch.object(run,"run_block",dev):
                freeze = run.development(out,bank,binding,{},checkpoints,1)
            self.assertEqual(freeze["selected"],"g4")
            frozen = run.motor.digest(out/"freeze.json")
            def opened(o,stage,label,b,ids,refs,bind,edges,workers):
                self.assertEqual(run.read(o/"freeze.json")["model"], checkpoints["g4"])
                self.assertEqual(bind["predecessor_sha256"], blocks[-1][2] if blocks else frozen)
                blocks.append((label,list(refs),label+"-digest"))
                return dict(sha256=blocks[-1][2]), {}
            run.evaluate_blocks(out, {b:bank for b in ("sealed",*run.DIAGNOSTIC)},
                                dict(binding=binding,edges={},winners=[],workers=1),freeze,opened)
            self.assertEqual([x[:2] for x in blocks], [("sealed",["v3","selected","native"]),
                             *((k,["v3","selected"]) for k in run.DIAGNOSTIC)])
