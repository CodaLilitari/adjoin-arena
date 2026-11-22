# Private four-bot JKWeb arena

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

Use `--model-gob /path/to/cosmetic.gob` to stage a privately supplied cosmetic archive containing `dlil.3do` and `dlil.snd`. Lily uses those resources. All four clients mount the same archive under the same mod path. Without it, Lily uses a stock model and sound. The launcher treats the supplied GOB as trusted mod content; prepare a cosmetic-only archive when retaining stock game rules. The only retail files it serves are the local installation's `resource/Res1hi.gob`, `resource/Res2.gob`, `resource/jk_.cd` and `episode/JK1MP.gob`. These routes require a seat credential. Each browser gets its own in-memory copy and profile.

The launcher chooses free loopback ports. Its first output line identifies the run directory and game origin. That directory contains `run.json` with all four page URLs. Open the host first at `/bot/lily`, then the joiners at `/bot/boba`, `/bot/jan` and `/bot/yun`. Each page accepts the corresponding private JSON file from `engines/`. The service and current relay stay on the local computer. Keep their credential files local.

For automated private sessions, create one fresh browser context per seat. Read the matching engine credential in the local harness and set `window.__JK_BOT_TOKEN` through a context initialization script before navigating. The page consumes and deletes this value at startup. Tokens are excluded from page URLs. Every page reads its own assets on boot. A replacement browser can reclaim an inactive seat after eight seconds without engine heartbeats. Its first state advances the companion world fence and invalidates the previous controller lease.

## Observe, speak and record

`GET /status` on the private game origin reports each seat's last joined state, slot and network ID, position, kills/deaths, renderer information, model, view flags, and recording progress. Four distinct joined seats are evidence of a four-client game. The browser's initial page load alone only confirms that the interface opened. View flag 1 indicates active game rendering, 2 indicates third person focused on the local player, 4 indicates engine acceleration, and 8 indicates the software rendering path. Check the actual WebGL renderer separately to distinguish hardware from a driver such as SwiftShader.

Companion credentials live under `companion/` and grant observation or control of a single bot. The game-facing credentials in `engines/` serve a different purpose. Use `python -m bots.companion_cli --credentials /path/to/run/companion/lily.json observe` to inspect Lily's state. The hub supports the same [lease, strategy and chat operations](../docs/COMPANION.md) as the native launcher. Enable outbound private-match chat explicitly with `--companion-chat`.

Select **Record 120 seconds** on Lily's page to capture the game canvas at a requested 30 fps. The recorder connects to the engine's active OpenAL master gain when browser audio is available. It reports the number of audio tracks actually captured. A harness can start the same recording by calling `await window.jkBot.startRecording(120)`. The server appends sequential bounded WebM chunks in the private run directory. A completed file is reported in `/status` under `capture.filename`. Interrupted recordings retain a `.part` suffix. Check the finished file's streams, duration and visible player model before using it as a demo.

The local frame bridge transfers bounded datagrams outside the engine tick. For each batch the browser translates command expiration using the exact native Emscripten monotonic clock before the poll, plus the remaining lifetime at the server. This conservatively includes the round trip and preserves the native lease limit even when the two clocks have different origins.

The separate Cross Server adapter for unchanged classic browser clients continues to target its pinned historical build. This browser-hosted arena uses the current upstream relay protocol. Results for either setup belong with the exact engine build, relay revision and client combination tested.

### Verified private sessions

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

## Build and relink

The engine pin is `tristamus/OpenJKDF2` `web-mp` commit
`7a6f95c9a3399e59acbf019dc6b25f9981d29dff` (netcode 2). Activate Emscripten
**6.0.12**, then run `bash web_bots/build.sh`. The script checks out the exact
pin, applies [engine.patch](engine.patch), and uses the upstream WASM toolchain.
[BUILD.json](BUILD.json) records changed-source and artifact hashes. Original
game assets are not included.

`engine-relink.tar.gz` contains the application object files, exact link arguments
and libsmacker source/license. With the same compiler active, extract it to a
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
