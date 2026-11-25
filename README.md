# Adjoin Arena

Adjoin Arena runs competitive Jedi Knight bots headlessly on stock game physics and records their play. Jan and Boba begin playing as soon as each joins. Red’s original tactics run inside each native client. A local neural policy can take over the decision to keep pursuing a pickup or turn to fight. [Project design](docs/superpowers/plans/2026-11-24-adjoin-arena.md) · [Native build instructions](native/README.md)

## What has the bot learned?

Six matches supplied 4,948 examples from Red. In four fresh scripted matches the first model agreed with Red on 95.71% of decisions. In four corresponding games with the model driving one player, the learned players totaled four kills and six deaths. The scripted players in the control games totaled seven kills and six deaths. On Bespin, a map absent from training, the native engine recorded the model changing Boba’s movement from pickup pursuit to combat. [Model, training corpus and results by player](docs/RED_PICKUP_MODEL.md)

Practice keeps learning locally between games. In two subsequent games Jan used the previous practice model and Boba loaded the new version that Jan’s game had qualified. The match runner records which weights each player actually used. The scored comparison can therefore be repeated while practice continues. [How to run the learner](docs/RED_DECISION_EXPERIMENT.md) · [Sixteen native match results](qa/adjoin-arena-red-runtime.json)

The native arena also runs free-for-all, team deathmatch and CTF with guns or saber-only controls and Force on or off. Four stock CTF games produced eight completed flag captures. Both bots reused remembered route costs on a second visit to a held-out stock level. On Jedi's High School an editable ten-point route guides Red's controller off the raised starting pad and across three catwalks. Its first test produced two completed crossings in three encounters. [CTF, unfamiliar levels and the annotated JHS route](docs/RED_TRANSFER_OBSERVATIONS.md) · [Run the bots on your own level](docs/RUN_RED_ARENA.md)

## Starting revisions

| Branch in this repository | Starting point |
| --- | --- |
| `source/pr1-foundation` | Lilitari’s competitive JKWeb foundation, `04d482e`. |
| `source/pr2-adaptive-player` | Lilitari’s adaptive player, `a8e6bdf`. The initial `main` derives from this branch and includes the foundation. |
| `source/pr3-tactics-movement` | Red’s tactics and movement work, `f453778`. Its source overlay has a separate build procedure. |

The sibling implementations have outstanding engine and browser integration work. Their original commits, notices and build receipts are retained. The server launchers, packages and updater described below belong to the inherited JK Cross Server baseline. Adjoin Arena has its own research history and has not issued a packaged release. Game files stay with their owners. [Source attribution](NOTICE.md)

## Run the pacing experiment

Use Linux, the patched engine source and native build described in the [stock-water fixture guide](native/tests/stock_water_replay/README.md), and your own Canyon Oasis JKL. Supply a new directory outside Git for the physical traces and timing receipt. This example runs the same committed start three times per mode.

```sh
python3 native/tests/stock_water_replay/pace_parity.py \
  --source "$PATCHED_SOURCE" --build "$NATIVE_BUILD" --map "$OWNED_JKL" \
  --case pool-90 --yaw 0 --samples 3 --output "$EXTERNAL_OUTPUT"
```

The script builds one fixture and uses it for both modes. Use `--help` for the prebuilt fixture option. Timing covers process start to exit, including initialization and trace output. The large traces and owned map stay outside Git.

### First measured result

The same Canyon Oasis water exit ran three times at 1× and three times uncapped on Ubuntu under WSL, using GCC 15.2.0 and the PR #2 web engine sources compiled as a native fixture. All six runs produced byte-identical start, input and state traces across 268 control ticks and 1,608 physics steps. The actor reached sector 10 with 100 health after 10.720 simulated seconds and 38 consecutive grounded steps.

Median elapsed time fell from 10.798 seconds (range 10.748–11.453) to 0.667 seconds (range 0.617–0.918), a **16.19× speedup for this single-actor case**. Timing includes process startup, initialization and trace output. The two-player series below first establishes an ordinary-speed baseline and then measures a matched 2× opening. [Six-run receipt and source hashes](qa/adjoin-arena-m0-pool90.json)

## Two-player Canyon Oasis baseline

A native dedicated host and two ordinary native bot clients played two 55-second, full-Force guns duels on stock Canyon Oasis. Both seats pursued the map's concussion rifle in each run. The sparse status reports and fire-input reports did not show either seat selecting or firing it. The first gear choices and the sectors, weapons and goals observed at 10 seconds differed across the two runs. [Comparison and input hashes](qa/adjoin-arena-native-duel-1x.json)

