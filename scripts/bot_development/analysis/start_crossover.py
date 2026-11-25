"""Compare recorded Canyon Oasis runs that exchange only the two starting positions."""
import argparse
import json
from pathlib import Path

from .. import controlled_opening, ready_gate
from .native_duel import SIDES, read_observer, read_seat, require, sha


NAMES = {"dark": "Bot_BobaFett", "light": "Bot_JanOrs"}
PROFILE_ORDER = ("boba_fett", "jan_ors")
WEAPONS = {10: "repeater", 29: "concussion rifle", 34: "repeater"}


def read_match(directory, *, allow_no_plan=False, expected_pacing="normal engine wall-clock", expected_host_sha=None):
    path = directory / "receipt.json"
    receipt = json.loads(path.read_bytes())
    gate = receipt["ready_gate_observations"]
    fixture = receipt["opening_fixture"]
    assignment = fixture.get("start_assignment")
    require(receipt["kind"] == "adjoin-arena-ready-gate" and gate["status"] == "qualified"
            and receipt["status"] == "live_join_and_loadout_verified" and fixture.get("observe_repeater") is True
            and receipt["requested_map"] == "m10.jkl" and receipt["network_interfaces"] == ["lo"]
            and receipt["pacing"] == expected_pacing, "Requires an instrumented native ready-gate match at the expected pace")
    require(assignment in ("normal", "swapped"), "Unknown start assignment")
    order = tuple(receipt["seat_order"])
    require(order in (PROFILE_ORDER, PROFILE_ORDER[::-1]), "Unknown join order")
    jan_first = order[0] == "jan_ors"
    sides = SIDES[::-1] if jan_first else SIDES
    swapped = assignment == "swapped"
    require(fixture["variant_gob_sha256"] == controlled_opening.REPEATER_GATE_GOBS[swapped]
            and fixture["variant_jkl_sha256"] == controlled_opening.VARIANT_MAP,
            "Unexpected instrumented episode or map")
    openings = controlled_opening.qualify(directory, receipt["bots"], swap_starts=swapped, jan_first=jan_first)
    mode = receipt.get("planner_experiment", {}).get("mode")
    require(openings == receipt["opening_observations"]
            and ready_gate.qualify(directory, openings, planner_mode=mode) == gate,
            "Opening or start gate differs from native logs")
    repeaters = controlled_opening.qualify_repeater(directory, openings, gate, jan_first=jan_first)
    require(repeaters == receipt["repeater_observations"], "Repeater observations differ from native logs")
    log_hashes = {name: sha(directory / name) for name in ("dark.log", "light.log", "server.log", "force-trace.jsonl")}
    require(log_hashes == receipt["log_sha256"] and log_hashes["server.log"] == gate["host_log_sha256"],
            "Native logs differ from the verified run")
    _, video = read_observer(directory, receipt, [NAMES[side] for side in sides], sides=sides, expected_host_sha=expected_host_sha)
    require(video["camera"] == "rifle-overlook", "Use the same rifle-overlook camera for all runs")

    seats = {}
    profiles = {}
    for side in SIDES:
        peer = receipt["bots"][side]
        opening = openings[side]
        repeater = repeaters[side]
        owner = gate["owners"][side]
        sector = opening["events"][0]["sector"]
        native = read_seat(directory / (side + ".log"), NAMES[side])
        plan = native["first_gear_plan"]
        slot = opening["slot"]
        require(slot == sides.index(side) + 1 and native["join_acknowledgements"] == [peer["joined"]]
                and (plan or allow_no_plan),
                "Unexpected native seat, join or initial plan")
        held_plans = owner["pre_release_plans"]
        if held_plans:
            require(plan and held_plans[0] == {"item": plan["item"], "bot_time_s": plan["t"]}, "First plan disagreement")
        release = owner["release_time_s"]
        first_gains = {}
        for bin_id, label, source in ((9, "concussion_rifle", opening), (6, "repeater", repeater)):
            gains = [ev for ev in source["events"] if ev["kind"] == "sampled_inventory_change"
                     and ev["life_ordinal"] == 1 and ev["previous"] == 0 and ev["current"] == 1]
            require(all(ev.get("bin", bin_id) == bin_id and ev["level_time_s"] >= release for ev in gains),
                    "Inventory gain precedes release or has an unexpected bin")
            first_gains[label] = round(gains[0]["level_time_s"] - release, 6) if gains else None
        require(first_gains["repeater"] == repeater["first_life_gain_after_release_s"], "Repeater timer disagreement")
        item = plan["item"] if plan else None
        seats[side] = dict(name=NAMES[side], slot=slot, sector=sector, position=opening["events"][0]["position"],
                           first_plan_item=item, first_plan_weapon=WEAPONS.get(item),
                           first_plan_bot_seconds=plan["t"] if plan else None, first_plan_during_hold=bool(held_plans),
                           plans_during_hold=held_plans,
                           held_owner_seconds=round(release - owner["hold_time_s"], 6),
                           first_life_gain_seconds_after_release=first_gains,
                           observed_respawns=native["respawn_reports"])
        args = list(peer["argv"])
        args[args.index("-botConnect") + 1] = "loopback host"
        profiles[side] = dict(argv=args, loadout=peer["loadout"], behavior=peer["behavior"])

    hashes = dict(receipt["sha256"])
    require(hashes.pop("jk1mp.gob") == fixture["variant_gob_sha256"]
            and hashes["jkl/m10.jkl"] == fixture["variant_jkl_sha256"], "Loaded episode or map differs from fixture")
    settings = {k: receipt[k] for k in ("pacing", "seat_order", "bot_options", "seed_control", "launcher_sha256",
                "launcher_input_sha256", "ready_gate_source_sha256", "recorder_sha256", "requested_match_seconds",
                "platform", "render_environment")}
    settings.update(profiles=profiles, binary_and_map_hashes=hashes,
                    server_registry={k: v for k, v in receipt["server_registry"].items() if k != "portNum"})
    if mode is not None:
        settings["planner_experiment"] = {"mode": mode, "build": receipt["planner_experiment"]["build"]}
    acks = gate["host_acknowledgements"]
    require(len(acks) == 2 and {ack["slot"] for ack in acks} == {1, 2}, "Missing release acknowledgement")
    result = dict(assignment=assignment, source_receipt_sha256=sha(path), logs_sha256=log_hashes, video=video,
                  shared_observation_wall_seconds=receipt["both_joined_observation_wall_seconds"],
                  cutoff_to_shutdown_request_seconds=receipt["cutoff_to_shutdown_request_seconds"],
                  native_shutdown_seconds=receipt["native_shutdown_wall_seconds"],
                  video_finalize_seconds=receipt["observer_flush_wall_seconds"],
                  host_ack_spread_ms=round(1000 * (acks[-1]["host_time_s"] - acks[0]["host_time_s"])),
                  seats=seats)
    return result, fixture, settings


