# Multiplayer map and ruleset coverage

The stock JK multiplayer sequence declares six deathmatch levels and three Capture the Flag levels. Each deathmatch level has eight cells, covering free-for-all and team play, with guns or sabers, and No Force or Full Force. Each CTF level has four cells, covering both weapon and Force settings. The original Jedi's High School adds eight deathmatch cells. Use the author's original JHS episode for these runs. The recording edition with an additional starting position has a different digest.

The [matrix receipt](../qa/map-rules-play.json) lists the actual map and GOB digests, seat order, controller and binary identity, requested pace and game duration, map sectors visited by each player, scoreboard deltas, and CTF objective samples. Each attempt retains its clock-verification outcome. Real-time repeats and earlier accelerated trials are listed independently.

| Original maps | Scheduled | Both owners joined with verified loadouts and clocks | Both owners showed physical play |
| --- | ---: | ---: | ---: |
| Stock FFA and team deathmatch | 48 | 48 | 48 |
| Stock CTF | 12 | 11 | 9 |
| Jedi's High School FFA and team deathmatch | 8 | 8 | 8 |

### Coverage across native and JKWeb

Across both runtimes, **68 of 68 distinct map/ruleset combinations** have a
verified two-owner session. In **68 of 68**, both owners showed physical play
under their runtime's measurement. All 12 stock CTF combinations have
two-owner movement and both owners selecting flag objectives beyond team
entry. **Six of those 12** have a confirmed capture. Each combination counts
once, including repeated C2 sessions. [Cross-runtime score and source digests](../qa/map-rules-cross-runtime.json)

| JKWeb trial | Teams and movement | Both-owner objective evidence | Stock capture announcements |
| --- | --- | --- | --- |
| C2 NF sabers, 100 s | Opposing teams, 9 and 6 sectors | Both sought the flag, carried home and intercepted | Red 3, Gold 1 on both screens |
| C3 FF sabers, 105 s | Opposing teams, 3 and 3 sectors | Both sought the flag. Red first reported its assigned team 72.86 s after joining | 0 |
| C3 FF guns, 105 s | Opposing teams, 6 and 4 sectors | Both sought the flag. Lily remained in sector 605 and Red in 393 at each of the last five ten-second checks | 0 |

The JKWeb movement check requires sampled displacement between living
positions within the same life and visits to multiple sectors in the native
game log, for each owner. An assigned-team flag goal is a planner decision.
The capture count uses stock game announcements independently recorded by
both clients. [Windows match evidence](../qa/windows-stock-ctf-c2-c3.json)

On C3, the FF guns owner consoles reported 12 gold-key denials for team 1
Lily and three red-key denials for team 2 Red over their sessions. Lily later
held the same horizontal coordinates at all five ten-second checks in sector
605, between the two doors of the gold airlock, while her planned destination
changed. Red did the same in sector 393, beside door 24, which requires the
red key. In FF sabers Lily held sector 505 in the red airlock for ten
successive checks spanning 90.1 game seconds. Her saber-session console
recorded zero key denials. These samples locate three persistent first-leg
stalls. Door frames and the activation target on each tick are still unknown.
[C3 door bindings and stall measurements](../qa/c3-door-stalls.json)

The static navigation graph omits moving door things. The driving code tries
ordinary activation during recovery. The stock C3 airlock script checks
inventory bin 83 or 84 for its interior door and waits for both doors to
close before accepting another activation. The exterior door also takes an
activation. A focused next engine trial should record the aimed-at door and
its frame, route around a denied entrance, and verify escape from a friendly
airlock with ordinary controls. [Graph and recovery code](../web_bots/engine.patch)

An [experimental C3 door patch](../web_bots/candidate/c3-door-access.patch)
checks the exact stock level and three door scripts before binding the six
keyed doors. It applies the stock inventory rule to the first navigation
anchor and straight walking edges. A fully open door can be used by either
team. The Windows graph regression exercised the actual edge builder and path
search: without the gold key the bot selected a longer walking route, and
with the key or a fully open door it selected the short route. Reclosing
the door restored the detour after the key was removed.
[Candidate test receipt](../qa/c3-door-access-candidate.json)

Four private JKWeb matches compared the packaged engine with the C3 patch
applied after the normal [overlay stack](../web_bots/engine_patches.py).
Each room ran for 105 seconds after both players joined, with Lily hosting on
Red and Red playing on Gold. Rebuilding the unmodified bot object reproduced
the packaged JS and WASM byte for byte. Both candidate owners bound all six
keyed doors in both rulesets.

