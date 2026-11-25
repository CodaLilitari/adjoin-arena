"""Resolve a tested native policy for an exact game ruleset and level digest."""
import hashlib
import json
from pathlib import Path
import re


def resolve(registry_path, *, mode, combat, force, map_sha256):
    """Return a learned model or the local native controller and the reason."""
    map_sha256 = str(map_sha256).lower()
    mode = str(mode).lower()
    combat = str(combat).lower()
    combat = "sabers" if combat == "saber" else combat
    key = {"mode": mode, "combat": combat, "force": force, "map_sha256": map_sha256}

    def teacher(reason):
        return {"controller": "teacher", "reason": reason, "path": None,
                "sha256": None, "cell": key}

    if mode not in ("ffa", "tdm", "ctf") or combat not in ("guns", "sabers") or type(force) is not bool:
        return teacher("unknown_rules")
    if not re.fullmatch(r"[0-9a-f]{64}", map_sha256):
        return teacher("unknown_map_digest")
    # v1 only learns a legal armed pickup-vs-opponent action. Other skills
    # register separate decision contracts when training and control exist.
    if mode == "ctf" or combat == "sabers":
        return teacher("v1_gear_task_outside_objective_or_saber_contract")
    try:
        path = Path(registry_path).resolve(strict=True)
        registry = json.loads(path.read_bytes())
        if registry["schema"] != 1:
            return teacher("unknown_registry_schema")
        if not isinstance(registry["cells"], list) or any(not isinstance(c, dict) for c in registry["cells"]):
            return teacher("invalid_registry_cells")
        matches = [c for c in registry["cells"] if all(c.get(k) == v for k, v in key.items())]
        if not matches:
            return teacher("no_evidence_for_exact_rules_and_map")
        if len(matches) != 1:
            return teacher("ambiguous_registry_cell")
        entry = matches[0]
        if entry["status"] != "qualified_imitation":
            return teacher(entry["status"])
        weight_file = (path.parent / entry["model"]).resolve(strict=True)
        if not weight_file.is_relative_to(path.parent):
            return teacher("weights_outside_registry")
        sha = hashlib.sha256(weight_file.read_bytes()).hexdigest()
        if sha != entry["weights_sha256"]:
            return teacher("weight_hash_mismatch")
        return {"controller": "learned", "reason": "qualified_imitation",
                "path": str(weight_file), "sha256": sha, "cell": key}
    except (OSError, ValueError, KeyError, TypeError):
        return teacher("unavailable_registry_or_weights")
