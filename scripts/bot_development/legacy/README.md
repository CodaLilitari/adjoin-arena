# Earlier native development helpers

These helpers preserve the distinct native Force-observation and incremental-build
work from the first competitive-bot development session. Paths and WSL distribution
names are caller supplied. The current browser recording, transfer and analysis
tools live alongside this directory; use those for new four-browser trials.

## Observe two native clients on Linux

```sh
python scripts/bot_development/legacy/native_force_observation.py \
  --repo /path/to/jk-cross-server \
  --data /path/to/owned-jk-installation \
  --output /path/to/new-force-observation \
  --map m_boss17.jkl --duration 75
```

The output directory must be new and outside both inputs. The harness starts one
dedicated server and two real bot clients, verifies their distinct joined
identities and expected stock Force loadouts, and retains bounded numeric
observations in `receipt.json` and `force-trace.jsonl`. It copies the required game
files into a temporary private directory and cleans up its own process groups.
The original game installation is read only. Raw process logs remain in the
caller-selected output directory.

This is a Linux x86-64 native test with software/offscreen rendering and an overall
172-second deadline. It requires the packaged native server, bot and runtime
libraries. It does not qualify browser networking, rendering quality, successful
casts attributable to a specific player, or competitive skill.

## Stage an owned Windows installation through WSL

```powershell
python scripts/bot_development/legacy/windows_force_bridge.py --distro "Your WSL Distribution" --data "C:\Games\JediKnight" --repo /path/to/jk-cross-server --output /path/to/new-force-observation --map m_boss17.jkl --duration 75
```

The repository must already exist inside the named WSL distribution. `--repo` and
`--output` are absolute Linux paths; the output parent must exist. `--harness`
defaults to the sibling `native_force_observation.py`. The bridge hashes that file
before sending it and the receiver verifies the same digest before execution.

The bridge checks native runtime libraries, streams only four allowlisted game
files and the observation harness over WSL's standard input, and runs the test in
a temporary user/network namespace containing only loopback. WSL must support
`unshare -Urn`. It performs no clone, download or upload. The original Windows
installation is read only; the Linux output directory retains the numeric receipt
and process logs. Total bridge time is bounded to 300 seconds.

## Rebuild the two original native translation units

```sh
python scripts/bot_development/legacy/rebuild_native_pair.py \
  --repo /path/to/jk-cross-server \
  --source /path/to/pinned-and-patched-native-engine \
  --build-dir /path/to/configured-native-build \
  --sdl-source /path/to/pinned-sdl-checkout \
  --output /path/to/new-pair-build
```

This deliberately narrow helper rebuilds `src/AI/jkBot.c` and
`src/Gui/jkGUIMultiplayer.c`, then links them with the verified remaining object
files from `native/bot-relink-linux-x86_64.tar.gz`. It requires the original Unix
Makefiles flags, generated header, pinned SDL revision and compatible Linux
compiler/linker. The output must be outside all inputs and must not already exist.
It checks source and archive pins, hashes all retained link inputs, verifies the
expected GUI symbols and rejects recorded source changes outside the rebuilt
dependency set. It writes build receipts and an executable only in that new
directory. It does not refresh release manifests or replace packaged binaries.

The primary reproducible full build remains `native/build_bots.sh`. Use it for
changes spanning other translation units. This historical two-unit diagnostic
was retained because it reproduces the earlier bounded incremental build and is
useful when checking that particular recovery path.

## Provenance and disposition of earlier scratch helpers

| Earlier helper | Preserved form or replacement |
| --- | --- |
| `competitive-force-harness.py` | `native_force_observation.py`; behavior retained, explanatory module description updated. |
| `competitive-force-windows-bridge.py` | `windows_force_bridge.py`; fixed machine paths, distribution, output and harness digest replaced by explicit arguments and a per-run digest. |
| `engine-build-probe/rebuild_pair.py` | `rebuild_native_pair.py`; build/SDL paths are arguments; integrity checks remain active under optimized Python. |
| `engine-build-probe/rebuild_unit.py` | The verified pair builder supersedes this unverified one-unit experiment. |
| `receive_demo.py` | The shared bounded packet-transfer helper handles chunk offsets, sizes and digests without the old terminal-mode dependency. |
| `demo-review/analyze_speedvideo.py`, `analyze_trial.py`, `compare_runs.py` | Preserved in the adjacent analysis tools with caller-supplied inputs. |
| Earlier `record-*`, `transcode-*`, `export-*`, `prepare_private_update.py`, `install-private-update.py` | The shared capture/transfer tools preserve these operations with explicit inputs; per-recording paths and historical overlay payloads are not duplicate tool entry points. |
| `demo-review/companion-refinement-control.py` | `bots.companion_cli` already exposes the observation, lease, strategy and chat operations used by this recording-specific wrapper. |
| Intermediate combat, pickup, host/join and companion patch fragments | Their final source is included in `native/bot-client.patch` and `web_bots/engine.patch`; superseded fragments and baseline source snapshots are not separate runtime variants. |
| `current-jkweb-relay.py` | Unmodified upstream relay at the pin documented in `web_bots/README.md`. |
| Object directories, generated JS copies, SDKs and relink scripts inside build outputs | Current runtime files, build instructions and verified relink inputs are already packaged. |