| C3 full-Force rules | Engine | Key denials, Lily / Red | Distinct sectors, Lily / Red | Flag captures |
| --- | --- | --- | --- | --- |
| Guns | Packaged | 99 / 0 | 3 / 1 | 0 |
| Guns | Candidate | 0 / 0 | 8 / 8 | 0 |
| Sabers only | Packaged | 104 / 0 | 4 / 5 | 0 |
| Sabers only | Candidate | 0 / 0 | 4 / 8 | 0 |

Sector counts use living, team-assigned positions sampled every ten game
seconds during shared play. In the packaged guns game, Lily stayed on the
same walking leg in sector 393 for at least 70 seconds. In the packaged saber
game, Lily left 393 and Red left 605 alive. No candidate owner appeared in
393, 505 or 605 at a sampling point. Each candidate sought the enemy flag.
Across all four rooms, no owner was sampled in the enemy flag's starting
sector or reported carrying it home. Random spawns and one match per arm
limit what the comparison can establish.
[Paired game measurements and build digests](../qa/c3-door-access-matches.json)

### Matched C3 door results

Four further games placed Lily inside her own red airlock (sector 505) and
Red on the gold team beside the locked red door (sector 393). The private
fixture waited for the stock scripts to assign both teams and issue their
keys. It then placed both owners once with the same coordinates and facing.
Each pair started within 0.03 wall seconds of each other. The owners'
clocks ran at 0.998–1.001 game seconds per wall second. Times below are
measured from each player's placement to the first observation beyond the
chamber or starting sector, on the same life.

| Full-Force game | Lily, friendly airlock | Red, locked-door approach | Red-key denials for Red during that life | Flag captures |
| --- | --- | --- | ---: | ---: |
| Guns, v0.6.1 | Still inside at 102.4 s | Still in 393 at 102.3 s | 127 | 0 |
| Guns, candidate | Outside by 2.70 s | Left for sector 402 by 2.01 s | 0 | 0 |
| Sabers, v0.6.1 | Still inside at 103.2 s | Still in 393 at 103.3 s | 3 | 0 |
| Sabers, candidate | Still inside at 101.2 s | First seen outside in sector 403 by 1.60 s | 0 | 0 |

In the candidate guns run, Lily visited 87 sectors and came within 1.378
world units of the enemy flag's starting position. The last chamber and first
outside samples bracket the outer opening; the narrow door sector fell
between samples. Red found the friendly corridor in both candidate games.
Neither owner was observed carrying the opposing flag in any of the four
rooms. One preliminary saber room put both players on gold and the fixture
withheld placement. Lily started the scored saber control with 99.35 health
and the candidate with 100. Red switched weapons immediately after placement
in the guns control. Each game used a fresh navigation store.
[Matched starts, observed routes and run comparisons](../qa/c3-matched-door-play.json)

### Reproduce the matched C3 opening

Build the practice episode from your own stock `JK1CTF.GOB` in an external
directory. The fixture changes the local team respawn script. The C3 level
geometry and the door scripts keep their retail bytes. Start a private
loopback relay as described in the [JKWeb operator guide](../web_bots/README.md).

```sh
mkdir -p "$RUNS/fixture"
python -B -m scripts.bot_development.c3_matched_opening \
  "$GAME_DATA/Episode/JK1CTF.GOB" "$RUNS/fixture/JK1CTF.GOB" > "$RUNS/fixture.json"
```

Use a fresh external directory for each run. Set `ENGINE` to the packaged
`bin/bots-jkweb` directory for the control or the separately built candidate
for the comparison. Run the observer and host together from the checkout.
The observer reads both owners through the ordinary companion interface.

```sh
RULES=ff-guns
ARM="$RUNS/control-$RULES"
mkdir "$ARM"
python -B -m scripts.bot_development.analysis.c3_record_owners "$ARM" --timeout 360 &
OBSERVER_PID=$!
ADJOIN_NAV_MEMORY="$ARM/navigation" python -B -m web_bots.headless host \
  --relay ws://127.0.0.1:8080/relay --room-name C3Matched --max-players 4 \
  --host-seat lily --seats red --mode "$RULES" --episode JK1CTF --map c3.jkl \
  --episode-gob "$RUNS/fixture/JK1CTF.GOB" --engine-dir "$ENGINE" --data "$GAME_DATA" \
  --runtime "$ARM/rooms" --chrome "$CHROME" --seconds 115 --join-timeout 90 \
  --width 320 --height 180 --fps-cap 30 --raster-threads 1 --no-software-gl --no-taunts \
  > "$ARM/launcher.log"
wait "$OBSERVER_PID"
python -B -m scripts.bot_development.analysis.c3_matched_doors "$ARM"
```

