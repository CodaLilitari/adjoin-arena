# Building the navigation candidate

The distributed Linux and JKWeb engines use the overlays recorded in their packaged build manifests. The opt-in navigation candidate adds stronger Bespin rim braking, tests actual grounded support on uphill paths, and embeds the original JHS entrance route with static-platform recovery. Its shared floor query preserves the uphill collision flags and checks the actual standable fixture before crossing a fall-death sector.

Start with the **assembled source for the packaged engine**. Choose a fresh external output on a filesystem with GNU patch. Stage either target, using `native` for Linux or `web_bots` for JKWeb.

```sh
python3 -B scripts/bot_development/stage_navigation_candidate.py \
  --target native --source "$PACKAGED_SOURCE" --out "$SCRATCH/nav-candidate"
python3 -B native/tests/run_candidate_footing_tests.py --source "$SCRATCH/nav-candidate"
python3 -B native/tests/run_supported_ramp_tests.py --source "$SCRATCH/nav-candidate"
```

The command checks the packaged build inputs and three assembled engine files against their recorded hashes. On private copies it reverses the two superseded overlays, then applies the candidate navigation, ramp and entrance overlays in order. The output contains four replacement C sources under `src/AI/` and a manifest listing each operation and hash. To use the result for a build, copy those four files into a separate, complete build tree matching the input engine, then compile that tree for the selected target. Keep its engine and receipt separate from the packaged artifacts.

Windows hosts may pass the absolute path of GNU patch with `--patch-program` and a C11 compiler with `--cc` on the two fixture commands. The three source-staging tests can verify reproducibility from local assembled sources by setting `ADJOIN_PACKAGED_NATIVE_SOURCE` and `ADJOIN_PACKAGED_WEB_BOTS_SOURCE`. The test accepts `PATCH` for the path to GNU patch.

Both source targets reproduced the recorded hashes and passed the compiled footing and ramp fixtures. The original Bespin and Nar maneuvers have controlled native gameplay receipts from their individual revisions. [Candidate source receipt](../qa/navigation-candidate-source.json) · [Bespin, Nar and JHS evidence](../qa/stock-navigation.md)

The first combined native candidate produced stock-clock client `eba800ab…` and pace-enabled client `62f58e6a…`. In two private NF-guns Nar games, both owners loaded the expected executable and played. The stock launcher ran for 35 wall seconds. In the second game, all three process clocks advanced 45.050 game seconds in 22.525 wall seconds. Three more original JHS games used the pace-enabled build for 100 game seconds each. NF guns FFA met both-owner activity. The two saber games exposed a repeatable stop on the last entrance mesh, nine waypoints into the route. [Clock, image and original-spawn receipts](../qa/navigation-candidate-matches.json)

The `--jhs-landing` staging option adds a separately pinned overlay for the transition from the final entrance mesh into sector 7. Compare its staged files to the [landing source receipt](../qa/navigation-landing-source.json). The packaged engines and first candidate remain independently reproducible.

For that variant, run `python3 -B native/tests/run_jhs_landing_tests.py --source "$SCRATCH/nav-landing"` against the new staged directory. This compiles the candidate's crossing decision and tests its behavior for the known overlap, missing lateral or center footing, an obstacle, an off-center approach, the wrong mesh, an incomplete route and a hazardous destination sector.

## Run the native candidate

The `--jhs-landing-step` variant tests the next 0.055 units of travel with the full collision radius after checking the supported landing. The [source manifest](../qa/navigation-landing-step-source.json) identifies both source targets. The retained Linux build directory contains `stock/` and `paced/`, each with its own `jk-bot-client` and adjacent `libGameNetworkingSockets.so`. In the commands below, set `CANDIDATE` to that build directory, `RUNS` to a fresh external logging directory, and `CONFIG` to the server configuration used for the running private room. Its `game_data` must contain the room's original JHS GOB.

In two 100-game-second original JHS matches, all three owners who started on the bridge cleared its final lip and reached sector 7 on life 1, at game times 8.194–8.330 seconds. The other owner started elsewhere. Both owners passed the activity check in each game. The full-radius fixture also rejects a solid wall, a closed portal, a foreign portal and another body. [Original-spawn FF FFA and NF team saber results](../qa/navigation-candidate-matches.json)

For ordinary 1× play with the normal Linux bot launcher, use the stock binary. The launcher reads the configured port, checks the map identity and starts each profile on join.

On WSL, use a Linux filesystem for `RUNS` while the game is writing. A test with continuously growing owner logs under `/mnt/c` returned `ENODATA` to the launcher after both bots joined. Completed logs and receipts can be copied back to Windows.

```sh
printf '%s  %s\n' adf4e21ebb61e6674702c3752ca91d548d9e41118d0b2bbd5ac09c3a7a2c3fcc \
    "$CANDIDATE/stock/jk-bot-client" | sha256sum --check --status &&
python3 -B -m bots.run --server-config "$CONFIG" --profiles boba_fett,jan_ors \
    --engine "$CANDIDATE/stock/jk-bot-client" --runtime "$RUNS/stock" --seconds 120
```

The 2× training pair uses paced client SHA-256 `f498e71d689f5b01139752898a9a5b3981433b05de4eb28ddb252ce1fd66a5e8` and the matching paced host from `native/pace-build.json`. On an already running private 2× host, the normal launcher can start the two owners from separate terminals. Run all three within the same private network namespace. The host must start with `ADJOIN_PACE_ROLE=host ADJOIN_PACE_RATE=2`. Each launcher timeout here uses wall seconds.

```sh
ADJOIN_PACE_ROLE=dark ADJOIN_PACE_RATE=2 python3 -B -m bots.run \
    --server-config "$CONFIG" --profiles boba_fett --engine "$CANDIDATE/paced/jk-bot-client" \
    --runtime "$RUNS/dark" --seconds 120
```

```sh
ADJOIN_PACE_ROLE=light ADJOIN_PACE_RATE=2 python3 -B -m bots.run \
    --server-config "$CONFIG" --profiles jan_ors --engine "$CANDIDATE/paced/jk-bot-client" \
    --runtime "$RUNS/light" --seconds 120
```

For benchmark comparisons, the [map coverage harness](MAP_PLAY_COVERAGE.md) verifies the loaded images, host and owner clock ratios, map bytes and loadouts. The retained candidate's build receipt and matching verifier identify the exact overlay stack used by the scored runs. Its ordinary stock-launcher smoke and qualified 2× games are recorded independently. [Native match receipts](../qa/navigation-candidate-matches.json)
