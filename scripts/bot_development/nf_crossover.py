"""Audit side-swapped 1x native NF gun games for one frozen pickup/fight candidate."""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path

from scripts.bot_development import competitive_results
from scripts.bot_development.analysis import red_tactical_policy as policy

ORDERS = (("boba_fett", "jan_ors"), ("jan_ors", "boba_fett"))


def require(ok, message):
    if not ok:
        raise ValueError(message)


def audit_match(directory, model, weights_sha, maps, seconds):
    raw = json.loads((directory / "receipt.json").read_bytes())
    entry = competitive_results.summarize(directory)
    if "owners" not in entry:
        return entry
    side = entry["model_side"]
    other = {"dark": "light", "light": "dark"}.get(side)
    require(other and entry["model_sha256"] == weights_sha, "different candidate seat or weights")
    require((entry["mode"], entry["weapons"], entry["force"]) == ("ffa", "guns", "off"), "different rules")
    require(entry["rate"] == 1 and raw["pace_experiment"]["requested_game_seconds"] == seconds, "different clock or duration")
    require(maps.get(entry["map"]) == entry["map_sha256"], "different map or digest")
    require(tuple(entry["seats"]) in ORDERS, "unexpected join order")
    selection = raw["mode_transfer"]["policy_selection"]
    require(selection["controller"] == "learned" and selection["sha256"] == weights_sha, "weights selection mismatch")
    windows = {}
    for role in ("host", side, other):
        clock = raw["pace_experiment"]["roles"][role]
        require(.9 <= clock["observed_rate"] <= 1.1 and clock["first"]["rate"] == clock["last"]["rate"] == 1,
                "role clock outside 1x")
        start = clock["first"]["game_ms"]
        windows[role] = (start, start + 1000 * seconds)
        require(clock["last"]["game_ms"] >= windows[role][1], "incomplete game-clock window")
    for owner in (side, other):
        expected_model = weights_sha if owner == side else "teacher"
        build = raw["red_policy"]["start_and_outcomes"]["owners"][owner]["events"]["BOT_RED_MODEL"]
        require((build["model"], build["status"]) == (expected_model, "ready"), "native model load mismatch")
        ctx = raw["mode_transfer"]["native"]["owners"][owner]["contexts"]
        require(ctx and all(c["scope"] == "ffa/guns/noforce" and c["map_sha"] == entry["map_sha256"]
                            and int(c["scope_match"]) == (owner == side) for c in ctx), "native scope mismatch")
    rows, _ = policy.read_match(directory.parent, {"name": directory.name})
    selected = Counter()
    delivered = Counter()
    candidate = []
    for r in rows:
        lo, hi = windows[r.seat]
        if not lo <= round(1000 * r.time) < hi:
            continue
        require(r.model == (weights_sha if r.seat == side else "teacher"), "wrong active decision owner")
        if r.seat != side:
            continue
        require(r.selected == model.predict(r.x), "recorded label differs from supplied weights")
        candidate.append(r)
        selected[r.selected] += 1
        if policy.delivered_class(r) == r.selected:
            delivered[r.selected] += 1
    # BOT_STATUS is a sampled position, while BOT_RED_READ witnesses a specific
    # movement input. These independent observations answer different questions.
    last_pos = None
    life = None
    moved = 0
    for line in (directory / (side + ".log")).read_text(errors="replace").splitlines():
        if line.startswith("BOT_RED_STATE "):
            f = competitive_results.fields(line)
            identity = f["life"] if f["dead"] == "0" else None
            if identity != life:
                last_pos = None
            life = identity
        elif line.startswith("BOT_STATUS ") and life:
            f = competitive_results.fields(line)
            lo, hi = windows[side]
            if lo <= 1000 * float(f["t"]) < hi:
                pos = tuple(map(float, f["pos"].split(",")))
                if last_pos is not None and math.dist(last_pos, pos) > .001:
                    moved += 1
                last_pos = pos
    def counts(counter):
        return {"engage": counter[0], "pickup": counter[1]}
    return dict(run=entry["run"], receipt_sha256=entry["receipt_sha256"], status=entry["status"],
                map=entry["map"], map_sha256=entry["map_sha256"], seat=side, first=entry["seats"][0],
                candidate=entry["owners"][side], red=entry["owners"][other], decisions=counts(selected),
                delivered_nonzero_axis=counts(delivered), eligible_encounters=len(policy.encounters(candidate)),
                same_life_positions_changed=moved)


def coverage(matches, maps):
    result = {}
    for map_name in maps:
        qualified = [r for r in matches if r.get("map") == map_name and "candidate" in r]
        cells = {}
        for side in ("dark", "light"):
            for order in ORDERS:
                members = [r for r in qualified if (r["seat"], r["first"]) == (side, order[0])]
                cells[f"{side}/{order[0]}-first"] = {
                    "verified_games": len(members),
                    "games_with_consumed_choice_and_observed_motion": sum(
                        bool(sum(r["delivered_nonzero_axis"].values()) and r["same_life_positions_changed"])
                        for r in members)}
        actions = {a: sum(r["delivered_nonzero_axis"][a] for r in qualified) for a in ("engage", "pickup")}
        result[map_name] = dict(cells=cells, missing_cells=[k for k, v in cells.items() if not v["verified_games"]],
                                missing_movement_cells=[k for k, v in cells.items()
                                                        if not v["games_with_consumed_choice_and_observed_motion"]],
                                delivered_actions=actions)
    return result


def audit(directories, weights, expected_sha, maps, seconds):
    data = weights.read_bytes()
    require(hashlib.sha256(data).hexdigest() == expected_sha, "supplied weights digest mismatch")
    model = policy.Model.decode(data)
    results = []
    seen = set()
    seen_logs = set()
    for directory in directories:
        payload = (directory / "receipt.json").read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        require(digest not in seen, "duplicate match receipt: " + str(directory))
        seen.add(digest)
        try:
            result = audit_match(directory, model, expected_sha, maps, seconds)
            if "candidate" in result:
                logs = json.loads(payload)["log_sha256"]
                game = tuple(logs[name] for name in ("server.log", "dark.log", "light.log"))
                require(game not in seen_logs, "duplicate native game logs")
                seen_logs.add(game)
            results.append(result)
        except (ValueError, KeyError, OSError) as exc:
            results.append(dict(run=directory.name, receipt_sha256=digest, status="rejected", failure=str(exc)))
    return dict(weights_sha256=expected_sha, game_seconds=seconds, matches=results, coverage=coverage(results, maps))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--weights", required=True, type=Path)
    p.add_argument("--weights-sha256", required=True)
    p.add_argument("--map", required=True, action="append", dest="maps", help="Expected stock map name; repeat for each.")
    p.add_argument("--seconds", required=True, type=int)
    p.add_argument("directories", type=Path, nargs="+", help="Individual match directories, including failed attempts.")
    args = p.parse_args()
    stock = json.loads((Path(__file__).resolve().parents[2] / "qa/bots-stock-map-audit.json").read_bytes())
    pinned = {m["map"]: m["sha256"] for ep in stock["episodes"] if ep["episode"].lower() == "jk1mp" for m in ep["maps"]}
    if any(m not in pinned for m in args.maps) or args.seconds < 1:
        p.error("expected a stock JK1MP map and positive duration")
    output = audit(args.directories, args.weights, args.weights_sha256, {m: pinned[m] for m in args.maps}, args.seconds)
    print(json.dumps(output, indent=2))