Repeat with the candidate engine and with `RULES=ff-sabers` for both engines.
Record each engine's JS and WASM hashes and use the same fixture for all four
rooms. The headless manifest and companion credentials stay in the private
run directory.

For the control, use `bin/bots-jkweb` from v0.6.1. To prepare the candidate
in a separate directory, activate the release toolchain (Emscripten 6.0.12)
and use a fresh external build root. The first build supplies the verified
control. The second recompiles the same source with the keyed-door patch.

```sh
export JK_WEB_BUILD_ROOT="$RUNS/c3-engine" JK_WEB_OUTPUT_ROOT="$RUNS/control-package"
./web_bots/build.sh
patch_file="$(pwd)/web_bots/candidate/c3-door-access.patch"
git -C "$JK_WEB_BUILD_ROOT/source" apply --check "$patch_file" &&
  git -C "$JK_WEB_BUILD_ROOT/source" apply "$patch_file" &&
  cmake --build "$JK_WEB_BUILD_ROOT/build" --parallel 2
export ENGINE="$JK_WEB_BUILD_ROOT/build"
sha256sum "$ENGINE/openjkdf2.js" "$ENGINE/openjkdf2.wasm"
```

Compare the hashes with the [played candidate](../qa/c3-door-access-matches.json)
before comparing your measurements with this trial.

Run the focused tests with `python -B -m unittest discover -s tests -p test_c3_door_access.py -v`.
On Windows the full path-search test reads `C3_EPISODE` (the owned stock
JK1CTF GOB), `C3_ENGINE_SRC` (engine `src`), and `C3_GLOBALS_DIR` (the
generated `globals.h` directory). Set `C3_BOT_SRC` when the packaged
AI source files are staged in a different `src` directory. Set `CC` to the
Windows Clang executable if needed.

Replay all four owner traces against a local stock episode. The fixture
contains periodic game-state fields and key-denial counts. To diagnose a new
private room, replace `--replay ...` with its owner `*.console.log` paths.

```sh
python -B -m scripts.bot_development.analysis.c3_door_stalls "$JK1CTF_GOB" --replay qa/c3-door-replay.json
```

Recompute the combined result after updating either underlying receipt:

```sh
python -B -m scripts.bot_development.score_cross_runtime_coverage --output qa/map-rules-cross-runtime.json
```

The native physical-play check requires ready graph movement input and at least one sector transition within a single life, an observed weapon gain, or a kill for each owner during the scored game-clock window. CTF additionally requires valid flag-objective telemetry from both players. The stock host logged five captures across C1 and C2 in the qualified windows. On C3, a red player's valid capture goal persisted while forward and strafe inputs stayed zero in FF guns and FF sabers. C2 NF sabers still needs a qualified clock window. These short, two-owner matches measure basic play and expose stalls. They have no human opponent or competitive ranking.

### Original JHS entrance

Three native JHS repeats used original spawns, fresh navigation caches and 100 game seconds per cell at 2×. The first combined navigation candidate brought JHS from five to six cells with both owners active. In NF guns FFA, Boba and Jan made 18 and 52 same-life sector changes and recorded one and two kills. In FF saber FFA and NF saber team deathmatch, Jan changed sectors 22 and 42 times respectively. Boba reached nine entrance waypoints in each saber game, then stopped on mesh 181 at the final bridge lip. The release and candidate attempts retain their individual engine hashes. [Native clock and route evidence](../qa/navigation-candidate-matches.json)

Both saber cells passed in a second pair of 100-game-second trials on the landing-probe build, bringing JHS to eight of eight on the union of native engine revisions. Boba and Jan changed sectors 119 and 1 times in FF FFA and 65 and 12 times in NF team deathmatch. In the latter game both logged a same-life exit into sector 7; in FF FFA Jan still stopped at the lip when the long clearance probe reported an obstacle. Activity and successful entrance traversal are scored separately. [Per-life landing observations](../qa/navigation-candidate-matches.json)

The next native build (`f498e71d…`) used a full-radius collision sweep over the next walking increment. All three players who started on entrance mesh 184 reached sector 7 on their first life. In FF saber FFA Boba crossed at game time 8.262. In NF saber team deathmatch Boba crossed at 8.330 and Jan at 8.194. Both games ran 100 game seconds at 2× and passed the clock and two-owner activity checks. Boba and Jan made 129 and 9 same-life sector changes in FFA and 24 and 83 in team play. These original-spawn trials used the engine controller without an external coach. [Engine identities, owner clocks and per-life crossings](../qa/navigation-candidate-matches.json)

