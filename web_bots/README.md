# JKWeb multiplayer bots

## Join an existing JediKnight.Zone game

Use Python 3.11 or newer, a WebGL 2 browser, and a local installation of Jedi Knight: Dark Forces II. From the repository root, install the browser launcher's dependency and list currently advertised games.

```sh
python -m pip install "aiohttp==3.14.5"
python -m web_bots.join_room list
```

Pick an entry with an open slot and `"unavailable": null`. In this example, replace `42` with its numeric `id` and the two paths with your installed game directory and a writable location for the bot's local session.

```sh
python -m web_bots.join_room join --room-id 42 --seat boba --data "/path/to/Jedi Knight" --runtime "/path/to/bot-runs"
```

Open the printed `page` URL in the browser. Use **Open engine credential** to select the exact local JSON file named by `credential`. Keep the command running while the bot plays. Look for the bot's name on the host's **Player Scores** screen. Close the bot tab to leave the game, then stop the launcher with Ctrl+C.

Choose `lily`, `red`, `lilivane`, `biddy`, `t800`, or `crownbraid` for the six identities from the JHS recording. The room launcher also offers `boba`, `jan`, and `yun`. For an unmodified host, these identities use stock appearances. For example, `--seat red` appears as `Bot_Red` with the stock Mandalorian model. The bot joins the selected room as a player, using the rank advertised by the host. Add `--sabers-only` to restrict its weapon choices. For a room using a custom map, supply its matching installed episode or add `--episode-gob "/path/to/episode.gob"`. The launcher checks the GOB name and the advertised JKL. The browser uses this project's WebAssembly controller. The pickup-versus-fight weights and the mapped JHS entrance described in the native arena studies run in the native client.

This path supports open, full-game JKDF2 rooms on the Zone's WSRelay netcode 2. The room list explains exclusions such as a full session, password or required host mod. MotS, demo, and Imperial Network Protocol sessions use different game or connection paths. The player reads their own game assets locally. For testing on your own relay, append `--relay ws://127.0.0.1:PORT/relay` to both commands. [JediKnight.Zone game rooms](https://jediknight.zone/) Â· [Upstream lobby protocol and deployment](https://github.com/tristamus/jkdf2mp-bb-server/blob/main/cloudflare/README.md)

We checked public room discovery against JediKnight.Zone. We tested joining and moving on a local copy of its relay with the unmodified deployed browser client hosting Nar Shaddaa Loading Terminal. The host and bot appeared together on the stock scoreboard. The public lobby had no advertised games at the time of the discovery check. [Hostâ€™s Player Scores screen](../docs/images/jkweb-stock-host-scoreboard.png) Â· [Match evidence](../qa/adjoin-arena-jkzone-join.json)

## Host a headless game

For a headless match on a loopback relay, the host can select a stock episode
and level. This example opens the first stock CTF map with no Force and guns.
The bots request alternating team entrances by player slot. The map's stock
scripts assign teams and handle flags and scoring.

```sh
python -m web_bots.headless host --relay ws://127.0.0.1:8080/relay \
  --episode JK1CTF --map c1.jkl --mode nf-guns --host-seat lily --seats red \
  --room-name CtfPractice --data "/path/to/installed/JK" --runtime "/path/to/private/runs" \
  --chrome "/path/to/chrome"
```

For Jedi's High School, use `--episode-gob "/path/to/jhs.gob" --map jhs.jkl`.
The host and the joining browsers use the operator's local episode.
`headless join` and `join_room join` can also mount the selected room's
locally supplied episode. They read the selected room's Force rank from
JKWeb's lobby entry before choosing the NF or FF navigation weights.
Intermediate or unavailable ranks still allow ordinary play and leave
the persistent NF and FF banks untouched.
Each seat reports its navigation memory as `enabled`, `disabled`, or `degraded`
in `/status`. A damaged database affects its own seat only. After repairing
that seat's database, opening its browser again retries the connection.
The browser host automatically enables teams for the stock `JK1CTF` episode.
Custom CTF hosting under another GOB name needs support for its team flag.
`--mode ff-sabers` or `--mode nf-sabers` sets the bots' weapon rules.
The separate `--model-gob` option supplies roster artwork.

Two-seat loopback trials exercised the original JHS episode with the 16-bit
roster, both no-Force deathmatch formats on Canyon Oasis, and C1 with bots
on opposing stock teams. Both C1 browsers reported the same two red-team
captures. The receipt includes per-seat models, camera flags, weapon inputs,
coach acknowledgments and native item-collection events.
[Browser gameplay and rebuild receipt](../qa/jkweb-competitive-rebuild.json)

