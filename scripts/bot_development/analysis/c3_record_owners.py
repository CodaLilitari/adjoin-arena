"""Record read-only owner observations beside one matched C3 headless run."""
import argparse
import json
from pathlib import Path
import time

from bots.companion_cli import call, load_private


SEATS = ("lily", "red")
FIELDS = ("game_time", "slot", "net_id", "health", "deaths", "position", "weapon", "kills", "sector", "look")


def record(arm, timeout):
    if not 1 <= timeout <= 3600:
        raise ValueError("The recording timeout must be between 1 and 3600 seconds")
    if not arm.is_dir() or arm.resolve().is_relative_to(Path(__file__).resolve().parents[3]):
        raise ValueError("Choose the existing external directory for this matched run")
    output = arm / "samples.json"
    if output.exists():
        raise FileExistsError(output)
    rows, credentials = [], {}
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        manifests = list((arm / "rooms").glob("headless-*/headless.json"))
        if len(manifests) > 1:
            raise ValueError("The arm directory must contain exactly one headless room")
        if manifests:
            manifest = json.loads(manifests[0].read_bytes())
            if "final" in manifest:
                break
            seats = manifest.get("seats", {})
            if all(seats.get(seat, {}).get("joined") for seat in SEATS):
                if manifest.get("hosted", {}).get("map") != "c3.jkl":
                    raise ValueError("Expected a C3 host")
                observations = {}
                for seat in SEATS:
                    if seat not in credentials:
                        credentials[seat] = load_private(Path(seats[seat]["companion_credential"]))
                    try:
                        observed = call(credentials[seat], "observation")
                    except OSError:
                        continue
                    state = observed.get("state")
                    if observed.get("native_active") and state:
                        observations[seat] = {key: state.get(key) for key in FIELDS}
                if observations:
                    rows.append({"wall": time.monotonic(), "seats": observations})
        time.sleep(.7)
    if not all(any(seat in row["seats"] for row in rows) for seat in SEATS):
        raise ValueError("Both playing owners must report observations before the room closes")
    encoded = json.dumps(rows, separators=(",", ":"), allow_nan=False)
    with output.open("x", encoding="utf-8") as stream:
        stream.write(encoded)
    return len(rows)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("arm", type=Path, help="External directory containing rooms/headless-*/headless.json")
    parser.add_argument("--timeout", type=int, default=300, help="Wall seconds including room startup")
    args = parser.parse_args()
    print(f"Recorded {record(args.arm, args.timeout)} observation frames.")
