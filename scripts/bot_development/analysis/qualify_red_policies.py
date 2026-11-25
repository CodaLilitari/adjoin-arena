"""Build a per-ruleset/JKL policy registry from frozen held-out evaluations."""
import argparse
import hashlib
import json
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def key(cell):
    return (cell["mode"], cell["combat"], cell["force"], cell["map_sha256"])


def initial_cells(matrix):
    cells = {}
    for entry in [*matrix["matrix"], *matrix["unseen"]]:
        cell = dict(mode=entry["mode"], combat="sabers" if entry["weapons"] == "saber" else entry["weapons"],
                    force=entry["force"] == "on", map=entry["map"], map_sha256=entry["map_sha256"])
        cell["status"] = ("separate_flag_or_saber_task" if cell["mode"] == "ctf" or cell["combat"] == "sabers"
                          else "no_qualified_gear_model")
        cells[key(cell)] = cell
    return cells


def add_study(cells, root, scope, train_path, evaluation_path, model_path):
    mode, combat, force = scope.split("/")
    if mode not in ("ffa", "tdm") or combat != "guns" or force not in ("force", "noforce"):
        raise ValueError("The v1 gear policy can be qualified only for armed FFA or TDM")
    train = json.loads(train_path.read_bytes())
    evaluation = json.loads(evaluation_path.read_bytes())
    if (sha(model_path) != train["weights_sha256"] or evaluation["weights_sha256"] != train["weights_sha256"]
            or train["training_schedule_sha256"] != evaluation["schedule_sha256"]):
        raise ValueError("Study, weights and held-out source identities differ")
    if train["rules_scope"] != scope or evaluation["rules_scope"] != scope:
        raise ValueError("The study was fitted or evaluated under different rules")
    train_ids = set(train["training_matches"])
    if train_ids.intersection(evaluation["matches"]):
        raise ValueError("Held-out data overlaps fitting")
    model_rel = model_path.resolve().relative_to(root.resolve()).as_posix()
    for basename, offline in evaluation["offline_by_map"].items():
        relevant = {name: item for name, item in evaluation["matches"].items() if item["map"] == basename}
        level_shas = {item["map_sha256"] for item in relevant.values()}
        if len(level_shas) != 1:
            raise ValueError("One map name has multiple content identities")
        cell = dict(mode=mode, combat=combat, force=(force == "force"), map=basename, map_sha256=level_shas.pop())
        k = key(cell)
        if k in cells and "weights_sha256" in cells[k]:
            raise ValueError("Two study candidates for the same registry cell")
        controls = [item for item in relevant.values() if item["controller"] == "teacher"]
        live = [item for item in relevant.values() if item["controller"] == "model"]
        delivered = [sum(item["model_selected_with_engine_read"][y] for item in live) for y in (0, 1)]
        scores = [offline[x]["balanced_accuracy"] for x in ("candidate", "training_majority")]
        if not controls or not live:
            status = "missing_independent_teacher_or_model_match"
        elif None in scores:
            status = "missing_heldout_teacher_class"
        elif min(delivered) == 0:
            status = "missing_live_model_movement_class"
        elif scores[0] <= scores[1]:
            status = "heldout_imitation_did_not_beat_majority"
        else:
            status = "qualified_imitation"
        cell.update(status=status, model=model_rel, weights_sha256=sha(model_path),
                    training_receipt_sha256=sha(train_path), evaluation_sha256=sha(evaluation_path),
                    n_heldout_teacher_matches=len(controls), n_heldout_model_matches=len(live),
                    candidate_balanced_accuracy=scores[0], training_majority_balanced_accuracy=scores[1],
                    model_selected_and_read=delivered, heldout_runs=list(relevant))
        cells[k] = cell


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--matrix", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--study", nargs=4, action="append", metavar=("SCOPE", "TRAIN", "EVAL", "WEIGHTS"),
                   help="May repeat for independently trained variants")
    a = p.parse_args()
    cells = initial_cells(json.loads(a.matrix.read_bytes()))
    for scope, train, evaluation, model in a.study or []:
        add_study(cells, a.out.parent, scope, Path(train), Path(evaluation), Path(model))
    result = {"schema": 1, "task": "native_legal_pickup_versus_engage_movement",
              "capability": "Qualified means held-out imitation above the training majority and actual "
                            "native nonzero movement read for both choices in a frozen-model match on the exact map "
                            "and rules. Competition strength is measured separately.",
              "cells": [cells[k] for k in sorted(cells)]}
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_bytes((json.dumps(result, indent=2)+"\n").encode("utf-8"))


if __name__ == "__main__":
    main()