In a 100-second C2 no-Force sabers match, both clients reported three Red
captures and one Gold capture. On C3, two 105-second full-Force matches
(sabers and guns) reached opposing team assignment and moved toward the
enemy flag. Both ended without a recorded capture. On the guns run both
players stayed in the same respective sectors over their final five
ten-second checks. [Windows C2 and C3 match telemetry](../qa/windows-stock-ctf-c2-c3.json)

## Private four-bot arena

This launcher runs the bot-enabled **current JKWeb browser engine**. Lily's browser hosts the game and the other three browser engines join through a private instance of the upstream relay. The match runs on stock JK1MP Canyon Oasis. The default is full Force with guns (`ff-guns`). The browser clients execute gameplay and ordinary multiplayer traffic. The external companion can observe or issue expiring strategy requests through a separate local API.

## Start the arena

Use Python 3.11 or later with `aiohttp`, a WebGL 2 browser, an installed copy of JKDF2, and the bot-enabled `openjkdf2.js` and `openjkdf2.wasm` pair from the same build. The default engine directory is `bin/bots-jkweb`. Select another with `--engine-dir`.

Supply `relay/relay.py` from the upstream `tristamus/jkdf2mp-bb-server` revision `642afa116f392e5734bad742bfd77c65119a0c52`. Its SHA-256 is `c7d24a708e90ad827952f11c18f1095fdb37ceb95128f0820b76df481da18619`. It runs locally in a child process. The launcher accepts the script path explicitly. [Pinned relay source](https://github.com/tristamus/jkdf2mp-bb-server/blob/642afa116f392e5734bad742bfd77c65119a0c52/relay/relay.py)

From the repository root:

```sh
python -m web_bots.serve --data "/path/to/installed/JK" --relay-script "/path/to/relay.py" --runtime "/path/to/private/runs" --room CanyonPractice
```

Choose a match format with `--mode`. Each of the four browsers receives the same format at startup.

| Mode | Stock rank | Bot combat policy |
| --- | --- | --- |
| `ff-guns` (default) | 8 | Full Force and normal stock weapon decisions |
| `ff-sabers` | 8 | Full Force and saber-only weapon attacks |
| `nf-guns` | 0 | No Force and normal stock weapon decisions |
| `nf-sabers` | 0 | No Force and saber-only weapon attacks |

In full-Force sabers, the bot can still use stock offensive Force powers. The saber restriction governs weapon attacks. Stock game rules still determine what a player can pick up, damage, and how fast a player moves. All four formats disable the bot's fists-as-peace convention for this competitive arena. The launcher records the selected mode in `run.json` and reports it at `/status`.

Use `--model-gob /path/to/cosmetic.gob` to stage a privately supplied cosmetic archive containing `dlil.3do` and `dlil.snd`. Lily uses those resources. All four clients mount the same archive under the same mod path. Without it, Lily uses a stock model and sound. Lily uses the stock red saber materials through the normal multiplayer character profile. The launcher treats the supplied GOB as trusted mod content; prepare a cosmetic-only archive when retaining stock game rules. The only retail files it serves are the local installation's `resource/Res1hi.gob`, `resource/Res2.gob`, `resource/jk_.cd` and `episode/JK1MP.gob`. These routes require a seat credential. Each browser gets its own in-memory copy and profile.

The launcher chooses free loopback ports. Its first output line identifies the run directory and game origin. That directory contains `run.json` with all four page URLs. Open the host first at `/bot/lily`, then the joiners at `/bot/boba`, `/bot/jan` and `/bot/yun`. Each page accepts the corresponding private JSON file from `engines/`. The service and current relay stay on the local computer. Keep their credential files local.

For automated private sessions, create one fresh browser context per seat. Read the matching engine credential in the local harness and set `window.__JK_BOT_TOKEN` through a context initialization script before navigating. The page consumes and deletes this value at startup. Tokens are excluded from page URLs. Every page reads its own assets on boot. A replacement browser can reclaim an inactive seat after eight seconds without engine heartbeats. Its first state advances the companion world fence and invalidates the previous controller lease.

## Observe, speak and record

`GET /status` on the private game origin reports each seat's last joined state, slot and network ID, position, kills/deaths, renderer information, model, view flags, and recording progress. Four distinct joined seats are evidence of a four-client game. The browser's initial page load alone only confirms that the interface opened. View flag 1 indicates active game rendering, 2 indicates third person focused on the local player, 4 indicates engine acceleration, and 8 indicates the software rendering path. Check the actual WebGL renderer separately to distinguish hardware from a driver such as SwiftShader.

For a bounded diagnostic run, set `JK_BOT_TRACE_FORCE=1` in the arena server environment. This enables own Force state, equipment-plan and firing-input traces in each bot console; requests do not establish successful casts, shots, hits or pickups.

Companion credentials live under `companion/` and grant observation or control of a single bot. The game-facing credentials in `engines/` serve a different purpose. Use `python -m bots.companion_cli --credentials /path/to/run/companion/lily.json observe` to inspect Lily's state. The hub supports the same [lease, strategy and chat operations](../docs/COMPANION.md) as the native launcher. Enable outbound private-match chat explicitly with `--companion-chat`.

Select **Record 120 seconds** on Lily's page to capture the game canvas at a requested 30 fps. The recorder connects to the engine's active OpenAL master gain when browser audio is available. It reports the number of audio tracks actually captured. A harness can request up to four minutes with `await window.jkBot.startRecording(240)` or `--record-seconds 240` on `launch_chrome`. The page button still records two minutes. The server appends sequential bounded WebM chunks in the private run directory. A completed file is reported in `/status` under `capture.filename`. Interrupted recordings retain a `.part` suffix. Check the finished file's streams, duration and visible player model before using it as a demo.

If the recorder stops sending chunks for ten seconds, or Lily's browser instance restarts, the host closes the incomplete file and frees the recording slot. A late chunk cannot append to a newer recording. The incomplete file remains available for inspection. The local relay connection and HTTP upgrade have a five-second timeout; an established game WebSocket has no match-duration timeout.

The local frame bridge transfers bounded datagrams outside the engine tick. For each batch the browser translates command expiration using the exact native Emscripten monotonic clock before the poll, plus the remaining lifetime at the server. This conservatively includes the round trip and preserves the native lease limit even when the two clocks have different origins.

The separate Cross Server adapter for unchanged classic browser clients continues to target its pinned historical build. This browser-hosted arena uses the current upstream relay protocol. Results for either setup belong with the exact engine build, relay revision and client combination tested.

### Challenges and game chat

Use `--private-duels` with `web_bots.headless host` or `web_bots.serve` to enable JKWeb's private saber challenges in a peer-hosted free-for-all. In a game hosted by someone else, the host controls this rule. An eligible player equips a saber, approaches a bot in sight and types `/duel <slot>` in the game chat. The bot equips its saber if necessary and acknowledges the incoming offer through JKWeb's duel protocol. Host range, sight, equipment, power-effect and timeout checks still apply. JKWeb excludes team games and CTF from private duels.

A browser bot can send a character line after joining, scoring or dying, or an occasional ambient remark. Its usual interval is 90–150 seconds. Public game chat delays its next line. Use `--no-taunts` to silence these lines across the launched roster.

A coach can read a bot's public chat while automatic tactics continue. Run `python -m bots.coach_seat --run <headless.json> --seat red --control <private-directory>`. Incoming messages appear as `chat` records with player slot and network ID in the coach log and in the control directory's status file. Start the host or join launcher with `--companion-chat` to enable replies, then type `say On my way.` at the coach prompt or append the line to `commands.txt`. Acknowledged replies, rejected replies and tactics have independent status. The current learning window continues across a reply.

### Verified private sessions

On Canyon Oasis, Red accepted a challenge from Darth Lilitari once with both seats configured for sabers and once while carrying a Bryar pistol in a guns-configured seat. In the second match she equipped her saber and both clients reported the duel result. Both coaches read and replied through public game chat, heard the other bot's character line and continued grading tactics.

An 86-second repeat on the combined engine produced one challenge, one automatic acceptance and a win for Red reported by both clients. Both coaches acknowledged their replies, received the other player's words and graded two tactics windows apiece. [Results from all three private matches](../qa/jkweb-browser-duels-chat.json)

The [final live receipt](../qa/bots-jkweb-companion-live.json) records two
separate four-player runs of runtime `42154174`. The first produced a
120.0155-second third-person recording with the supplied cosmetic model,
hardware WebGL and game audio. During the full session, Lily equipped the
stormtrooper rifle, bowcaster and repeater; Boba and Jan equipped concussion
rifles. The live navigation graphs reported 39 of 42 pickups reachable.
These observations include warmup and the hold after capture, so they do not
describe only the two-minute clip. Reachability is a planned route, not proof
that every route was traversed successfully.

In the second run, the engine acknowledged a companion strategy and one chat
message as applied in Lily's current world and life. All three other players
independently received the message. The recording itself is autonomous and
does not contain this separate companion test.

The [additional format receipt](../qa/bots-jkweb-formats-live.json) covers
four-player FF Sabers, NF Guns and NF Sabers sessions on runtime `91a1265`.
No-Force observations had zero active Force masks. The source regression
suite separately checks the saber-only attack guard; a selected weapon sample
alone cannot identify every weapon attack between observations.

These are private Canyon Oasis integration checks. They do not establish
strength against skilled humans, public-lobby interoperability, reliable
navigation from every spawn, or mastery of every stock map.

The [recording follow-up](../qa/bots-movement-force-followup.json) records two
execution problems found by reviewing that demo. Combat and recurring sounds
could keep control of movement during wall stalls or delay the decision to seek
air. Recovery now temporarily gives navigation control, preserves the heading
needed for a jump, and penalizes only a route it actually drove unsuccessfully.
The new regression exercises the normal bot tick; the earlier aligned water-exit
replay had started after route selection and missed this arbitration failure.

Two subsequent live trials exposed deeper shaft failures. Recovery now credits
vertical progress, seeks air earlier, and plans around the browser's actual
control and physics cadence. The bot uses normal upward-facing swimming and
surface jumps, preserves the shore route through a brief breach, and can clear
crouch through an ordinary hop. A dry approach also walks to its water-entry
anchor instead of repeatedly discarding a still-distant opening.

The later sector 42 pool failure exposed two more gaps. Swim links now require
clearance for the player's full body. When a blocked route leaves a swimmer
needing air, a clear surface directly above is an immediate escape option. Bank
prediction also checks the engine's wider floor-contact sweep, so a supported
rim landing is not discarded just because a ray through the player's center
misses the bank. An intervening standable object still blocks that prediction.

The follow-up receipt retains the failed intermediate trials and explains the
limits of the original simplified fixtures. An independent replay using stock
engine collision, surface capture, sector transitions, drowning and controls
reached sustained dry footing in all 36 shaft cases. The three recorded pool
states also reach dry ground; the previous build drowns from all three on the
same replay. The [reusable runner](../native/tests/stock_water_replay/README.md)
accepts the observed control interval and initial wet sector. Actual browser
multiplayer qualification is recorded separately.

Stock multiplayer permits pulling the Bryar. Active Absorb prevents the
disarm, and repeated requests against an unchanged weapon were wasting Lily's
mana. The bot now checks the intended target again at release and backs off
repeated Pulls on the same unchanged opponent weapon. A known weapon change or
new life clears that history. The decision uses synchronized weapon changes;
the victim's stock script remains authoritative about immunity and disarming.

Seeing now requires local Blind or an observed hostile Persuasion effect.
Ordinary engagement, unexplained damage and generic Force threats do not trigger
it. The Persuasion check requires both synchronized effect and actor invisibility
flags, so Force Jump's shared twinkle alone does not qualify. Seeing protects
against a subsequent Blind; the current Blind timer remains
under stock script control.

Charged Force Jump now includes the stock rank limit, the actual first-anchor
approach, and a checked uphill escape after a grounded movement stall. The
full-charge predictor uses body clearance, stock air drag and thrust, and
the observed browser control cadence. At Lily's recorded grounded stall,
the normal bot tick selects and lands on an upper ledge at 30 and 60 Hz. It
declines that tested jump at 15 and 20 Hz, where the current movement falls
short. The follow-up receipt distinguishes these controlled stock-script
replays from live browser observations.

## Build and relink

The engine pin is `tristamus/OpenJKDF2` `web-mp` commit
`6f6d376063954f86b8d01561aad03c26fec2e4ed` (netcode 2). Activate Emscripten
**6.0.12**, then run `bash web_bots/build.sh`. The script checks out the exact
pin, applies the [ordered source overlays](engine_patches.py) and compiles the engine using the upstream WASM toolchain.
[BUILD.json](BUILD.json) records changed-source and artifact hashes. Original
game assets are not included.

`engine-relink.tar.gz` contains the application object files, exact link arguments
and libsmacker source/license. Packaging recompiles libsmacker and verifies both
JS and WASM byte-for-byte in an empty directory. With the same compiler active, extract it to a
fresh directory, modify its libsmacker sources if desired, and run
`python relink.py`. The upstream engine and third-party licenses still apply.

The separately distributed relay can be fetched and verified with
`python -m web_bots.fetch_relay runtime/web-bots/relay.py`. For automated PC
qualification, install Python Playwright and use an already installed Chrome:

```sh
python -m web_bots.launch_chrome --chrome /path/to/chrome \
  --run-json /path/to/private/arena/run.json --record-seconds 120 --hold-seconds 30
```

Omit `--record-seconds` to keep the four browsers open for companion testing.
The launcher writes private diagnostics; an actual game and captured video must
still be inspected before reporting a successful demo or competitive strength.
