"""Build a private close-spawn drill from an owned stock Nar Shaddaa episode."""
import argparse
from pathlib import Path
import re
import sys

if __package__:
    from . import controlled_opening as opening
else:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    import controlled_opening as opening

LEVEL = "jkl/m2.jkl"
STOCK = "938f8a892bcdc90a7f54f25aed4fd58baba750293c5d01ac2dec68ef170eef9a"
START = re.compile(rb"(?m)^([ \t]*\d+:[ \t]+walkplayer[ \t]+walkplayer[ \t]+)"
                   rb"((?:[-.\d]+[ \t]+){6}\d+)(?=[ \t\r\n])")


def build(source, dest):
    if opening.digest(source.read_bytes()) != opening.STOCK_GOB:
        raise ValueError("Expected the retail JK1MP archive")
    entries = opening.read_entries(source)
    if opening.digest(entries[LEVEL]) != STOCK:
        raise ValueError("Unexpected Nar Shaddaa map")
    # Two positions face one another along the approach to stock rifle thing 30.
    # Both are in the original lower room (sector 61). All normal starts and
    # respawns in this drill alternate between these two markers.
    n = 0
    def position(match):
        nonlocal n
        n += 1
        y, yaw = ("-0.560000", "180.000000") if n % 2 else ("-0.940000", "0.000000")
        return match[1] + f"0.040000\t{y}\t0.120114\t0.000000\t{yaw}\t0.000000\t61".encode()
    entries[LEVEL] = START.sub(position, entries[LEVEL])
    if n < 2:
        raise ValueError("Missing player starts")
    with dest.open("xb") as f:
        f.write(opening.encode_entries(entries))
    if opening.read_entries(dest) != entries:
        raise ValueError("Private episode readback mismatch")
    return dict(gob_sha256=opening.digest(dest.read_bytes()), map_sha256=opening.digest(entries[LEVEL]), starts=n)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("stock", type=Path)
    p.add_argument("output", type=Path)
    a = p.parse_args()
    print(build(a.stock, a.output))