Two separate FF saber JKWeb matches give different observations. Both owners changed sectors in the first game, which lacked a saved lobby packet. The repeat recorded FFA flags, 16 ms ticks and rank 8, while Lily stayed in sector 5. The combined score recognizes the verified browser room and credits the native trials for two-active FFA play on this cell. [JKWeb owner and lobby observations](../qa/jhs-ffa-owners.json)

### Reproduce


Run from the repository root. Keep data, networking libraries, candidate binaries, nav caches and logs outside the checkout. The native runner uses one private Linux network namespace per cell, verifies the staged files and checks each owning process's game clock.

```sh
python3 -B -m scripts.bot_development.map_coverage
python3 -B -m scripts.bot_development.map_coverage --run \
  --episode jk1mp --episode jk1ctf --data "$DATA" --pace-build "$PACE" \
  --stock-build "$COMPETITIVE" --output "$RUNS/stock" --rate 2 --seconds 30
python3 -B -m scripts.bot_development.map_coverage --run \
  --episode jhs --data "$DATA" --pace-build "$PACE" --jhs-gob "$JHS_GOB" \
  --jhs-client competitive --stock-build "$COMPETITIVE" --output "$RUNS/jhs" --seconds 60 --rate 1
python3 -B -m scripts.bot_development.score_map_coverage \
  "$RUNS/stock" "$RUNS/jhs" --output "$RUNS/summary.json"
```

The competitive JHS command requires a client and launcher with verified custom admission. To reproduce the earlier entrance-route client, use `--jhs-client hints --hint-build "$HINT_BUILD"` with the corresponding source snapshot (`--repo`) and pace build. Select a particular cell with `--cell c2-ctf-sabers-off`. Repeats use a fresh output root; `--jan-first` reverses the starting order.

### What counts as an upper-floor visit

The original JKL places the middle floor at or above Z 2.365312 in the tracked sectors. The upper passages begin at 4.115 and the roof at 4.545. The repeater and railgun are in sectors 57 and 58, with rooftop vents in 10 and 11. Sector 5 spans a void, an entrance platform and a tall sky volume. Presence in sector 5 supplies no roof evidence. The scorer requires consecutive live owner samples in a tracked region, and separately marks a prior lower-sector sample during that life.

Open portals connect the lower rail-ammo landing to the upper railgun corridor through sectors 124, 122, 121, 120, 123, 119 and 58. The three sloped chute faces have collision enabled and lack the floor flag that ordinary player ground attachment uses. At the top, a 0.13-unit lip blocks the direct body sweep. A headless JKWeb trial applying uphill motor inputs from this chute slipped toward the lower landings. The candidate navigation code checks grounded support on upward slopes. [Candidate build and compiled fixtures](NAVIGATION_CANDIDATE.md)

**Lily reached the roof from an ordinary spawn on the original JHS episode under all four weapon and Force settings.** In each of the private two-owner games below, Red hosted and Lily joined at the front entrance in sector 5. Lily crossed the static platforms, rode the entrance transporter through sectors 9 and 16, and jumped through sector 19 onto the roof. Each time she was alive at full health on her first life. The timer runs from the first owner sample until Lily had two consecutive observations of standing on the roof in sector 0. [Windows JHS openings and owner observations](../qa/jhs-upper-play.json)

| Room and matching coach loadout | Game seconds to supported roof | Roof sample IDs |
| --- | ---: | --- |
| NF sabers | 24.535 | 399, 401 |
| FF sabers | 26.632 | 432, 433 |
| NF guns | 24.734 | 382, 383 |
| FF guns | 29.444 | 422, 423 |

In the NF sabers run the coach handed back movement and Lily subsequently visited upper sectors 34, 35 and 36. The FF sabers run used a later controller revision that moves forward on the rising transporter. With that revision, a 50-second NF sabers repeat handed movement back for combat on the first life. Lily's highest live Z was 1.249 and she did not reach the roof. Other trials ended on a stale observation or a missed upper exit. An earlier two-owner run without the route coach recorded highest living positions of Z 0.347 for Lily and 0.384 for Red. These timings describe successful traversals across controller revisions. Match win rates remain unmeasured. [All recorded trials](../qa/jhs-upper-play.json)

The FF sabers roof run also shows both native owners moving across sectors at normal speed throughout the shared measurement window. A separate private FF sabers run captured the raw lobby entry confirming free-for-all (team bit clear) and rank 8. In that repeat Lily stayed in sector 5. The two receipts retain their separate mode and activity evidence. [Owner, lobby and timing checks](../qa/jhs-ffa-owners.json)

