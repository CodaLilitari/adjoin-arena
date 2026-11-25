# Native dedicated server

The server is built from [codalilitari/OpenJKDF2-MotS-Fixes](https://gitlab.com/codalilitari/OpenJKDF2-MotS-Fixes), pinned to **74e4657c4f1751d09af9ad9e056acb8f41997acb** (v0.9.9), plus `crossplay-dedicated.patch`. All engine changes are on the server. The ordinary native client still uses its existing Valve GameNetworkingSockets transport. The Python supervisor adds original DirectPlay and browser endpoints through a local transport bridge.

The bundled `bin/linux-x86_64/openjkdf2` and `libGameNetworkingSockets.so` were built on Ubuntu 24.04 x86_64 with GCC 13.3.0. The current server uses a fresh full CMake Release build: all 206 application translation units and the enabled pinned bundled dependencies were compiled in a new build directory. `BUILD.json` records exact source/dependency commits, source and object hashes, sizes, build commands, and system library dependencies. This binary is not advertised as portable to every Linux distribution. Rebuild on the intended host when its libc or multimedia dependencies differ.

## Build

Install the following Ubuntu 24.04 build dependencies, then run `bash native/build.sh` from the project directory. The script clones the pinned source, obtains the pinned submodules, applies the full server patch, builds with at most four jobs, and installs the engine, GNS library, licenses, and relinking materials into this project. A separate build directory can be supplied as the first argument.

```sh
sudo apt-get install build-essential git cmake pkg-config python3-venv bison zsh \
  libgtk-3-dev libopenal-dev libglew-dev libssl-dev libcurl4-openssl-dev \
  libpng-dev libx11-dev libxcursor-dev libxrandr-dev libxi-dev libxss-dev \
  libxext-dev libxfixes-dev libwayland-dev libxkbcommon-dev libasound2-dev \
  libpulse-dev libudev-dev libdbus-1-dev libgl1-mesa-dev libegl1-mesa-dev \
  xvfb xauth
bash native/build.sh
```

The build requires network access to the source repositories and PyPI. `cogapp==3.6.0` is pinned for generated globals; the current package was built with CMake 3.31.10. The pinned engine's own CMake logic applies its existing GameNetworkingSockets 1.4.1, PhysicsFS, SDL_mixer and Ogg build adjustments. Those resulting submodule worktree changes are expected; the crossplay patch does not replace their pinned gitlinks or conceal unrelated dependency changes. The executable retains the literal `$ORIGIN` runtime library search path and the upstream Release strip step. Source, dependency commits, and build steps are pinned; byte-identical builds across different compiler/distribution versions are not claimed.

For the bundled executable, runtime packages include `libgtk-3-0t64`, `libopenal1`, `libgl1`, `libegl1`, `libcurl4t64`, `libsndio7.0`, `libssl3t64`, and a working Mesa/OpenGL/EGL implementation, plus normal C/C++ runtime dependencies. The manager sets `LD_LIBRARY_PATH` to the engine directory. The engine's headless mode still initializes graphics. The manager accepts `engine_display` values `auto` (default), `offscreen`, `xvfb`, and `display`. Auto respects an inherited display or explicit SDL video driver; otherwise it selects SDL offscreen and surfaceless EGL. Xvfb mode requires `xvfb-run` and `xauth`. Bots and the original-retail Wine adapter have separately prepared display environments.

## Optional bot client

`bash native/build_bots.sh` builds `bin/bots-linux-x86_64/jk-bot-client` from the
same pinned base with **only** `bot-client.patch`. It does not replace the
dedicated engine. Run bots through `python3 -m bots.run`; see `bots/README.md`.

`BOT_BUILD.json` records the separate executable. The bot relink archive
contains its exact objects, static libraries and LGPL libsmacker source. Extract
it into an empty folder, edit the included library if desired, and run
`python3 relink.py`. The result is `jk-bot-client-relinked`; make the packaged
GNS shared library available at runtime. Existing dependency notices apply.

The recovery build reused the published unchanged objects/static dependencies,
recompiling changed client units and restoring every existing server-modified
unit to the client source. New dedicated-only units are excluded from the bot
link. A fresh full dependency rebuild is not claimed by its receipts. See
[Bot behavior](../docs/BOTS_BEHAVIOR.md) for current qualification and limitations;
[Bot prototype](../docs/BOTS_PROTOTYPE.md) preserves the earlier milestone.

The competitive Force candidate recompiles both `jkBot.c` and
`jkGUIMultiplayer.c`, including their changed Force policy and saved-loadout
headers. Its remaining objects and static dependencies come from the verified
prior bot relink archive. `qa/bots-competitive-force-build.json` records this
incremental build, source pins, object hashes, and the matching package. This
does not by itself establish connected effects or human-match performance.

## Server changes

The patch adds an authenticated, bounded loopback TCP transport bridge. It accepts one supervisor and exposes session metadata, external peer creation/removal, canonical player IDs, and Sith packet delivery. It preserves the original GNS transport for native clients. Detailed framing, message types, ID-pool rules, and packet layouts are in `protocol.md` and the patched engine's `docs/crossplay-gateway.md`.

Dedicated startup uses its isolated working directory and requires the original game-data marker. Redirected stdin is handled without repeatedly logging a prompt. The public GNS packet source is bound to its actual connection's assigned identity. Session metadata counts fully joined remote players, including ordinary bot clients and excluding the dedicated host and unused DirectPlay surrogate slots.

Two existing serialization inconsistencies are corrected inside the server: UpdateState's light value is written as float32 to match the existing reader, and MotS absolute CreateThing's sector is read as int32 to match the retail/browser representation and existing sender.

### Host observer

The existing authenticated web panel can show a local observer camera. With
`spectator_rendering` enabled at launch, the manager supplies a private inherited
AF_UNIX frame socket and the dedicated engine retains a hidden graphics context.
The camera starts off. A host can open a free camera or follow a joined player;
closing the view or losing its viewer lease disables it. Setting the launch
option to false uses the original headless graphics lifecycle.

The observer owns a camera, with no joined identity, world thing, player slot,
collision, damage, or host-actor movement. Free movement passes through geometry;
an outside-world camera reports that condition. Follow binds to the native
peer and connection generation and reacquires the player after respawn. A
departed target leaves a free camera at its last pose. Control epochs reject
stale input, and motion expires after 250 ms without an update. The renderer
preserves gameplay visibility, COG sighting state, AI flags, animation/joint
caches, model lighting, player tint, and explosion effects across the observer
pass. Its stateful extra weapon-render hook is omitted, so some saber and weapon
cosmetics can be absent in the observer view.

Frames are bounded to 640×360 RGBA at five per second, on a separate nonblocking
channel. A pending frame finishes before another is accepted; the engine never
waits for the web viewer. Capture age survives backpressure, and frame/world/
control epochs prevent stale images being shown as current. Native GNS, retail
DirectPlay, and browser gameplay routes retain their existing packet formats
and game-data checksums. See [Observer protocol](../docs/SPECTATOR_PROTOCOL.md)
for the exact private command and frame layouts.

An optional second channel exports bounded clip-space vertices, opaque RGBA8
colours and triangle indices for browser WebGL 2 rasterization. It has its own
nonblocking socket, pending frame and five-second opt-in lease. Geometry failure
does not retire the image channel or game IPC. The image remains the default;
the native scene preparation and image render pass still run. See the exact
[JKSG protocol](../docs/SPECTATOR_GEOMETRY_PROTOCOL.md) and
[geometry qualification](../docs/BROWSER_SPECTATOR.md).

### Chat administration

The manager issues and revokes persistent administrator credentials independently
of the game process. `src/Dss/sithAdmin.c` accepts only a small set of typed host
actions from the authenticated supervisor, checks the actor's current transport
identity and connection generation, and executes ordinary kick or episode
progression messages. It exposes no arbitrary console or script operation.

Players use ordinary chat and an offline proof helper. The downloaded `.cog`
file is an inert credential container kept outside game content; it is never
loaded as a world script. Retail, OpenJKDF2 and JKWeb retain their ordinary
clients and game checksums. See [Chat administration](../docs/CHAT_ADMIN.md) for
issuance, login, revocation and the limits of manually copying challenges.

### MotS native reader profile

The pinned native client has an asymmetric absolute CreateThing implementation: it sends a 32-bit sector ID but reads 16 bits. The dedicated server therefore sends this particular field as 16 bits only to native GNS destinations. The Sith header, reliable sequence, coordinates, and object ID are preserved. Retail and browser destinations use the 32-bit representation. This conversion is a server transport operation; clients install no engine changes.

If every native client connecting to the session uses a later build with the corrected 32-bit reader, launch the manager with `OPENJKDF2_GNS_MOTS_SECTOR_BITS=32` in its environment. GNS does not advertise the client's source commit or this capability, so both native reader variants cannot be inferred automatically on one endpoint. The default profile targets the inspected pinned native version. This setting affects MotS absolute CreateThing only.

JK and MotS use separate session modes and corresponding assets. A JK executable cannot enter a MotS session merely because both endpoints use the same gateway. Matching episode, map, resource, and mod data remains necessary.

## Validation evidence

The current geometry-capable dedicated core is
`16944b47e2ceecf3f09cc2820af26372e2af8642057c2b0a963e353ff090c745`.
[Geometry build provenance](../qa/browser-spectator-native-build.json) records
two newly compiled units (`jkObserver.c` and `rdCache.c`), 204 reused application
objects and 12 reused dependency inputs. This is an incremental build against
the verified image-observer baseline, not a fresh compilation of all 206 units.
[Geometry packaging verification](../qa/browser-spectator-native-packaging.json)
checks all 218 link inputs, the literal `$ORIGIN` search path, a byte-identical
supplied-object relink and a successful independent libsmacker-source relink.

The earlier image-only core was `af0d99d232da3d77a3bbd87dde917bd824775815df9ec420411452701f29e572`.
[Native observer build](../qa/native-observer-build.json) records the fresh
206-unit build and a second clean application of the complete patch to the
pinned base. Every compiled source and all changed headers matched that
independently patched tree. The complete patch also matches the final preserved
pre-recovery patch byte for byte.

[Native regressions](../qa/native-observer-regressions.json) records all eight
existing server/bot runners, twelve observer behavior groups, and two packager
tests. These controlled tests exercise actual engine code, including read-only
render state, follow lifecycle, stale/replayed input, frame backpressure, capture
age, and sky orientation. Actual graphics and mixed-client gameplay evidence
belongs in the separate live receipts; fixture tests alone do not certify those
paths. [Native client provenance](../qa/native-client-observer-provenance.json)
records a separately configured unchanged client: all 204 original application
units freshly compiled, with the freshly built server dependency libraries
reused and no application objects reused.

The older qualification receipts below retain their original artifact hashes
and scopes.

`qa/native-jk-synthetic.json` and `qa/native-mots-synthetic.json` record actual engine world loading, an authenticated synthetic peer, full synchronization and WELCOME, and joined-human metadata changing 0 → 1 → 0. These are engine/transport checks, not retail or browser gameplay certification.

`qa/native-client-provenance.json` proves that the native test client was built from the exact unmodified base: all four modified translation units were rebuilt from their original git contents and linked with the remaining unchanged base objects and dependencies. No server changes are included in that client. Its SHA-256 is recorded in that receipt.

The earlier dedicated binary `4be9e8fa` and its byte-identical supplied-object
relink are recorded in [server-reconnect-build.json](../qa/server-reconnect-build.json).
The [identity lifecycle regression](../qa/server-surrogate-identity-regression.json)
covers retirement of used canonical identities and replacement with fresh
ordinary DirectPlay IDs, including repeated joins and delayed old messages.
Used identities remain retired across map changes for the transport session.

The [native discovery regression](../qa/server-native-discovery-regression.json)
covers a separate case: a pool-backed native connection that has only read the
initial transport descriptor may return its pristine reservation to the unused
pool when it closes. Any incoming payload, including malformed input, or any
ordinary outgoing Sith packet permanently commits that identity. A used or
uncertain connection follows the retirement/replacement path. Browser and retail
ADD operations commit immediately. Pristine discovery release emits neither a
retirement event nor a queued player-loss event that could affect the next holder.
These controlled checks and build results supplement the source-specific live
receipts; the earlier [chat-admin live receipt](../qa/chat-admin-live-4be9.json)
records completed stages and pending qualification separately. Historical client
qualification and artifact hashes below remain unchanged.

The unchanged native client discovered and joined the mixed server's stock JK `JK1MP/m2.jkl` session through GNS, was assigned a real reserved DirectPlay identity, and entered the live world alongside the original JK1.00 retail executable and published browser client. `qa/native-jk-live.json` records the simultaneous active roster and deliberate movement from all three clients reaching the native client, with reciprocal native movement observed in original retail. In the recorded snapshots, native versus original retail views differed by 0.127451 world units for the native player and 0.038729 world units for the retail player; exact coordinate convergence is not claimed. Both source implementations use thresholded velocity smoothing, but its role in these observed offsets was not isolated. These local checks do not certify every map, force power, mod, network condition, or engine release.

The same unchanged native executable, launched with its existing `-motsCompat` option, also joined original retail MotS and the unchanged published browser build simultaneously on `JKM_MP/mdm02_freezer.jkl`. This check used free-for-all, rank 7, and the default Jedi personality. `qa/native-mots-live.json` records active rosters, applied movement, chat, and actual projectile entities in both directions between native and retail, and between native and browser. The browser independently observed six distinct native pistol projectiles; native independently observed five distinct browser pistol projectiles. A native world death and ordinary respawn during normal movement propagated to original retail, including health 100 after respawn and deaths 1 / suicides 1 / score −1. The recorded native-versus-retail position offset after respawn was 0.105607 world units; its cause was not isolated. Initial across-room shots did not reduce browser health or shields, so this evidence does not establish direct player-to-player damage or kill credit. MotS team/class models and other maps remain outside the qualification.

The standalone `src/Tests/gateway_bridge_test.cpp` passes under AddressSanitizer and UndefinedBehaviorSanitizer: fragmented authentication, 200 coalesced frames, replies, length bounds, wrong token rejection, and disconnect callbacks. Compile from the patched checkout with:

```sh
g++ -std=c++17 -O1 -g -Wall -Wextra -Werror \
  -fsanitize=address,undefined -Isrc src/Tests/gateway_bridge_test.cpp \
  -o gateway_bridge_test
./gateway_bridge_test
```

## Licenses and relinking

The engine's exact original license and bundled dependency notices are under `licenses/native/`. Original game archives, game executables, ISOs, Microsoft runtimes, and player data are excluded from this package. The server patch retains the engine license; new integration/build scripts use the project license.

`relink-linux-x86_64.tar.gz` includes all 206 application objects (including the
observer), linked static libraries, the statically linked LGPL libsmacker's
corresponding source, original link command, and a `relink.py` utility. Extract
the archive into an empty directory and use a matching compiler/distribution.

- `python3 relink.py` recompiles the included libsmacker source, then links the
  application. Edit the library source before running this command to use a
  modified version. This remains the default behavior.
- `python3 relink.py --supplied-objects` skips the library recompile and relinks
  all supplied objects unchanged. Use a fresh extraction for this check if the
  default command has already replaced the three libsmacker objects.

Both modes preserve the final link flags, including literal `$ORIGIN`, and
repeat the Release strip step. They produce `openjkdf2-relinked`. Place the
packaged `libGameNetworkingSockets.so` beside it, use the manager, or set
`LD_LIBRARY_PATH` to that library's directory.

[Current geometry packaging verification](../qa/browser-spectator-native-packaging.json)
verifies every one of the 218 archived object/library inputs. The supplied-object
output is byte-identical to the packaged core. The default source-rebuild path
also completed successfully; its output hash is
`1f1dd05cd35e151ca8ebb3dc59b0df146ed8d6a51d4b0a9f1c9e18dcd04e8449`.
That mode uses its documented smaller compiler option set for libsmacker, so
byte identity is not promised. Full native source can also be rebuilt using the
pinned source and patch above. The [earlier image-only packaging receipt](../qa/native-observer-packaging.json)
is retained with its original artifact hashes.

## Rebuild the planner-GO research client

Both comparison modes use the same Linux x86-64 executable. Set
`JK_BOT_PLANNER_QUARANTINE=0` to observe the physical hold while the normal
policy runs and `=1` to hold the policy clock, planning and perception
callbacks until the same player enters and leaves the authored physical hold.
The client observes both actor flags, gravity, collision, slot, world and player
signature. Its held and released markers include the native game clock and
the policy clock. In mode 1, passive Force inventory observations use the
continuous game clock throughout the run.

Use the native engine checkout at `74e4657c4f1751d09af9ad9e056acb8f41997acb`
with this repository's `native/bot-client.patch` applied. Generate its header
from the **native** checkout. The commands below assume the repository root as
working directory and an external, writable `WORK` directory. `ENGINE` is the
path to the bot-patched checkout. Python 3.12+, cogapp 3.6.0, GNU patch, a
Linux C/C++ toolchain, and the system libraries named in the relink archive's
`link.json` are required.

```sh
python3 -m cogapp -d -D "symbols_fpath=$ENGINE/symbols.syms" \
  -D "project_root=$ENGINE" -D embedded_resources= -o "$WORK/globals.h" \
  "$ENGINE/src/globals.h.cog"
python3 native/build_planner_go.py --source "$ENGINE" \
  --globals-header "$WORK/globals.h" --output "$WORK/planner-client"
```

The build checks 224 native source hashes and the packaged relink inputs,
recompiles the bot driver's translation unit, then compares the result with
`planner-go-build.json`. It writes `jk-bot-client`, the matching
`libGameNetworkingSockets.so`, and a receipt in the fresh output directory.
The recorded toolchain is Ubuntu 26.04 x86-64, GCC/G++ 15.2.0-16ubuntu1 and GNU
ld 2.46. The paired studies use the binary with SHA-256
`885234aa2c9de16406f9c01da5bfefe733d65777d86edf7a89336cf255561b69`.

[Native patch](planner-go.patch) and [build receipt](planner-go-build.json)

## Paced native training images

The Linux training build produces a dedicated host and a planner-GO bot client
for local instrumented duels. Both pace conditions use the same host image,
the same client image for both seats, and the original networking libraries.
The ordinary server distribution remains the default when launching a game.

Run the rebuild on x86-64 Linux with the Ubuntu toolchain identified in the
[pace receipt](pace-build.json), the two packaged relink archives, the pinned
bot-patched engine sources, and the generated `globals.h` used by the planner
build above. Each `--source` is a candidate root containing `src/`. The
builder checks the original input hashes and the exact rebuilt planner object
before inserting the four timing hooks. Use a fresh output path outside a
checkout for each rebuild.

```sh
python3 -B native/build_arena_pace.py \
  --source /path/to/bot-patched-engine \
  --globals-header /path/to/generated/globals.h \
  --output /outside-checkouts/pace-build
python3 -B native/tests/test_arena_pace_clock.py
```

The launcher selects `host/openjkdf2` and two copies of `bot/jk-bot-client`
from that output, with the matching `libGameNetworkingSockets.so` for each
image. Set `ADJOIN_PACE_RATE=1` or `2` on every engine process and pass
`ADJOIN_PACE_ROLE=host`, `dark`, or `light` for its assigned seat. Keep the
host and both clients on the same rate.

Each outer gameplay step advances the stock engine clock by exactly 34 ms.
Both the integer millisecond timer used by COGs and microsecond input used
for fractional physics time derive from the same virtual step. The stock
physics accumulator, control sampling, COGs and multiplayer update order
execute normally. At 1× a step is scheduled every 34 real ms and at 2×
every 17 real ms. Each process has its own deadline. After a substantial
stall the scheduler restarts from current wall time and preserves every
simulated step. This intentionally preserves tick size under CPU pressure.

The networking library, OS delivery, observer, leases and launcher continue
using wall time. The dedicated engine can still need a graphics context
without a visible main window. These modes establish neither a synchronized
packet schedule nor a deterministic multiplayer replay. Compare the
instrumented 1× case to the ordinary runner when calibrating behavior.
For the first frame and every fifth frame each engine emits `ARENA_PACE`
on stderr with its role, PID, rate, frame counter, actual game milliseconds,
undilated Linux monotonic nanoseconds, configured step and measured applied
milliseconds. Qualify achieved speed on all three engines during the same
post-GO interval. The standalone clock test checks integer and fractional
steps against each archived clock object, separately from full-match evidence.

[Clock implementation](arena_pace.c) · [Verified relinker](build_arena_pace.py)

## Red’s headless teacher and local neural policy

The research client starts with Red’s full 14-file tactics patch from
`f453778a3cf670dea43c44315786ae4afc8ae440` in JK Cross Server. The build
uses that revision’s bot base patch and relink archive. It recompiles both
the AI driver and the input device translation unit so Red’s ordinary
mouse-look aiming path reaches the game. Both teacher and neural seats run
the same executable. Use the paced dedicated host from the preceding recipe.

Export that exact revision’s `native/BOT_BUILD.json`, `native/bot-client.patch`,
`native/bot-tactics.patch`, `native/bot-relink-linux-x86_64.tar.gz`, and its
`bin/bots-linux-x86_64/{jk-bot-client,libGameNetworkingSockets.so}` into
one directory preserving these paths. Supply the bot-patched engine source
at Red’s engine base `74e4657c4f1751d09af9ad9e056acb8f41997acb` and its
generated `globals.h`. Multiple `--source` paths are supported. The builder
requires the manifest hash of each source and archived input and verifies the
result against the retained receipt. The qualified Linux x86-64 toolchain
versions and generated-header hash are in that receipt. Install OpenSSL
development headers/library alongside the normal linker dependencies.

```sh
python3 -B native/reproduce_red_build.py duel \
  --red-export /path/to/frozen-red-pr3 \
  --source /path/to/bot-patched-engine \
  --globals-header /path/to/generated/globals.h \
  --output /outside-checkouts/red-build
python3 -B native/tests/test_red_policy.py
```

Set `ADJOIN_RED_TRACE=1` on both owners. Leave the two model variables unset
for the teacher. For a neural seat set `ADJOIN_RED_MODEL` to the weights file
and `ADJOIN_RED_MODEL_SHA256` to its lowercase SHA-256. The client hashes,
parses and freezes the same bytes at configuration time. A failed load selects
the teacher and emits `mode=fallback status=rejected`. Red’s tactics remain
editable through his existing tactics controls. To change learned weights
between matches, start a new owner process with the new digest. Each owner
begins its ordinary controls on joining the stock match. Set the same
`ADJOIN_PACE_RATE` for the three processes and their individual pace roles.

The learned decision is whether to keep following an existing pickup
objective or switch to combat footwork while a visible opponent is present.
The query requires a live, still-useful item, suitable footing, and an ordinary
elite deathmatch controller. Red retains urgent moves, rescue, trap responses,
aim, weapon choice, both fire modes and Force. The script’s original decision
at that branch is to keep the route at an enemy distance of at least 0.45
world units. It can aim or shoot while keeping the route.

Each `BOT_DUEL` row records the nine integer observations before arbitration,
the original teacher decision, the decision selected by the active controller
and the final movement owner. The feature order is health, shields, distance
to the enemy, distance to the pickup, equipped weapon bin, its ammunition,
stock backpack flag, underwater sector flag and remaining route nodes.
Distances use thousandths of a world unit. A value of one in `applied` means
that same pickup retained a nonzero final movement command. `owner` also
distinguishes engagement, changed route, stationary and overridden movement.
`BOT_RED_READ` records each movement-axis value when the ordinary control
driver actually requests it, keyed by owner, life and decision sequence.
Zero-valued axes and absent reads are distinguishable in the source logs.

`BOT_RED_JOIN`, `BOT_RED_FIRST` and `BOT_RED_APPLY` respectively mark the
native join callback, first live control tick per life and first nonzero
forward/slide axis delivered per life. Each uses the owning process’s PID and
Linux monotonic clock. `BOT_RED_STATE` records the owner's weapon possession
mask, ammunition, health, shields, kill/death counters and target on changes
and a five-per-game-second heartbeat. That log samples possessions and damage
on the owner and does not identify who inflicted every loss. Actual kills
may follow earlier decisions or another actor’s action.

[Build receipt](red-policy-build.json) · [Game integration](red-policy.patch) ·
[Loader, neural forward pass and trace implementation](red_policy.inc)

## Cross-mode navigation and local route learning

The separate transfer client keeps the measured duel executable reproducible.
Build it with the same source, globals header and Red export arguments, using
the transfer recipe and a fresh output directory. Its driver tests
also need the complete upstream `native/tests` directory in the Red export.

```sh
python3 -B native/reproduce_red_build.py transfer --red-export "$RED_EXPORT" \
  --source "$ENGINE_SOURCE" --globals-header "$GLOBALS_HEADER" --output "$NEW_OUTPUT"
python3 -B native/tests/run_red_transfer_tests.py --red-export "$RED_EXPORT" \
  --source "$ENGINE_SOURCE" --globals-header "$GLOBALS_HEADER"
```

The original engine embeds the compile-time path of `sithControl.c` in a
diagnostic. The reproduction wrapper maps that single source filename to
the exact value embedded in each frozen image. The original builders,
the executable receipts and the gameplay source stay byte-for-byte pinned.

| Competitive mode | Native evidence | Tactical controller |
| --- | --- | --- |
| Free-for-all | Teams flag cleared | Red’s default script, with the local gear decision eligible in a qualified guns configuration |
| Team deathmatch | Teams flag and stock skin-team bit 0x100 | Red’s team-aware targeting, with the gear decision eligible only for this mode’s qualified guns configuration |
| Capture the flag | Teams flag plus live bindings from the stock `ctf_main.cog` | Red’s physical lobby entry, capture, return, recover, intercept, escort and defend objectives |

Each mode can run guns or sabers and with or without Force. The stock roster
supports JK1MP’s six deathmatch levels and JK1CTF’s three flag levels at Jedi
ranks 0 through 8. Other authored maps need their own launcher/content
admission, asset checks and playtest. Unknown team configurations use Red’s
controls. The transfer client reads the engine’s team flags, replicated CTF
bindings, effective saber/Force controls and actual Jedi rank. Its
`BOT_RED_CONTEXT` also contains the SHA-256 of the level bytes opened through
the game’s resource layer and the active scope, such as `tdm/guns/noforce`.

Supply the local model path and digest as above. A model also requires a
matching `ADJOIN_RED_MODEL_SCOPE` and `ADJOIN_RED_MODEL_MAP_SHA256` to act.
The loader’s startup marker validates the artifact. The context marker
validates its scope, and the model field on each decision records who chose.
A new level initially uses Red’s controller. CTF and saber controls stay with
their own scripts. A local movement coach can use the observations to train
and qualify an appropriate model later. The fallback uses current sector
geometry and live CTF bindings. When no graph route is available it can take
a short ground-tested step, retaining the objective heading if one exists.
An unusable graph or a blocked corridor can still strand a bot.

Set `ADJOIN_NAV_CACHE` to an existing writable absolute directory per bot
profile for cross-match route memory. Raw observations stay local. Each map
digest and rules combination has an independent file including server
multiplayer flags and Jedi rank. The directed endpoints use quantized world
positions and sector identity so graph insertion order can vary with spawn.
One native writer locks a file. A second writer or inaccessible path uses
session memory. Writes replace a small file atomically.

If Red detects a stall on an identifiable directed edge it was actually
driving, the planner adds two distance-cost units on its next legal search.
Repeated failures raise that cost up to eight. Success halves the underlying
failure count. The count declines once per six wall-clock hours and expires
after 24 hours. Each map/rules file retains at most 128 directed edges.
Physical admissibility checks for gates, Force jumps, health and collision
still run on every route. A higher cost may leave the chosen path unchanged
when an alternative is unavailable.

`BOT_NAV_LEARN` records the traversal outcome and old/new cost,
`BOT_NAV_COST` records a surcharge used in search, and `BOT_NAV_FALLBACK`
records locally checked steering. `BOT_RED_NAV` records team, flag identities,
carrier thing IDs, home states, the chosen objective, scoreboard and actual
movement outputs. Its first-order measurements distinguish physical movement,
objective selection and a changed score. Objective selection alone cannot
establish a completed flag capture.

[Transfer build receipt](red-transfer-build.json) · [Native implementation](red_transfer.inc) ·
[Controlled pathfinder regression](tests/test_red_transfer_driver.c)
