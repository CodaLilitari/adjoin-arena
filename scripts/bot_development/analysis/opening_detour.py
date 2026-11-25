"""Read opening-life gear plans in a qualified Canyon Oasis owner's native log."""
from math import isfinite
import re


# Stock m10.jkl thing IDs. The HUD confirms weapon type, not which repeater rack supplied it.
PICKUPS = {10: ("repeater", "Repeater Gun"), 34: ("repeater", "Repeater Gun"),
           29: ("concussion_rifle", "Concussion Rifle")}
PLAN = re.compile(r"BOT_GEAR name=(\S+) t=(\d+(?:\.\d+)?) event=plan item=(\d+) "
                  r"guid=\d+ signature=\d+ pack=([01]) anchor=-?\d+ direct=([01])")


def read_opening_detour(log_path, expected_name, first_plan_item, first_life_gains_after_release):
    """Join native plan/HUD order to same-owner, same-log first-life inventory qualification.

    The caller supplies the first observed plan and validated first 0→1 gain times
    (seconds since owner release) from the instrumented Canyon Oasis fixture.
    Lines count physical LF-delimited records, starting at 1. Plans describe target
    selection only. Switching items does not establish movement or the cause of a delay.
    """
    plans = []
    result = dict(status="unobserved", reason=None, plans=plans, release_line=None, pickup=None,
                  different_item_plan_before_pickup=None, post_release_different_item_plan_before_pickup=None)
    weapon = PICKUPS.get(first_plan_item)
    if weapon is None:
        result["reason"] = "unmonitored_initial_item"
        return result
    inventory_key, hud = weapon
    gain = first_life_gains_after_release.get(inventory_key)
    opened = False
    with log_path.open("rb") as stream:
        for line_no, raw in enumerate(stream, 1):
            line = raw.strip().decode("ascii", errors="replace")
            if not opened:
                opened = line == "ADJOIN_OPENING"
                continue
            if line in ("ADJOIN_OPENING", "ADJOIN_RESPAWN") or line.startswith(
                    ("BOT_RESPAWN ", "OpenJKDF2: sithWorld_Load -> ")):
                break
            if line == "GATE_LOCAL_RELEASE":
                if result["release_line"] is not None:
                    raise ValueError("Duplicate owner release in opening life")
                result["release_line"] = line_no
            elif line.startswith("BOT_GEAR ") and "event=plan" in line.split():
                match = PLAN.fullmatch(line)
                if not match or match[1] != expected_name:
                    raise ValueError("Malformed native gear plan or unexpected owner")
                item = int(match[3])
                if not plans and (item != first_plan_item or match[4] != "0"):
                    raise ValueError("Initial native gear plan disagrees with qualified stock item")
                change = "initial"
                if plans:
                    change = "same_item_replan" if item == plans[-1]["item"] else "changed_target"
                plans.append(dict(line=line_no, bot_time_s=float(match[2]), item=item, direct=match[5] == "1",
                                  change=change, after_release=result["release_line"] is not None))
            elif line == hud:
                if not plans or result["release_line"] is None:
                    result["reason"] = "hud_precedes_plan_or_release"
                    return result
                if gain is None:
                    result["reason"] = "missing_first_life_inventory_gain"
                    return result
                if isinstance(gain, bool) or not isfinite(gain) or gain < 0:
                    raise ValueError("Invalid owner inventory gain time")
                different = [p for p in plans if p["item"] != first_plan_item]
                result.update(status="qualified",
                              different_item_plan_before_pickup=bool(different),
                              post_release_different_item_plan_before_pickup=any(p["after_release"] for p in different),
                              pickup=dict(line=line_no, hud=hud, weapon=inventory_key,
                                          owner_gain_seconds_after_release=gain))
                return result
    result["reason"] = "missing_opening" if not opened else "missing_initial_weapon_hud_in_opening_life"
    return result
