# Bespin and Nar Shaddaa navigation

On Bespin Mining Station, the competitive controller looks for a pickup reachable through a body-width opening alongside a vertical lift. It can plan from either lift stop toward the shelf. During the ride it moves toward the opening before the sill reaches its feet. Stock item contact triggers a retreat toward the deck centre, then the controller dismounts at a landing. The concussion rifle and rail detonator both come within ordinary pickup reach from the moving deck.

| Controlled stock challenge | Observed result |
| --- | --- |
| Bespin concussion rifle, thing 13, shelf sector 61 | The game sent TAKEN in sector 45. Jan returned to the centre of the deck and dismounted in sector 46 on life 1 with 97.43 health. |
| Bespin rail detonator, thing 14, shelf sector 75 | The game sent TAKEN in sector 52. Jan cleared the opening and dismounted in sector 53 on life 1 with 99.81 health. |
| Bespin reactor rim, surface 1835 | Starting 0.13 units back with a 1.25-unit/s lateral velocity toward the shaft, the guard applied braking or recovery on 12 frames. At the 1.1 s sample Jan was grounded in sector 155 at 100 health. With the guard disabled she was falling in sector 101, 1.39 units below her starting height. |
| Nar Shaddaa, thing 48 | The ordinary switch sent the stock lift up. From the lower landing the probe repeatedly requested movement under the returning deck. The controller overrode 94 frames and stayed in sector 35 at 100 health through the return. With that final check disabled, Jan entered sector 109 and the deck pinned her. Her last live sample recorded 18.785 health. |

The cases use an isolated native dedicated server, an owner client, the retail JKLs, stock mover COGs, collisions and game clock. The weapon trials assign the objective and place the player once at a valid boarding approach. Stock TAKEN is observed in the engine's item dispatcher. Standing on a floor in a separate landing sector establishes escape. The Nar case stages the approach after the stock switch has raised the deck. The rim case seeds one lateral velocity and asks for tangent movement. These measurements establish the specific maneuvers. Autonomous pickup frequency, long-run fall rate and browser physics need their own match samples.

### Bespin rim with both guards enabled

With the shipping v0.6.1 controller, Jan braked on 10 frames, fell 1.0114
world units and was airborne in sector 102 after 1.1 game seconds. The
native navigation candidate braked on 12 frames and finished grounded in
sector 155, within 0.001 units of the starting height. Both started 0.13
units inside the same rim with 1.25 units/s of outward velocity. Both
were still alive at the cutoff. [Ordinary game clock](bespin-rim-guard-pair.json)

At 2× the same two controllers produced the same fall and grounded outcomes
with the same 34 measured rim samples in each run. Each client advanced
74.086 game seconds in 37.043 wall seconds across the wider observation
window. The private host and owners each used 34 ms simulation steps.
This particular collision and braking test can run at 2× while retaining
the observed 1× result. [Paced comparison](bespin-rim-guard-pair-paced-2x.json)

An earlier trial accepted a weapon bin's available bit before Jan had reached the shelf. The retained weapon trials require the stock callback for the exact item, the same life on escape, and a static dismount. Owner-log digests, map hashes and event lines are in [the navigation receipt](stock-navigation.json).

## Reproduce

On Linux, use the assembled competitive source tree, its generated globals header, the matching competitive relink bundle and your original game data. Use a loopback-only network namespace with the loopback device enabled and an available X display. The test instruments temporary sources, relinks the controller and item observer, and launches one case at a time through the bot launcher. The compiled test client and staged game files are removed at teardown. The output directory retains the logs, markers and file hashes. Set `--scratch-root` or `ADJOIN_MATCH_SCRATCH` to place temporary builds and games on a specific volume. [Match storage](../docs/TEST_STORAGE.md)

~~~sh
unshare --net sh -c 'ip link set lo up && exec xvfb-run -a python3 -B native/tests/stock_navigation_replay/run.py "$@"' sh \
  --source "$SRC" --generated "$BUILD/generated" --data "$GAME_DATA" \
  --out "$SCRATCH/nav-on" --seconds 45
~~~

For the matched hazard comparison, choose a fresh output directory and add the arguments --cases rim nar --veto-off. This disables the final guard for the controlled approach only. The fixture suite also exercises moving-deck entry, refusal to step under a raised deck, escape from a lift footprint, and recoverable rim overhangs.

~~~sh
python3 -B native/tests/run_bot_driver_tests.py --source "$SRC" --build "$BUILD"
~~~

## Original Jedi High School entrance

The [opt-in navigation candidate](../docs/NAVIGATION_CANDIDATE.md) embeds the existing ten-point entrance walk on both engine paths. Its digest and coordinates come from [jhs-school-entry.route](../bots/routes/jhs-school-entry.route). The controller checks the actual 597,187-byte JKL content hash, sector ownership and standability of all four support fixtures. A supported start on fixture 184 in sector 5 can follow fixtures 183, 182 and 181 into sector 7 with the normal walking controls. Each step samples live support under three lateral positions and checks body clearance. An interrupted hint yields to ordinary navigation. A separate fallback checks live static footing when a player is stranded on a standable fixture in a fall-death sector.

A host-compiled test of the C loader accepted the exact original JKL, rejected a same-length one-byte mutation, and rejected the original geometry when fixture 182 lacked standable support. The port applies the same coordinates to both clients. The prior native research build recorded exits on this route. The [original geometry check](adjoin-arena-jhs-route-geometry.json) and [original connected trial](adjoin-arena-jhs-hints-results.json) identify those fixtures and runs. The sector 5 entrance is separate from the upper-school ramps.