Each run includes a 640×360 native host follow-camera clip. The camera can intersect the followed player's body and obscure its actions. [Run and compare a duel](scripts/bot_development/legacy/README.md#repeat-a-native-canyon-oasis-duel)

### Controlled rifle opening

A private test variant places each bot at a known stock start and restores its normal respawn mask immediately. Boba starts in sector 41 near the rifle alcove. Jan starts in sector 18. The game reports the local player's rifle inventory ten times per simulated second. A stationary host camera looks into the alcove from outside, giving an unobstructed view of the pickup.

In two runs Boba's first rifle inventory gain appeared at 1.124 and 1.125 seconds on his local game clock. He later requested alternate fire in each run. The launcher joined the players in sequence. Boba had already collected the rifle when the camera first reported both players present. These results qualify placement, acquisition and recording. [Controlled opening receipt](qa/adjoin-arena-controlled-opening.json)

### Shared start for the rifle opening

The optional ready gate holds each player's position, facing and collision state at the assigned start until both clients report ready. Slot 1 broadcasts the release, and the host records a separate acknowledgement from each player. Both bots can still choose routes during the hold. Each player's pickup time is measured from its own local release.

In two 1× runs, the host received the release acknowledgements 40 and 20 milliseconds apart. Boba first acquired the concussion rifle 9.418 and 9.792 simulated seconds after his release. Both times the first gear plans were already different during the hold. Boba chose the concussion rifle (map thing 29, sector 58), and Jan chose the repeater (map thing 34, sector 59). Jan had no recorded concussion rifle gain in either run. Boba started nearer the rifle. The runs establish a repeatable acquisition from his assigned seat. Measuring a tactical advantage requires other starts and opponents. A third run using the final launcher recorded the same opening choices and a Boba pickup at 9.690 seconds. [Two-run shared-start evidence](qa/adjoin-arena-ready-gate.json) · [Final launcher run](qa/adjoin-arena-ready-gate-cli.json)

### What changed when the starts were swapped?

Boba kept slot 1, Jan kept slot 2, and the same native bots played four 22-second trials in normal, swapped, swapped, normal order. Both test episodes used the same map and sampled the owner's repeater and concussion rifle inventory. The only difference in the episode contents was the pair of starting-position masks.

| Opening position | Boba Fett, time to possession | Jan Ors, time to possession |
| --- | --- | --- |
| Sector 41 | Concussion rifle at 9.894 and 11.630 s | Concussion rifle at 1.156 and 1.190 s |
| Sector 18 | Repeater at 9.588 and 9.725 s | Repeater at 1.360 and 1.360 s |

All eight first gear plans matched the weapon subsequently gained. Times run from each player's local release to the first sampled inventory gain during the opening life. Sector 41 is 1.278 world units from the rifle. Sector 18 is 1.164 units from the nearby repeater. The planner considers pickup value, traversability and route cost. These trials isolate the effect of exchanging the two starts on the observed first choice. They leave the exact scoring calculation and the competitive value of each route open.