def compare(directories):
    runs = []
    fixtures = {}
    common = None
    for directory in directories:
        result, fixture, settings = read_match(directory)
        assignment = result["assignment"]
        if common is None:
            common = settings
        require(settings == common, "Matched controls differ across runs")
        require(fixtures.setdefault(assignment, fixture) == fixture, "Fixture changed within a condition")
        runs.append(result)
    require(len({r["logs_sha256"]["server.log"] for r in runs}) == len(runs), "A host log was reused")
    counts = [sum(r["assignment"] == side for r in runs) for side in ("normal", "swapped")]
    require(counts[0] == counts[1] and counts[0] >= 2, "Provide equal numbers of at least two runs per condition")
    require(fixtures["normal"]["variant_gob_sha256"] != fixtures["swapped"]["variant_gob_sha256"],
            "Both start assignments used the same episode")
    return dict(schema=1, scope="1x native Canyon Oasis. Inventory gains cover the opening life only. "
                "Null means no gain was sampled. Times use the owner's clock from its own release.",
                configuration=common, fixtures=fixtures, runs=runs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directories", type=Path, nargs="+", help="Recorded match directories in run order")
    parser.add_argument("--output", type=Path, required=True, help="New comparison JSON")
    args = parser.parse_args()
    try:
        result = compare(args.directories)
        with args.output.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(result, stream, indent=2, allow_nan=False)
            stream.write("\n")
    except (OSError, KeyError, ValueError, IndexError, TypeError) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