Original helper SHA-256 values, before portability changes:

| Original | SHA-256 |
| --- | --- |
| Native Force harness | `99af029eca3084482f9842086606aef7019e98c9b1b855d01d929ff39a28df9d` |
| Windows/WSL bridge | `9aef0cf3a87094ac31bab1313909140d1a988a93f02bea37802d41dced0262ad` |
| Native pair rebuild | `475fd22c6f4d08608f32b38e531d7e7d00ea79ff3d696e4498ada27ccaa53394` |

The preservation check ran the ported pair builder against the fifth refinement
sources and reproduced the packaged native executable byte for byte:
`862e566209dae8fab218243a47455b5a5616bf98fb8d1f09fa65969f9c8519aa`.
CLI parsing, embedded WSL program compilation, literal argument transport,
allowlisted archive creation, digest rejection and malformed-response handling
were checked locally. The ported Windows bridge was not rerun as a live WSL match.

## Repeat a native Canyon Oasis duel

Use Linux or WSL2 with the packaged native runtime's libraries. Recording also needs ffmpeg and ffprobe with H.264 support. The launcher runs one dedicated host and two native clients using an owned JK installation and the shipped bot profiles. Give each run a new output directory on a native Linux filesystem outside Git. The private network namespace needs unshare and iproute2.

```sh
for run in stock-duel-a stock-duel-b; do
  unshare -Urn -- sh -c '
    ip link set lo up || exit 1
    exec python3 -B "$1/scripts/bot_development/legacy/native_force_observation.py" \
      --repo "$1" --data "$2" --output "$3" --map m10.jkl --duration 55 --arena-baseline --record
  ' sh "$PWD" "$OWNED_JK" "$RUN_ROOT/$run" || exit 1
done
python3 -B scripts/bot_development/analysis/native_duel.py \
  --first "$RUN_ROOT/stock-duel-a" --repeat "$RUN_ROOT/stock-duel-b" --output "$RUN_ROOT/comparison.json"
```

The host roster, each peer's join acknowledgement, native logs and video have separate evidence in the receipts. The clip starts after both players join and spans up to about 45 seconds. Actor positions in the client logs are rounded, usually ten seconds apart. The two client clocks start independently. An equipment plan records intent, a selected weapon records possession at a sample, and a fire-input report records a change of input mode. The engine suppresses repeated fire reports of the same mode. Health or shield decreases alone leave the attacker unidentified.

### Record the controlled rifle opening

Use the same native command and network namespace as the stock duel, with these additional flags. This example records both owners' inventory readbacks and the fixed host camera in a new private directory. GNU coreutils provides stdbuf, used to retain the COG's native console output.

```sh
unshare -Urn -- sh -c '
  ip link set lo up || exit 1
  exec python3 -B "$1/scripts/bot_development/legacy/native_force_observation.py" \
    --repo "$1" --data "$2" --output "$3" --map m10.jkl --duration 24 \
    --arena-baseline --controlled-opening --camera rifle-overlook
' sh "$PWD" "$OWNED_JK" "$RUN_ROOT/opening"
```

The launcher verifies the owner's stock episode, builds a temporary variant in its private stage, and checks the expected derived episode and map hashes. The variant adds one local COG and references it in the level. The two peers read the same content. Read the opening_observations in the run receipt for the verified spawn coordinates, restored masks, and owner-side changes to inventory bin 9. The camera's timestamps use wall time; the inventory readbacks use each seat's game clock. Compare matching events within each clock domain. The stock-duel comparison command takes unmodified stock matches.

### Release both players from the controlled starts

Run the controlled rifle command above with `--ready-gate` in place of `--controlled-opening` and a fresh output directory. Keep `--camera rifle-overlook` to see the alcove. Omit the camera for an unrecorded run. The gate requires the Canyon Oasis arena baseline and writes its own temporary episode variant. Stock and ungated trials use their original launch options.

After the stock loadout appears, each client signals that it is ready. The player in slot 1 broadcasts GO when it has seen both signals. Both clients restore control, gravity and collision, then acknowledge the same GO to the dedicated host. The result in `receipt.json` includes the players' local releases and both host acknowledgements. The bot planners run during the physical hold. For the time to first rifle acquisition, subtract the release timestamp from the first owner-side bin 9 gain on that same client's clock. The elapsed time between the host's two acknowledgements measures message arrival at the host.