Acquisition speed stayed associated with the player and seat. Boba waited 3.573 to 4.391 seconds behind the gate and changed gear plans en route. Jan waited 0.138 to 0.171 seconds and kept her first gear plan until the stock pickup message in all four trials. Both planners ran during the hold. The experiment below reverses the join order. [Four-match evidence](qa/adjoin-arena-start-crossover.json) and [reproduction command](scripts/bot_development/legacy/README.md#exchange-the-starting-positions).

During the first attempt video encoding delayed shutdown and extended the native logs beyond the observation window. The four trials above use the corrected recorder, which ends capture and reaps the game processes before encoding. The measured shared windows were 22.08 to 22.10 seconds. The host and bots finished shutting down in 30 to 61 ms.

### Does the opening detour follow the player or the first seat?

Jan joined first in four new 22-second native matches. The sequence of physical starts was normal, swapped, swapped, normal, matching the earlier Boba-first series. Jan kept her light Force profile and Boba kept his dark profile. The host roster, each native client, and the recorded Force loadouts all confirmed the assignments.

| Join order | First player planning another item before pickup | Second player planning another item before pickup |
| --- | --- | --- |
| Boba then Jan | Boba in 4 of 4 | Jan in 0 of 4 |
| Jan then Boba | Jan in 4 of 4 | Boba in 0 of 4 |

Every first joiner planned another item after release and before acquiring the initially planned weapon. Every second joiner stayed on the original target through pickup. Each intended pickup was confirmed by its stock HUD message and first-life inventory gain. The median time from local release to sampled gain was 9.852 seconds in slot 1 and 1.275 seconds in slot 2. All 16 acquisitions still followed the starting position.

In these openings the target changes followed the first seat across both profiles and both layouts. Slot 1 also coordinated release and spent 3.573 to 4.391 seconds held with its planner active. Slot 2 spent 0.138 to 0.175 seconds held. The next experiment tests what happens when both planners start at release. The fixed camera shows the rifle rack. The ordered gear logs establish target changes en route. [Eight-match evidence](qa/adjoin-arena-join-crossover.json) and [reproduction command](scripts/bot_development/legacy/README.md#reverse-the-join-order).

### Starting both bots' planners on GO

This historical Canyon Oasis timing study used the research client with `--planner-quarantine on`. Each bot began planning when its own game client observed GO and regained movement. The control could already plan and track items while movement was locked. The switch is specific to reproducing this instrumented opening.

Sixteen native 1x matches crossed both join orders with normal, swapped, swapped, normal starting positions in each mode. A detour means the bot planned a different item between release and the stock pickup message for its initially chosen weapon. Pickup times run from that player's local release to the first inventory sample showing possession.

| Main experiment | Ordinary planning | Planning starts on GO |
|---|---:|---:|
| First player changed target before pickup | 8/8 | 0/8 |
| First player's median pickup | 10.064 s | 1.224 s |
| Second player changed target before pickup | 0/8 | 0/8 |
| Second player's median pickup | 1.275 s | 1.225 s |

Jan and Boba each changed targets in all four ordinary openings where they joined first. Both kept the original target in all four of their starts on GO. In a separate confirmation pair, Jan joined first at the rifle start. She acquired it in 1.122 s with planning held until GO and 14.521 s with ordinary planning. Boba collected the repeater in 1.360 s both times. All 18 matches qualified on their first attempt. All 36 opening pickups matched the weapon expected for the starting sector. Each was confirmed by a stock HUD message and an inventory gain.

The native markers locate the difference at release. With ordinary planning, slot 1 already had 3.44 to 4.39 s on its policy clock and had selected gear in every run. With planning held, both players' policy clocks read zero at release and every first gear plan came afterward. The change delays planning and perception together, so the particular timer or observation responsible for the former detour is still open. The confirmation uses the same map, and the game seeds were unrecorded. Duel strength and accelerated multiplayer require their own comparisons.

[Per-match results](qa/adjoin-arena-planner-start.json) | [Experimental design](docs/superpowers/plans/2026-11-24-planner-start.md) | [Trial schedule](qa/adjoin-arena-planner-start-schedule.json) | [Rebuild and reproduce](scripts/bot_development/legacy/README.md#compare-ordinary-planning-with-a-start-on-go)

### Do the openings carry over to double speed?

Yes for the observed gear decisions. In 16 headless matches, Jan and Boba kept the same target through pickup in every paired comparison. Each player chose the concussion rifle when starting in sector 41 and the repeater when starting in sector 18. Both starting layouts and join orders were tested twice at each speed. Each bot started planning at its own physical GO.

| Eight matched 1×/2× pairs | Result |
|---|---:|
| Same first target, target sequence and weapon collected | 16 of 16 player comparisons |
| Identical release-to-possession time on the owning game clock | 4 of 16 |
| Within 0.10 game seconds | 16 of 16 |
| Median absolute time difference | 0.034 s |
| Largest absolute difference | 0.068 s |

The median signed difference (2× minus 1×) was zero. Boba's largest difference was 0.034 s and Jan's was 0.068 s. Pickup times come from the first sampled inventory gain after local release, corroborated by the stock pickup message. For comparison, repeated runs at ordinary speed in the earlier study differed by up to 0.068 s under the same join order and layout.

The research host and both clients use 34 ms simulation steps at each pace. The 1× control schedules a step every 34 real ms and the 2× condition every 17 real ms. All 48 process measurements covered 22.100 game seconds. That took 22.100 and 11.050 wall seconds respectively at the median. Across the shorter release-to-pickup intervals the two owners also independently measured the intended pace. Including startup, joins and spectator-video processing, median launcher time fell from 29.91 to 16.76 seconds, a 1.78× speedup.

Use 2× for repeated measurements of this opening. Keep 1× as the comparison for new scenarios. The game seeds were unrecorded, and these observations end at the opening pickup. All 16 scored runs qualified on the first attempt. Two successful pilots and an earlier host-loading timeout before either player joined were kept separately. The matches ran in a loopback-only Linux network.

[Matched outcomes and measured clocks](qa/adjoin-arena-opening-pace.json) | [Frozen trial schedule](qa/adjoin-arena-opening-pace-schedule.json) | [Rebuild and reproduce](scripts/bot_development/legacy/README.md#run-the-same-opening-at-normal-and-double-speed)

## Inherited JK Cross Server documentation

A dedicated JKDF2 / Mysteries of the Sith host with a small browser control panel and server-side adapters for original DirectPlay, native OpenJKDF2, and the published JKDF2Web client.

**Development build. Read `docs/QUALIFICATION.md` for the exact clients and checks completed.** An actual OpenJKDF2 game simulation drives the session. Clients do not install an engine patch. JK and MotS are distinct session modes.

## What is included

- Python administration: start/stop, saved settings, stock/custom episode catalog, map selection, limits, log output, file preflight and isolated run directories.
- Persistent admin credentials for ordinary player chat commands, with explicit key issuance/revocation, an offline proof helper, and server-executed kick/next-level actions. See [Chat administration](docs/CHAT_ADMIN.md).
- GitLab release checks on startup and every six hours, verified package installation, optional automatic installation between sessions, and rollback recovery.
- A compiled Linux x86-64 dedicated engine, built from the pinned OpenJKDF2-MotS-Fixes source with server-side transport changes.
- A compiled Windows 32-bit DirectPlay bridge and its C source. On Linux it runs through Wine with a compatible original DirectPlay runtime.
- A Python WebSocket/WebRTC gateway with custom episode and active-mod downloads, plus a hash-verifying fetcher for the unchanged published browser client.
- Source patches, build instructions, tests, and qualification receipts.

Commercial game archives, retail executables, DirectPlay DLLs, and ISOs are not included. Point the server at your installed game data. Browser players select their own game data through the existing client.

## Downloads for Windows, Linux and macOS

The [0.4.0-dev release](https://github.com/CodaLilitari/jk-cross-server/releases/tag/v0.4.0-dev)
is also available on [GitLab](https://gitlab.com/codalilitari/jk-cross-server/-/releases/v0.4.0-dev).
All downloads include the bots, chat administration and spectator features on main.

| Host | Package | Runtime |
| --- | --- | --- |
| Windows | `JK_Cross_Server_0.4.0-dev-windows-docker.zip` | Docker Desktop running Linux containers |
| macOS | `JK_Cross_Server_0.4.0-dev-macos-docker.zip` | Docker Desktop; Apple Silicon uses amd64 emulation |
| Linux x86-64 | `JK_Cross_Server_0.4.0-dev-linux-x86_64.zip` | Native Ubuntu 24.04-compatible runtime, or Docker |

See [platform setup and launch commands](docs/PLATFORMS.md). Windows and Mac
packages are Linux-backed launchers, not native engine ports. The existing
`JK_Cross_Server_0.4.0-dev.zip` remains the updater-compatible package.

## Start on Linux

Use Python 3.11 or newer. The tested build environment and exact dependency pins are recorded under `native/` and `web_gateway/`.

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r web_gateway/requirements-lock.txt
python -m web_gateway.fetch_client --destination runtime/browser-client
python app.py
```

Open **http://127.0.0.1:8765**. Set the engine path to the included `bin/linux-x86_64/openjkdf2`, the game-data directory to your install containing `resource` and `episode`, and the browser build folder to `runtime/browser-client`. Read the episode catalog, select a map, save, then start.

The native engine can start without an X server using SDL's offscreen driver and Mesa/EGL. **Engine display** in Advanced settings defaults to **Auto**: it respects an existing display or explicit SDL video driver, and otherwise selects offscreen rendering. Choose **Offscreen**, **Xvfb**, or **Existing display** to select a backend explicitly. A working OpenGL/EGL implementation is still required; sound uses null/dummy drivers. Player bots and the retail Wine adapter have separate display requirements. Install Xvfb and xauth for those components on a host without a display. The panel distinguishes engine IPC connection, actual session readiness and the selected backend.

For stock JK use episode `JK1MP` and map `m2.jkl`. For stock MotS use `JKM_MP` and `mdm02_freezer.jkl`, with the MotS resource archives installed. The original data directory is not used for generated profiles or configuration. The supervisor stages data with normalized filename case and saves each run's settings and logs separately.

MotS personality sessions use advertised rank 7, which permits the tested unchanged native client to select its normal character. The panel and MotS example select this automatically. Lower ranks require ranked-Jedi mode (game flag 4096).

Optional CLI:

```bash
python app.py --config instance.json --check
python app.py --config instance.json --start
python app.py --config another-instance.json --state-dir another-state --port 8766
```

For multiple instances, assign distinct native, IPC, broker, browser, and administration ports. Retail DirectPlay also has its own legacy transport port constraints; do not assume changing the native UDP port relocates DirectPlay.

## Keep the server updated

The **Server updates** panel checks this project's published GitLab releases on
startup and every six hours. Choose **Install update** while the server is
stopped, or enable **Install automatically when the server is stopped**.
Automatic installation is opt-in and never interrupts a match. It verifies the
release, preserves local settings and game data, retains a backup, and restarts
the panel with the game still stopped.

Existing 0.2 installations need the 0.3 ZIP installed manually once. Git
checkouts use Git rather than the in-place installer. See [update instructions](docs/UPDATES.md)
for migration, recovery, multi-instance behavior, and publishing new releases.

## Host spectator view

Open **Spectator view** in the existing control panel to follow a joined player or fly an invisible camera through walls and floors. It does not take a player slot, interact with the game, or change client checksums. Closing the view keeps the match running. The Linux implementation provides a 640 Ãƒâ€” 360 view at up to five frames per second; see [controls, setup and compatibility limits](docs/SPECTATOR.md).

**Image view** remains the default. The optional **Experimental geometry (WebGL 2)** view draws the observer's validated triangle stream in the browser. It shares the same camera and player roster. This first geometry profile uses vertex colours, with no textures and approximate transparency/effects; the server still prepares and renders the native scene. See [browser geometry setup and qualification](docs/BROWSER_SPECTATOR.md).

![Host spectator view in the JK Cross Server control panel](docs/images/spectator-view.png)

## Current JKWeb bot arena

The experimental [browser bot arena](web_bots/README.md) uses the current
JKWeb engine and its netcode-2 relay. Four ordinary browser players can run
FF Guns, FF Sabers, NF Guns, or NF Sabers on stock Canyon Oasis. One browser
hosts; the other three join it. This path runs independently of the older
Cross Server browser adapter.

The bots can use privileged game-state and sound observations while submitting
normal movement, weapon, and Force inputs. The [companion bridge](docs/COMPANION.md)
lets a local controller observe a bot, issue expiring strategy preferences, and
speak through ordinary game chat. The arena guide includes the pinned build,
private setup, optional cosmetic model, and hardware capture instructions.
Competitive strength remains experimental and requires human match evaluation.

The [development tools](scripts/bot_development/README.md) preserve the recording,
trace analysis, source verification and native observation helpers used during
the bot refinements. The custom JKWeb JavaScript/WebAssembly runtime, complete
engine patch and reproducible build inputs are included in this branch.
See the [continuation checkpoint](docs/BOTS_CONTINUATION.md) for the latest trial
and remaining navigation work.

## Optional native player bots

The Linux server panel can start one to four ordinary player bots, chosen from
eight stock multiplayer identities with occasional original character chat.
Each bot runs a separate native client and uses the stock movement, weapons,
inventory, Force powers, damage, scoring and respawn rules. Retail, OpenJKDF2
and JKWeb human clients keep their existing executables and connection routes.

The panel's **Sabers only**, **Fists = peace**, and **Use Force powers** checkboxes
can be applied during a match without restarting it. Bots seek useful pickups,
choose weapons according to ammunition and range, and pursue stock CTF
objectives. Supported content is stock **JK1MP and JK1CTF, ranks 0Ã¢â‚¬â€œ8**; the
implementation remains experimental. MotS bots, passwords and mods are outside
this version's scope.

The server also preserves all authored spawn points independently of the
configured player limit. This is required by stock CTF's lobby and team spawn
masks and applies to every connection route. Normal admission still enforces
the configured limit. See [the bot guide](bots/README.md) and
[behavior, build evidence and limitations](docs/BOTS_BEHAVIOR.md). The
[earlier recovery qualification](docs/BOTS_PROTOTYPE.md) is retained with its
original executable hashes.

```bash
python3 -m bots.run --list-profiles
python3 -m bots.run --server-config config/server.json --profiles boba_fett,jan_ors
```

## Client connection routes

| Client | How it connects |
|---|---|
| Original JK / MotS | Its ordinary TCP/IP DirectPlay multiplayer UI, to the server host |
| Native OpenJKDF2 | Its ordinary network UI, to the native host and UDP port |
| JKDF2Web | This server's browser origin, serving the byte-identical published client and `/relay` |

The existing public JKDF2Web website points to its own lobby. This package serves an unchanged copy of that client at your own origin; it does not insert your server into somebody else's public lobby. See `web_gateway/README.md` for exact pins, the WebRTC route, fallback behavior, and custom-content limits.

## Browser content downloads

**Send missing custom maps and mods to browser players** is enabled by default in the panel (`web_asset_downloads: true`). Select the custom episode on the host as usual. If the server uses a mod, select its folder in **Mod folder**. On startup, the server prepares the selected episode and mod for the published client's existing transfer protocol. The **Browser downloads** panel shows the offered content, fingerprints, transfer sizes, and activity.

A browser player picks their original game data and joins through the normal multiplayer UI. The unchanged client checks the host's episode, downloads a missing or different custom archive, verifies its SHA-256, and installs it. If the selected mod differs, its existing flow downloads the mod and restarts into it. Follow the client's prompt to return to Multiplayer and rejoin the session after that restart; a missing episode is downloaded during the rejoin. The client caches downloaded content using its existing browser storage.

The server uses the upstream retail-reference scheme: byte-identical original content is represented by hashes and byte ranges that the browser reconstructs from the player's own game data. Original episodes and the MotS Remastered pack are not downloads. The Remastered pack, when active in a supported location, must already be available on the client with the matching fingerprint.

Custom assets belong in the selected episode archive or configured mod folder. Unadvertised resource overrides are rejected when preparing browser content so the server does not advertise an incomplete mod. Retail and native clients continue to install matching custom content themselves.

Disabling downloads prevents asset chunks from being sent. The server still advertises the selected mod and supplies custom-map fingerprint metadata so a browser with matching local content can join. A browser genuinely missing the custom map follows its existing download timeout. See `web_gateway/README.md` for transfer limits and exact behavior.

## Enable retail

Set the DirectPlay bridge path, enable the retail adapter, and on Linux set a Wine executable/launcher and a dedicated Wine prefix. That prefix needs a working original DirectPlay TCP/IP provider. The bridge itself contains no original game or Microsoft binaries. See `directplay/README.md` for tested runtime setup and precise provenance.

Mixed sessions reserve DirectPlay identities for native/browser participants. The engine uses those real identities, so an ordinary retail peer can address them. Mixed mode supports up to 15 playing clients, shared by humans and bots. The engine adds the dedicated host separately. Stock maps may impose a lower practical spawn limit. The retail session browser also counts reserved transport identities. The administration panel's joined-player count excludes these reservations.

## Network configuration

Defaults keep administration and the browser gateway on loopback. Native GNS uses UDP 3500 by default. DirectPlay uses the original TCP/IP provider's discovery and session sockets. For an Internet host, configure the appropriate routing/firewall and browser TLS/WebSocket reverse proxy deliberately. Do not expose the administration port as a game endpoint.

See `docs/NETWORKING.md` for the endpoint table, LAN connection steps, remote administration, browser profile setup, and STUN/TURN configuration.

The browser has reliable ordered WebRTC channels and its existing WebSocket fallback. The unchanged client limits some movement updates to 200 ms when using fallback. No public STUN/TURN service is contacted by default. The native IPC and adapter broker are authenticated loopback services, not client endpoints.

Optional STUN/TURN configuration is available in the advanced panel as `web_ice_servers`. For example, a TURN entry has `urls`, `username`, and `credential` fields. Keep the array empty for direct connections. Internet NAT traversal is a separate deployment check from the local compatibility tests.

## Content and compatibility

Use the same episode and mod resources on all participants. Browser downloads establish matching custom content through the published client's existing checks. Archive hashes establish content identity; gameplay parity still depends on the participating engine versions and the mod itself. The qualification report separates stock multiplayer interoperability from missing-content download checks.

MotS has a known legacy native-client sector-field mismatch. The server adapts that field at the native edge while preserving retail/browser format. See `native/README.md` for the tested native reader and the explicit corrected-reader option. This is a server setting, not a patch installed on clients.

## Source and credit

Project direction: Andrei. Implementation and integration: Lilitari, with parallel native-engine, browser-transport, and retail-runtime collaborators. Based on work by the OpenJKDF2 contributors, Coda Lilitari's MotS-fixes fork, and Tristamus's JKDF2Web client and lobby protocol. Original game, community, and dependency authors retain their credits and licenses. See `NOTICE.md` and `licenses/`.