The middle hall has a slashable grate on approach to that elevator. Surface 868, facing the hall, initially blocks movement into sector 30. Its reverse face 327 permits movement out. The stock `00_SLASHGRATE.COG` opens it on saber or explosive damage. Two hall-side attempts with primary fire failed to board. A diagnostic copy independently confirmed that aligning with the grate and using secondary saber fire reached the stock COG's accepted damage branch. The entrance transporter, ground-to-middle switch lift (thing 65), and middle-to-roof lift (thing 11) have separate routes and triggers.

The optional coach also cleared the **middle-hall route** in NF sabers. Lily started in sector 79 facing the intact grate, cut through, boarded sector 30 and rode through sector 31 to roof sector 0 in **17.383 game seconds**. This was a solo practice start outside the grate with the normal COGs and geometry intact. A separate NF guns drill placed Lily on the lower car; its deck-to-roof segment took 2.216 game seconds. [Per-life observations](../qa/jhs-upper-play.json)

The local **Lilivane coach automatically helps with the final exit** when it has already observed Lily riding the entrance transporter up in the original JHS. Operators can turn this off with `--no-jhs-roof`. Selecting `--jhs-roof` also enables deliberate routes from the front spawn and the middle grate. Full-opening routing is opt-in because the timing trials do not establish whether leaving the nearest pickup or a fight improves match results.

The coach verifies the map and episode hashes in the hosted-room and owner manifests. It acts only in the launch world, steps aside for nearby combat or a manual coaching command, allows at most two attempts per life, and bounds each attempt to 32 wall seconds. The hall and entrance approaches have a 30-game-second limit and the final transporter exit has a six-game-second limit. Chat continues on the same lease. Other maps and older manifests without content identity use normal navigation.

```sh
python3 -B -m scripts.bot_development.analysis.jhs_upper_geometry "$JHS_GOB" --stock "$RES2_GOB"
python3 -B -m scripts.bot_development.jhs_upper_drill "$JHS_GOB" "$RUNS/upper-practice" \
  --run --data "$DATA" --pace-build "$PACE" --stock-build "$COMPETITIVE"
```

The drill generator verifies the original archive and changes only its player starts. The default opening uses the lower flat chute landings in sectors 124 and 121. Use `--start-area middle-lift` for the wider hall, `hall-grate` for the verified start in front of the grate or `lift-deck` for the ride from the lower car. The `nearest-original` fixture exchanges the two original start assignments in sectors 199 and 135. All six authored poses remain available. The manifest identifies each fixture. These practice openings have a separate score from the 68 original map/ruleset combinations.

To repeat the original-spawn result, host the **original** GOB with `--adaptive-lily --host-seat red --seats lily --mode nf-sabers --max-players 6` on a loopback relay. Attach the normal coach when the headless manifest lists Lily's owner. For the separate hall drill, use the `hall-grate` fixture with `--host-seat lily --seats ""`. The `entrance-original` practice fixture swaps two original spawn slots for controlled solo entrance trials.

```sh
python3 -B -m bots.coach_seat --run "$HEADLESS_JSON" --seat lily --start lilivane \
  --weapons sabers --jhs-roof --control "$RUNS/coach" --seconds 120
```

To repeat the elevator ride with JKWeb, first generate the deck fixture, then host a private room using the packaged engine and the regular bot roster. Set `RELAY` to your local JKWeb relay. `ROOM` must be an external output directory.

```sh
python3 -B -m scripts.bot_development.jhs_upper_drill "$JHS_GOB" "$RUNS/deck" --start-area lift-deck
python3 -B -m web_bots.headless host --relay "$RELAY" --room-name JHS-Roof-Lift \
  --host-seat lily --seats red --mode nf-guns --episode-gob "$RUNS/deck/jhs_upper.gob" --map jhs.jkl \
  --data "$DATA" --engine-dir "$WEB_ENGINE" --runtime "$ROOM" --seconds 45 --adaptive-lily
```

Read each owner's `BOT_STATUS` in the room logs. For high-rate evidence, start the read-only observer alongside the coach. It uses the headless manifest to resolve Lily's owner and takes no controller lease. Keep both output paths in external scratch.

```sh
python3 -B -m scripts.bot_development.analysis.jhs_upper_play --record "$HEADLESS_JSON" --seconds 60 --output "$RUNS/owner.jsonl"
python3 -B -m scripts.bot_development.analysis.jhs_upper_play --score-trace "$RUNS/owner.jsonl" --output "$RUNS/upper-score.json"
```
