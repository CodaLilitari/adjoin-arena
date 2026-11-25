# PR4: headless bots and a JKZone/JKWeb coach seat

Written by **Wren (AI collaborator, via Grok Bot)** for Andrei Pemberton / CodaLilitari.

PR4 builds on `main` (v0.5.0). It takes the parts of PR #2 and PR #3 that hold up under review and puts them in the JKWeb (browser/WASM) engine, so the bots that join JKWeb and Jedi Knight Zone rooms run the same tactics as the native PR #3 bots. It also adds:

1. **Headless bots.** One command starts N JKWeb seats in a single headless Chrome. They need no desktop tabs and no folder picker, and credentials load automatically.
2. **A coach seat.** It attaches to any live companion-enabled bot (JKWeb or native) and runs the coach on it. A person or another agent can take the seat over at any point and hand it back.
3. **Headless hosting.** One seat hosts a listed room (for example 12 slots, JK1MP Canyon Oasis m10, Jedi rank 8, guns FFA) and the other seats join it.

All bot effects still go through ordinary player inputs and the engine's existing companion commands. The bots get no engine-state cheats.

## What came from where

| Area | Source | Notes |
|---|---|---|
| Run key, swim fixes, running Force Jumps, traps, confinement/recovery, ordnance, `CP_TACTICS` (21), tactics table, `bots/tactics.py`, `bots/coach.py` | **PR #3** | Ported to the web engine as a third overlay, `web_bots/bot-tactics-web.patch`. PR #3's patch applied as-is rejected 37 of 37 hunks against the web `jkBot.c`. A 3-way merge (`git merge-file`, base = reverse-patched native) left 9 conflicts, which I resolved by hand. |
| Red's tactics on join | main / PR #3 | Kept. |
| Adaptive Lily (`CP_COMMIT` 19, `CP_MOTOR` 20, offers/progress/sense, live policy reload) | **PR #2** (already on main) | Kept beside `CP_TACTICS`. Lily commands still dispatch only for 19/20 (`kind==CP_COMMIT‖CP_MOTOR` instead of `>=`), so 21 can't be misrouted. |
| Lily pickup credit | new (review fix) | Arriving at an item node counts only if the stock touch actually removes the item (outcome `collected`). Otherwise the route fails with `not_collected` after a 0.6 s grace. |
| Lily route combat lockout | new (review fix) | A Lily route under fire with a target is interrupted (`self_defense`) and stock combat answers. `JK_LILY_SELF_DEFENSE=0` restores the PR #2 behaviour. Force use stays off while Lily drives. |
| `CP_SENSE` self trailer | new (review fix) | An optional 20-byte trailer: sector, on_water_surface, hurt_recently, health, shields, mana. The Python codec accepts old and new lengths. |
| Coach grades each window once | new (fix to PR #3) | PR #3 re-graded the same window on every poll whenever the next preset was refused or lost (1 window graded 10× in 200 s). The window now closes right after grading. |
| Coach memory per build | new | `--engine` hashes the wasm/native binary into the memory record (or `--build-id`). Different builds never mix. PR #3 records load as "unrecorded". |
| `bots/coach_seat.py` | new | Modes: auto (UCB1 over presets), manual, hold, released. Operator commands come from the terminal (`--interactive`) or a control directory (`commands.txt` in, `status.json`/`log.jsonl` out). A takeover drops the open window, so manual play is never graded. SIGTERM releases the lease. |
| `web_bots/headless.py` | new | `host` / `join` subcommands. Each seat gets its own Playwright context, served engine and companion. Runs headless (`--headless=new`) or under Xvfb. WebGL renders through SwiftShader by default (software GL, no GPU). Seats join one at a time and the run writes `headless.json` + `status.jsonl`. `--public-room` is required before it will host on the public JKZone relay. |
| Hosted room parameters | new | `JK_BOT_WEB_MAX_PLAYERS` (2..16) and `JK_BOT_WEB_MAP` for the host role. No time or score limit. |
| Browser bridge | new (bug found in e2e) | `client.js` dropped kind 21, so every coach preset over JKWeb came back "unconfirmed". It now forwards 21. A test keeps the page's allow-list equal to the companion's command kinds. |

Not included: the GTTeancum-inspired pickup returnability check (left for a follow-up). No original or frozen files were edited apart from the overlay stack.

## Usage

```sh
# Host a 12-slot Canyon Oasis room and join five more seats (local relay)
python -m web_bots.headless host --relay ws://127.0.0.1:18080/relay --room-name Canyon \
  --max-players 12 --map m10.jkl --mode ff-guns --host-seat lily \
  --seats red,lilivane,biddy,t800,crownbraid --data /path/to/JK --runtime runs/

# Coach one of them; jump in with lines appended to coach/commands.txt
python -m bots.coach_seat --run runs/headless-*/headless.json --seat red \
  --engine bin/bots-jkweb/openjkdf2.wasm --memory coach/memory.json --control coach/
echo "preset hunter" >> coach/commands.txt   # take over
echo "auto" >> coach/commands.txt            # hand back
```

## Test receipts

The environment for these runs: box Linux x86-64, Chrome headless with ANGLE/SwiftShader (software GL), and the JKWeb engine (OpenJKDF2 fork, tristamus/OpenJKDF2 `web-mp` 7a6f95c) rebuilt with **emsdk 6.0.12** from all three overlays. JK1 retail data came from Disc 1.

- **WASM build:** a full CMake build of the three-patch stack succeeds. `openjkdf2.wasm` sha256 `e2aef2a15f69a1fd…`.
- **Python unit suite (68 modules):** PR4 matches main exactly. The only failures are the same 8 pre-existing import errors on both (`test_lily_memory_*`, `test_lily_outcome_*`: optional dependency missing on the box). New tests: `tests/test_coach_seat.py` (13), `tests/test_web_bot_headless.py` (6), `tests/test_lily_protocol.py` PR4 cases. `tests/test_bot_tactics.py` was updated for the build-aware memory format.
  - Regressions verified failing before / passing after: coach refused/lost command grades once, batched operator commands all sent, `client.js` forwards `CP_TACTICS`.
- **Native C fixtures (on the merged web sources):** driver, hearing, portal PASS. Companion PASS on the hybrid tree, including tactics and the new pickup-credit/self-defence fixture. Collision and plain companion fail **identically on main** (web `sithMulti.c` chat difference; collision endpoint off by 1e-8).
- **JS client test** `tests/test_web_bot_client.js`: PASS.
- **Local end-to-end** (`relay.py` on 127.0.0.1, never a real JKZone room):
  - Smoke: Lily hosts 12 slots on m10 (`BOT_WEB_HOST … seats=12 mode=ff-guns rank=8`) and Red joins. Listed as room 1, frags on both sides, PR3 `BOT_MOVE` telemetry live in the browser.
  - 6 bots: Lily hosts, and Red, Lilivane, Biddy, T800 and CrownBraid join one at a time, all in within 52–61 s. About 333 s of play: lily 8/8, red 8/8, lilivane 10/8, biddy 6/10, t800 2/7, crownbraid 8/6 (K/D).
  - Coach seat on Red: presets applied (`reason 0`), a window graded once (default +1.99), rotation to arsenal, operator takeover (open window dropped), `set run=1` + `strategy pressure` applied in order, handback resumes auto. After a SIGTERM the lease is released and a new seat attaches immediately.

## Known gaps

- Join/connection time grows with seat count on one 8-core box (about 6 s for the first joiner, about 14 s for the sixth). Each seat runs its own SwiftShader renderer.
- JKWeb direct links between joiners sometimes fall back to the host relay path ("direct link … going through the host"). This is stock netcode behaviour.
- `SHA256SUMS` / `release-manifest.json` are not regenerated here. That belongs to the release build (`tools/build_release.py`).
- Two native fixtures fail on the web tree exactly as they do on main (see above).
- The pickup returnability check is not ported.
