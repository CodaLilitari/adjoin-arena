# Adjoin Arena match runbook: Canyon Oasis, 12 slots, 6 bots, coach seat
Prepared 2026-11-25 ~1:00 PM EST by Wren (AI collaborator, via Grok Bot). Repo `CodaLilitari/adjoin-arena`
main `e5badcb` / tag v0.5.0. Working clone: `/workspace/adjoin-arena` (unmodified). Release zip
`release/JK_Cross_Server_0.5.0-linux-x86_64.zip` (sha256 2438cdd3…, matches its .sha256; its binaries are
byte-identical to the repo's `bin/`).

Rules in force: OpenJKDF2-fork engines only (never retail); label every test's environment; add **exactly 6 bots**
(never 12); no posting/accounts/connected services; no public JKZone room until Andrei says go.

## 0. Answers in one place
| Question | Answer |
| --- | --- |
| What is JKZone? | https://jediknight.zone/ : browser JKDF2 (OpenJKDF2 WASM, "JKWeb") + lobby relay `wss://jediknight.zone/relay`. "No account needed." You pick your own game folder in the page; files stay in the browser. |
| How do you host there? | In the page: Play JKDF2 → pick game folder → game starts in the tab → stock Multiplayer menus → host. Episode JK1MP, map **Canyon Oasis = `m10.jkl`**. The relay allows up to 64 peers; the stock host menu sets max players (confirm it takes 12). |
| How do the bots join? | `python -m web_bots.join_room join --room-id N --seat S ...`, once per bot. Each command serves a local page `http://127.0.0.1:PORT/bot/S`; a browser tab opens it, you load the printed credential JSON, and the bot's own WASM engine joins as an ordinary player. Six commands give six bots. |
| Ruleset | `join_room` always uses mode `ff-guns`, or `ff-sabers` with `--sabers-only`. The **host's** rank decides Force: set Jedi rank 8 for full Force. |
| Requirements | Room must be open: **no password** (locked rooms are refused), **no host mod**, netcode 2, jk1. That means a public, listed room. Matches of 2+ players lasting 1+ minute are **recorded on the public JKZone leaderboard**, so Andrei has to OK this first. |
| Coach seat | It is PR #3's `bots/coach.py` driving the companion `tactics` command (docs: `docs/BOT_TACTICS.md` on branch `source/pr3-tactics-movement`, section "The coach seat"). **No packaged binary supports it**: main's JKWeb wasm, main's native `jk-bot-client` (= PR #2's binary) and even PR #3's committed binaries all lack the tactics overlay. Main's companion hub has no `tactics` route. See §4. |
| Me playing/spectating | JKZone: host from the box browser (I hold the host seat), or watch from another tab with the relay's spectate (30 s delay, takes no seat). Local native: the control panel's **Spectator view** (free cam / follow player) at http://127.0.0.1:8765/. Driving a bot like Lily does: companion API (`bots.companion_cli observe/attach/strategy`; `--adaptive-lily` for Lily's motor controls). |
| Game data | Already on the box, no download needed (see §1). |

## 1. Game data (done)
`/workspace/jk-data/JK/` holds read-only **copies** from the box's existing JK1 retail Disc 1 extract
(`/workspace/jk1-compare-20261023/r1/iso/GAMEDATA`, Internet Archive item `Star_Wars_Jedi_Knight_Dark_Forces_II_USA`).
The originals are untouched. Layout: `resource/{Res1hi.gob,Res2.gob,jk_.cd}`, `episode/JK1MP.gob`. Hashes are in
`/workspace/jk-data/SHA256SUMS`. JK1MP contains m10.jkl (Canyon Oasis), m2, m4, m5, m_boss15, m_boss17. These files are only game data
for OpenJKDF2/JKWeb; retail is never run. (`/workspace/jkwine*/` copies also exist; their RES2 differs from retail, so don't use them.)

## 2. Box environment (label every test with this)
- 8 vCPU, 15 GB RAM (~9 GB free), **no GPU** (`/dev/dri` absent). Desktop Xvfb :1, Chrome at `/usr/bin/google-chrome`.
- "Graphics acceleration" here means the engine's OpenGL renderer (`r_softwareRenderer=false`), running on Mesa/llvmpipe
  (native) or SwiftShader/ANGLE (Chrome WebGL2). It is **not hardware GPU**. Label: *"OpenJKDF2 fork (Adjoin Arena v0.5.0 build),
  GL renderer on software rasterizer, box Linux, no GPU"*. JKWeb `/status` view flag 4 = engine acceleration, 8 = software path;
  check the WebGL renderer string too.
- venv: `/workspace/adjoin-arena-match/venv` (Python 3.13, aiohttp 3.14.5). `V=/workspace/adjoin-arena-match/venv/bin/python`
- Pinned relay (for local replica testing): `/workspace/adjoin-arena-match/runtime/relay.py`, sha256 c7d24a70… (matches the doc).

## 3. Path A: the JKZone match Andrei described (READY, waiting on his go-ahead)
Topology: my box Chrome tab = stock JKZone host (12 slots) + 6 bot tabs, each its own JKWeb engine, through the public relay.
**Resource warning:** 7 WebGL2 WASM engines on software GL in one box. Expect a low frame rate. Open the bot tabs one at a time
and check `/status`. If the box can't keep up, fall back to fewer bot tabs per check, but never more than 6 bots.

A1. Desktop agent (browser, box desktop 1280x800):
1. Open https://jediknight.zone/ → **Play JKDF2** → "Pick your game folder" → choose `/workspace/jk-data/JK` (allow read).
   Ignore the "bring them over" migration prompt (choose Start fresh).
2. Once the game starts in the tab, set the player name (e.g. `Wren`), then go Multiplayer → host a new game:
   episode **Jedi Knight MP (JK1MP)**, level **Canyon Oasis**, max players **12**, Jedi rank **8** (full Force), no password,
   no mod, time limit e.g. 15 min, score limit off, teams off (FFA). Start. Leave the tab in front.
3. Report back the room name.
A2. Shell (box), from `/workspace/adjoin-arena`:
```sh
V=/workspace/adjoin-arena-match/venv/bin/python
$V -m web_bots.join_room list          # read-only; pick our room's numeric id with "unavailable": null
RT=/workspace/adjoin-arena-match/runs-jkzone; mkdir -p $RT
for S in lily red lilivane biddy t800 crownbraid; do      # EXACTLY SIX
  nohup $V -m web_bots.join_room join --room-id ROOMID --seat $S \
     --data /workspace/jk-data/JK --runtime $RT > $RT/$S.launcher.log 2>&1 &
  sleep 2
done
cat $RT/*.launcher.log    # each prints {"page":..., "credential":..., "run":..., "room":...}
```
Optional: add `--adaptive-lily` to the lily line only (Lily's experimental controls).
A3. Desktop agent: for each of the 6 printed `page` URLs, open a new tab → **Open engine credential** → select that seat's
`credential` JSON (path printed) → wait until the bot's name appears on the host's **Player Scores**. Do the next seat only after that.
A4. Leave the tabs running for the match. To stop: close the bot tabs, Ctrl+C (or `pkill -f web_bots.join_room`), leave the host game.

## 4. The coach seat: what exists and what it would take
- `coach.py` (PR #3 only): UCB1 over presets `default,arsenal,hunter,standoff,dry`, ≥90 s dwell, grades kills minus deaths per minute,
  memory file + label. Run: `python -m bots.coach --credentials RUN/companion/BOT.json --memory coach.json --label oasis-ff-guns`.
  It needs (a) an engine built with `native/bot-tactics.patch` and (b) PR #3's `bots/companion.py`, which has the `tactics` route.
- **Known bug (my PR #3 review):** after grading, the window only resets when the next preset is ACKed `applied`. On a refused,
  rate-limited (8 s engine limit) or lost command it re-grades the same window every 5 s poll and writes each grade to memory.
  If we run it, run it in a *copy* with the one-line fix (reset kills/deaths/since right after grading), labelled
  "Wren-patched copy". Also record the build hash in the memory label, because the memory file doesn't record builds.
- **JKZone/JKWeb coach is not possible with what's published.** Tested on the box: main's JKWeb tree (tristamus/OpenJKDF2 `7a6f95c`
  + `engine.patch` + `external-room.patch`) applies cleanly, but PR #3's `bot-tactics.patch` then rejects all 37 `jkBot.c` hunks plus
  `jkBot.h`, `jkBotCompanion.inc` and `jkBotForce.inc`. It was written against the native base `74e4657`. Porting it is Coda/Red work
  (and Emscripten 6.0.12 isn't installed here).
- **Local native coach is possible (Path C, not started):** build `jk-bot-client` from gitlab `codalilitari/OpenJKDF2-MotS-Fixes`
  `74e4657` + PR #3 `native/bot-client.patch` + `native/bot-tactics.patch` (PR #3's relink archive / BOT_TACTICS "Building and trying it"),
  run its fixture tests, then use the Path B topology below with PR #3's `bots/` Python in a separate worktree. Coach on 1 seat
  (or 3 coached vs 3 default for the paired comparison the design spec asks for). Needs a few hours of build time and Andrei's OK to use unreleased PR #3 code.

## 5. Path B: purely local 12-slot native match (VERIFIED on the box today)
Env label: *OpenJKDF2 fork, Adjoin Arena v0.5.0 prebuilt `bin/linux-x86_64/openjkdf2` dedicated host (xvfb-run, GL on llvmpipe) +
6× prebuilt `bin/bots-linux-x86_64/jk-bot-client` (SDL offscreen/EGL surfaceless, Mesa software GL); PR #2-era controller, no Red
tactics, no coach.* Config: `/workspace/adjoin-arena-match/native-canyon-12.json` (m10, max_players 12, rank 8, FFA, web gateway off).
```sh
cd /workspace/adjoin-arena; V=/workspace/adjoin-arena-match/venv/bin/python; F=/workspace/adjoin-arena-match/native-canyon-12.json
R=/workspace/adjoin-arena-match/runs-native/$(date +%Y%m%d-%H%M); mkdir -p $R
$V app.py --config $F --state-dir /workspace/adjoin-arena-match/state --check
env -u DISPLAY $V app.py --config $F --state-dir /workspace/adjoin-arena-match/state --start > $R/server.log 2>&1 &
sleep 15   # the launcher caps one run at 4 bots, so use two launchers of 3 = 6 total, started 30 s apart
B="env -u DISPLAY SDL_VIDEO_DRIVER=offscreen SDL_VIDEODRIVER=offscreen EGL_PLATFORM=surfaceless"
$B $V -m bots.run --server-config $F --profiles boba_fett,jan_ors,kyle_katarn --runtime $R/botsA --seconds 900 --companion-port 0 > $R/botsA.log 2>&1 &
sleep 30
$B $V -m bots.run --server-config $F --profiles stormtrooper,bossk,lily --runtime $R/botsB --seconds 900 --companion-port 0 > $R/botsB.log 2>&1 &
# watch: Chrome on the box → http://127.0.0.1:8765/ → Spectator view (Follow player)
python3 /workspace/adjoin-arena-match/tools/score_session.py /workspace/adjoin-arena-match/state/runs/<latest>/session.jsonl "$R/bots*/*/*/client.log"
```
Smoke result (2026-11-25, 12:55–12:58 PM EST, ~150 s, 6 bots, 12 slots): all 6 joined (slots 1–6), 13 kills, no self-kills.
Boba 5/2, Jan 3/4, Trooper 3/3, Katarn 1/1, Bossk 1/2, Lily 0/1. Every bot logged 4 `BOT_NAV_UNREACHABLE` (e.g. detonator at sector 34,
lightside at 67). Box load average ~3. Rendered in-engine, not viewed.
**Gotcha found:** `time_limit: 15` made the dedicated host end each level about every 10 s (10 "Time limit reached" in ~100 s, cycling
m10→m2→m4). Bots that joined during a switch got `BOT_JOIN_REJECTED server status=3`. It looks like a unit mismatch (minutes vs
ms/s) in `manager/config.py`'s `timeLimit` hand-off. Use `time_limit: 0` and `--seconds` for now. Worth reporting to Coda (draft only).

## 6. What to log and measure (both paths)
- **Per bot K/D:** host Player Scores screenshot at start, halfway and end (JKZone). Native: `score_session.py` on `session.jsonl`.
- **Stalls:** `BOT_STATUS` (every ~10 s: sector, pos, health, goal, path, recover, keys), `BOT_NAV_UNREACHABLE`, `BOT_CONFINED`/`BOT_MOVE`
  (PR #3 builds only); count samples where pos moved <0.35 for ≥6 s.
- **Water time:** `BOT_STATUS breath_ms>0` share; PR #3 builds also log `BOT_WATER` entries and exits.
- **Coach (Path C):** coach stdout (`coach: playing X`), every `tactics` request id → `commands/<id>` status (applied / refused /
  rate_limited / pending), memory-file diffs per minute (to catch the re-grade bug), preset dwell lengths, K−D per minute per spell,
  coached vs uncoached seats.
- **JKWeb:** `GET http://127.0.0.1:PORT/status` per bot (joined, slot, kills/deaths, view flags, renderer), the companion
  `observe` JSON every 5 s, and the WebGL renderer string. Optional 120 s recording from a bot page.
- Label the environment line on every result and render.

## 7. Needs Andrei
1. OK to open a **public, unpassworded** JKZone room. It'll be listed, and it lands on the public leaderboard. Or he can host the room himself and we only join bots.
2. The coach: accept "no coach on JKZone" for now, or OK Path C (local native build of unreleased PR #3 tactics + coach.py, with my fix in a copy).
   Or ask Coda/Red for a tactics-enabled JKWeb build.
3. Bot identities for the 6 seats (defaults: lily, red, lilivane, biddy, t800, crownbraid, i.e. the JHS six).

## Live match after a reboot (added 2026-11-25 3:05 PM EST)
The box can be reset (processes and some folders such as the venv vanish). To bring the 'Wren' JKZone match back:

    /workspace/adjoin-arena-match/live/resume.sh

It recreates the venv if needed (aiohttp, playwright, cmake, ninja), stops stale match processes, and starts
`live/watchdog.py`. **The lineup is `live/lineup.json`** (updated 3:58 PM EST), re-read before every (re)launch:
room 'Wren', JK1MP m10, max 6 players, rank 8, guns FFA, no limits; host Lily (Darth_Lilitari, own Chrome, 256x144,
25 fps, --netlog); joiners t800 and lilivane, each in its own Chrome (160x90, 15 fps, nice +5); coach seat on
Bot_T800Hybrid (auto); red sabers for lily,t800; skins from `/workspace/adjoin-skins-work/RedRosterPhoto.gob`
(a read-only copy of the owner's GOB; set `model_gob` to "" to run stock models); `until` 16:35 local.
To change the lineup: edit lineup.json, then `kill -TERM <watchdog pid from live/PIDS>` and run resume.sh again.
The watchdog relaunches on a host/joiner exit or a lost listing, reattaches the coach, and logs per-seat
game-time rates every minute (`rates lily=1.00(dt 0.15) ...`; WARN below 0.9).
State: `live/current.json` (room id, run dirs, lineup), `live/PIDS`, `live/watchdog.log`, `live/resources.log`.
Coach seat: append commands to `live/coach-t800/commands.txt`; read `live/coach-t800/status.json`
(the earlier Red seat's folder `live/coach-red/` is kept but no longer used).
Spectator feed check: `node /workspace/pr4-port/feed_watch.mjs wss://jediknight.zone/feed/<room> 20` should print
`feed 30` then a `JKF1` keyframe (or `feed waiting`/`feed first <ms>` when no keyframe is old enough yet); host-side lines are `netlog feed:` in the run's lily.console.log.
If emscripten's node_modules is gone: `cd /workspace/toolchains/emsdk/upstream/emscripten && npm ci --omit=dev`.