### Exchange the starting positions

Give each of four matches a fresh directory and use the same duration, camera, game data and bot settings. Add `--observe-repeater` to the ready-gate command for all four. Add `--swap-starts` for the middle two. Boba remains slot 1 and Jan remains slot 2. The swapped condition exchanges their physical spawn locations. Both conditions sample the concussion rifle (bin 9) and repeater (bin 6).

From the repository root, use the four completed directories in run order to produce the comparison:

```sh
python3 -B -m scripts.bot_development.analysis.start_crossover \
  "$RUN_ROOT/1-normal" "$RUN_ROOT/2-swapped" "$RUN_ROOT/3-swapped" "$RUN_ROOT/4-normal" \
  --output "$RUN_ROOT/crossover.json"
```

The report checks the native logs and stationary camera against their recorded hashes. It includes the first gear plan and the first sampled possession of each weapon during the opening life. The pickup timer starts at each player's local release. A null timer means no gain was sampled in that life.

### Reverse the join order

Add `--jan-first` to each of the four instrumented ready-gate commands above. Keep the same normal, swapped, swapped, normal sequence and use four new output directories. Jan now takes slot 1 with her light Force profile and Boba takes slot 2 with his dark profile. In a normal run slot 1 starts in sector 41, and in a swapped run slot 1 starts in sector 18. The COG still uses slot 1 as the gate coordinator.

From the repository root, compare both four-match series in chronological order within each group.

```sh
python3 -B -m scripts.bot_development.analysis.join_crossover \
  --boba-first "$BOBA/1-normal" "$BOBA/2-swapped" "$BOBA/3-swapped" "$BOBA/4-normal" \
  --jan-first "$JAN/1-normal" "$JAN/2-swapped" "$JAN/3-swapped" "$JAN/4-normal" \
  --output "$RUN_ROOT/join-order.json"
```

For each player, the report reads the first gear plan and subsequent plans up to the stock pickup message for that weapon. A different item ID counts as a target change. Replanning a path to the same item keeps the original target. Owner inventory supplies the acquisition time. An opening without a corroborated pickup remains unobserved. The host roster, join acknowledgements and Force loadouts establish who actually occupied each slot.

### Compare ordinary planning with a start on GO

Build the client using the [native build instructions](../../../native/README.md#rebuild-the-planner-go-research-client). For the two-player Canyon Oasis ready-gate command, supply both `--planner-client "$RESEARCH_CLIENT"` and `--planner-quarantine off` or `--planner-quarantine on`. Use the same built executable, local game data, camera and 22-second observation duration in both modes. Include `--observe-repeater`. `--jan-first` controls join order and `--swap-starts` controls the physical layout. The [trial schedule](../../../qa/adjoin-arena-planner-start-schedule.json) lists all main and confirmation runs in order.

With Bash, set `REPO`, `OWNED_JK`, `RESEARCH_CLIENT` and a fresh external Linux `RUN_ROOT` to absolute paths. This example uses jq to read the committed schedule. Each invocation gets a fresh loopback-only network namespace. The shell stops on the first failed match, leaving its logs and all completed runs in place.

```bash
set -euo pipefail
mkdir "$RUN_ROOT"
schedule="$REPO/qa/adjoin-arena-planner-start-schedule.json"
while IFS=$'\t' read -r name first starts mode; do
  flags=()
  if [[ $first == jan ]]; then flags+=(--jan-first); fi
  if [[ $starts == swapped ]]; then flags+=(--swap-starts); fi
  unshare -Urn -- sh -c 'ip link set lo up && exec "$@"' sh \
    python3 -B "$REPO/scripts/bot_development/legacy/native_force_observation.py" \
    --repo "$REPO" --data "$OWNED_JK" --output "$RUN_ROOT/$name" \
    --arena-baseline --ready-gate --observe-repeater --map m10.jkl --duration 22 \
    --camera rifle-overlook --planner-client "$RESEARCH_CLIENT" --planner-quarantine "$mode" \
    "${flags[@]}" > "$RUN_ROOT/$name.log" 2>&1
  printf '%s\n' "$RUN_ROOT/$name" >> "$RUN_ROOT/qualified-paths.txt"
done < <(jq -r '.runs[] | [.name,.first,.starts,.mode] | @tsv' "$schedule")
```

From the repository root, evaluate those directories in schedule order:

```sh
python3 -B -m scripts.bot_development.analysis.planner_start \
  --paths "$RUN_ROOT/qualified-paths.txt" --output "$RUN_ROOT/planner-start.json"
```

The comparison verifies the camera, owner inventories, native gate markers and first gear plans against the raw logs. The final two runs form a separate confirmation pair. The report includes incomplete pickups and gives an opening without a confirmed pickup no credit for taking a direct route.
