# Run Jan and Boba in the native arena

Use Bash on Linux, the project's dedicated server and your installed Jedi Knight game data. Build the [paced host, Red duel client and mode-aware transfer client](../native/README.md) before running these examples. Set `REPO` to this checkout, `OWNED_JK` to the game data, and `PACE_BUILD`, `RED_BUILD` and `TRANSFER_BUILD` to the corresponding native build directories. Set `RUN_ROOT` to an existing writable directory outside Git. Give each match a fresh output path. The launcher starts the host and both players inside a private loopback network.

## Replay a teacher match or compare the first weights

```bash
arena() {
  unshare -Urn -- sh -c 'ip link set lo up && exec "$@"' sh \
    python3 -B "$REPO/scripts/bot_development/legacy/native_force_observation.py" \
    --repo "$REPO" --data "$OWNED_JK" --arena-baseline \
    --pace-build "$PACE_BUILD" "$@"
}

arena --red-policy-build "$RED_BUILD" --pace-rate 2 --duration 90 \
  --map m10.jkl --output "$RUN_ROOT/train-01-m10-boba"

arena --red-policy-build "$RED_BUILD" --pace-rate 2 --duration 90 \
  --map m4.jkl --model-side dark \
  --policy-weights "$REPO/bots/models/red_pickup_engage_v1.weights" --camera follow \
  --output "$RUN_ROOT/bespin-neural-boba"
```

Boba joins first by default. Use `--jan-first` to reverse the join order. Each player's planner receives its own first playable tick. The common timed interval begins after the two players have joined. Use `--pace-rate 1 --camera follow` to study a difficult situation at ordinary speed with video. [Match schedule](../qa/adjoin-arena-red-decision-schedule.json) · [Learning between games](RED_DECISION_EXPERIMENT.md)

## Run CTF or visit an unfamiliar level

The transfer client reads the loaded level geometry and game rules. For stock CTF, specify the owned episode and the exact map digest from the [active mode schedule](../qa/adjoin-arena-mode-coverage-jhs-schedule.json). `NAV_CACHE` is a writable directory outside the checkout. Keep its contents between games to let each player reuse navigation observations for the same level and rules.

```bash
mkdir -p "$NAV_CACHE"
arena --transfer-build "$TRANSFER_BUILD" --pace-rate 2 --duration 90 \
  --mode ctf --weapons guns --force on --map c1.jkl \
  --episode-file "$OWNED_CTF_GOB" \
  --episode-sha256 da98fe3fc769168f1bb562cc1f6532560b12d8e920fd6c34586d69b424b5b1fc \
  --map-sha256 349fb5beffba7c84fd573fe1184f3fbb569d4fcdad07d2d9b26fcb8afdb849e0 \
  --nav-cache "$NAV_CACHE" --policy-registry "$REPO/bots/models/red_pickup_registry.json" \
  --registry-side dark --camera follow --output "$RUN_ROOT/ctf-first-visit"
```

Choose `ffa`, `tdm` or `ctf`, `guns` or `sabers`, and Force `on` or `off`. For an authored custom multiplayer episode, use `--custom-build "$CUSTOM_BUILD"` in place of `--transfer-build "$TRANSFER_BUILD"`. Supply the local GOB, its SHA-256, the map name and the SHA-256 of the actual JKL entry. The custom client verifies the archive at discovery and verifies the loaded world before it applies the first control. A CTF episode also needs matching flag bindings. On an unfamiliar map the bot starts with Red's movement planner. The registry can enable a learned pickup decision for an exact, qualified map and ruleset. CTF flag decisions and saber combat stay with Red. [Policy registry](../bots/models/red_pickup_registry.json)

To use the mapped entrance on Jedi's High School, set `JHS_GOB` to PeD_HeAd's original JK episode and `HINT_BUILD` to the native client built with walking hints. Give `JHS_CACHE` a new directory for the first visit. The second process uses the same cache, with Jan joining first. [Original map source and checksums](https://github.com/CodaLilitari/World-Between-Worlds/blob/codex/massassi-top50/jhs_catalog.py) · [Editable walking route](../bots/routes/jhs-school-entry.route)

```bash
mkdir "$JHS_CACHE"
jhs=(--hint-build "$HINT_BUILD" --mode ffa --weapons guns --force on
     --pace-rate 2 --duration 75 --map jhs.jkl --episode-file "$JHS_GOB"
     --episode-sha256 a62c94789c521af2746cc8378301a4940a59a24f6fb44dd4c443caacc0211b04
     --map-sha256 90e2641a58e0ec0102355dca9d3ec5eb55c4cbc9945a427227dcc8244885619d
     --route-hint "$REPO/bots/routes/jhs-school-entry.route"
     --route-hint-sha256 c9a86f5b438146d8f7c27d76f90af1d253ead33e1e0d47b748a310aad2b1f92c
     --route-hint-scope ffa/guns/force
     --nav-cache "$JHS_CACHE" --policy-registry "$REPO/bots/models/red_pickup_registry.json"
     --registry-side dark)
arena "${jhs[@]}" --output "$RUN_ROOT/jhs-hints-01-first"
arena "${jhs[@]}" --jan-first --output "$RUN_ROOT/jhs-hints-02-repeat"
```

To reproduce the platform-only control, remove the three route-hint options and replace the build option with `--platform-build "$PLATFORM_BUILD"`. The earlier `--custom-build "$CUSTOM_BUILD"` reproduces the original admission-only test. Use a separate cache and output path for each study. [Compare the three implementations](RED_TRANSFER_OBSERVATIONS.md#the-mapped-entrance)

The route file stores a level digest and a waypoint count, followed by one row per waypoint. Each row gives a sector, supporting fixture and X/Y/Z coordinates in thousandths of a world unit. Fixture `-1` denotes the sector floor. After editing the route, check it against the original episode and the stock `Res2.gob`, then pass the new file digest to the client.

```sh
python3 -B -m scripts.bot_development.analysis.jhs_route_geometry \
  --episode "$JHS_GOB" --stock "$STOCK_RES2_GOB" \
  --route bots/routes/jhs-school-entry.route --output "$RUN_ROOT/geometry-check.json"
```
