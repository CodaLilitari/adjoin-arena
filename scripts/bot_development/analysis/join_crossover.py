"""Compare four Boba-first and four Jan-first native Canyon Oasis openings."""
import argparse
import json
from pathlib import Path

from .native_duel import require
from .opening_detour import read_opening_detour
from .start_crossover import PROFILE_ORDER, compare


ASSIGNMENTS = ["normal", "swapped", "swapped", "normal"]


def match_controls(series, order):
    config = series["configuration"].copy()
    require(tuple(config.pop("seat_order")) == order, "Series has the wrong join order")
    require([row["assignment"] for row in series["runs"]] == ASSIGNMENTS,
            "Run each series in normal, swapped, swapped, normal order")
    # The Jan-first option changed the launcher and the owner-identity verifier.
    # Retain their hashes in the report while requiring the game and every other input to match.
    measurement = {"launcher_sha256": config.pop("launcher_sha256")}
    verifiers = config.pop("ready_gate_source_sha256").copy()
    measurement["controlled_opening_sha256"] = verifiers.pop("controlled_opening.py")
    config["gate_verifier_hashes"] = verifiers
    return config, measurement


def compare_orders(boba_first_dirs, jan_first_dirs):
    runs = []
    totals = []
    versions = {}
    common = fixtures = initial_stars = None
    for directories, order in ((boba_first_dirs, PROFILE_ORDER), (jan_first_dirs, PROFILE_ORDER[::-1])):
        series = compare(directories)
        controls, versions[order[0]] = match_controls(series, order)
        if common is None:
            common, fixtures = controls, series["fixtures"]
        require(controls == common and series["fixtures"] == fixtures,
                "Game inputs, profiles, fixture or other matched controls changed across join orders")
        counts = {slot: {"first_profile": order[0], "slot": slot, "profile": order[slot - 1],
                         "observed_openings": 0, "with_different_target": 0,
                         "with_post_release_different_target": 0} for slot in (1, 2)}
        for directory, row in zip(directories, series["runs"], strict=True):
            row["first_profile"] = order[0]
            stars = {}
            with (directory / "force-trace.jsonl").open(encoding="ascii") as trace:
                for line in trace:
                    event = json.loads(line)
                    if event["event"] == "state":
                        stars.setdefault(event["side"], event["stars"])
                        if len(stars) == 2:
                            break
            require(set(stars) == {"dark", "light"} and stars["dark"] != stars["light"],
                    "Both distinct initial Force loadouts must be observed")
            if initial_stars is None:
                initial_stars = stars
            require(stars == initial_stars, "Initial Force loadout changed for a player")
            for side, seat in row["seats"].items():
                detour = read_opening_detour(directory / (side + ".log"), seat["name"], seat["first_plan_item"],
                                             seat["first_life_gain_seconds_after_release"])
                seat["target_history_before_pickup"] = detour
                if detour["status"] == "qualified":
                    group = counts[seat["slot"]]
                    group["observed_openings"] += 1
                    group["with_different_target"] += int(detour["different_item_plan_before_pickup"])
                    group["with_post_release_different_target"] += int(detour["post_release_different_item_plan_before_pickup"])
            runs.append(row)
        totals.extend(counts.values())
    require(len({row["logs_sha256"]["server.log"] for row in runs}) == len(runs), "Reused native match")
    return {"schema": 1, "scope": "Two four-match 1x native series. A detour is a logged plan for a different "
            "item before the first planned weapon's opening-life pickup message, corroborated by owner "
            "inventory. Plans show intent. Slot, join order, gate coordination and planning time vary together.",
            "configuration": common, "initial_force_stars_by_side": initial_stars,
            "measurement_code": versions, "fixtures": fixtures,
            "counts_by_join_order_and_slot": totals, "runs": runs}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--boba-first", type=Path, nargs=4, required=True, metavar="RUN")
    parser.add_argument("--jan-first", type=Path, nargs=4, required=True, metavar="RUN")
    parser.add_argument("--output", type=Path, required=True, help="New comparison JSON")
    args = parser.parse_args()
    try:
        report = compare_orders(args.boba_first, args.jan_first)
        with args.output.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(report, stream, indent=2, allow_nan=False)
            stream.write("\n")
    except (OSError, KeyError, ValueError, IndexError, TypeError) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
