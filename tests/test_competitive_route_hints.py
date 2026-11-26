"""Keep the two engine builds tied to the checked-in entrance route and retail map."""
import hashlib
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


class CompetitiveRouteHintsTest(unittest.TestCase):
    def test_both_clients_embed_the_authoritative_route(self):
        route = (ROOT / "bots/routes/jhs-school-entry.route").read_bytes()
        header, *rows = route.decode("ascii").splitlines()
        version, map_digest, count = header.split()
        self.assertEqual(version, "RED_ROUTE_HINT_V1")
        self.assertEqual(len(rows), int(count))
        expected = [tuple(map(int, row.split())) for row in rows]
        sources = []
        for directory in ("native", "web_bots"):
            with self.subTest(client=directory):
                patch = (ROOT / directory / "candidate/competitive-route-hints.patch").read_text()
                helper = patch.split("+++ b/src/AI/jkBotRouteHints.inc\n", 1)[1].split("\n--- ", 1)[0]
                source = "\n".join(line[1:] for line in helper.splitlines() if line.startswith("+"))
                sources.append(source)
                self.assertIn('#define ENTRY_MAP_SHA "' + map_digest + '"', source)
                self.assertIn('#define ENTRY_ROUTE_SHA "' + hashlib.sha256(route).hexdigest() + '"', source)
                array = source.split("static const HintPoint entryPoints[] = {", 1)[1].split("};", 1)[0]
                actual = []
                for row in array.strip().splitlines():
                    sectors, fixtures, x, y, z = re.findall(r"-?\d+(?:\.\d+)?", row)
                    actual.append((int(sectors), int(fixtures), *[round(float(v) * 1000) for v in (x, y, z)]))
                self.assertEqual(actual, expected)
        self.assertEqual(sources[0], sources[1])


if __name__ == "__main__":
    unittest.main()
