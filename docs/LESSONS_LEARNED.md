# Lessons learned: hosting headless JKWeb bots on Jedi Knight Zone (PR4)

Notes from running the public room "Wren" (JK1MP Canyon Oasis, guns FFA, Jedi rank 8) from one 8-vCPU, 16 GB box on 2026-11-25. They cover rooms 1147 to 1153.
Written by Wren (AI collaborator, via Grok Bot).

## 1. Six engines in one Chrome stalled together (room 1147)

- **What happened.** Room 1147 dropped after about 11 minutes. At t=640 s, all six WebRTC links went down in the same second, and relay sends stalled with 30 s timeouts. Shortly after, Chrome's thread-pool threads hit fatal signals 5 and 6, and the kernel logged `virtio_balloon: Out of puff`.
  - It was not an out-of-memory kill. The cause was one browser process (one SwiftShader GPU process) shared by six engines, so one stall froze every seat.
  - The launcher didn't notice, because a hung page still looked alive.
- **Fix.**
  - The host seat runs in its own Chrome (`headless host --seats ""`).
  - `headless.py` keeps `chrome.log` and `crashes/` for each run, watches page crash/close and browser disconnect, and exits non-zero when the host seat drops (`--exit-on-drop`).
- **Lesson.** Never let the host share a browser with anything else, and make the launcher fail loudly so a supervisor can act.

## 2. The box reboot, and the resume script

- **What happened.** The box was reset at about 14:38 and room 1148 went with it. The reset also wiped:
  - the venv
  - pip's `cmake`
  - emscripten's `node_modules`
- **Fix.** `live/resume.sh` (box-side, outside the repo) does the following:
  - recreates the venv if needed (aiohttp, playwright, cmake, ninja)
  - refuses to start a second watchdog
  - stops stale seats
  - starts the watchdog under `setsid nohup`
- The watchdog's end time is absolute (`until` in `live/lineup.json`), so a resume keeps the original plan.
- The RUNBOOK covers restoring emscripten with `npm ci --omit=dev`, using emsdk's own node.
- **Lesson.** Anything that must survive a reset needs a single idempotent entry point and state files that hold absolute times, not relative ones.

## 3. Spectators saw a black screen: no keyframe

- **What happened.** The lobby showed `feed: 1`, but spectators waited forever for the first picture. Two causes:
  - Our engine was built on tristamus/OpenJKDF2 `web-mp` `7a6f95c`. That commit predates the engine half of spectator mode (the "Feed, step 1..4" commits), so the host never opened `/feed/<room>` and never made a keyframe.
  - Our bot page's CSP allowed only the relay URL, which would also have blocked the feed socket.
- **Fix.**
  - Rebase the overlays onto `web-mp` `6f6d376` and use upstream's own feed code unchanged. The host sends a keyframe on feed open, on every new level, every 60 s, and on `key`.
  - Allow `<relay origin>/feed/` in the CSP.
  - Mirror the engine's netlog to the console (`?netlog`).
- **Verification.**
  - A watcher on `wss://jediknight.zone/feed/<room>` receives `feed 30` and then a `JKF1{...}` keyframe within a second.
  - The host logs `feed: keyframe, ...` every 60 s.
- **Lesson.** When a lobby flag says a feature is on, check the bytes on the wire. Also, track how far our engine base lags upstream.

## 4. Niced joiners were starved: measure game-time rate, not liveness

- **What happened.** In room 1149, five joiners shared one Chrome at nice +10. Every process was alive and every seat reported "running", yet the joiners looked frozen to other players.
  - Each bot's clock (`t=` in its `BOT_*` console lines) advanced 0.19–0.24 s per wall second.
  - Their frame `dt` sat at the bot's 0.25 s clamp, which is 4 fps or less.
  - The host, at normal priority in its own Chrome, stayed at 1.00.
- **Cause.** The cost is in the SwiftShader GPU process, about 2 to 2.6 cores per Chrome even at 160×90, not in pixels: the engine already draws at about 61×34. Five engines behind one niced GPU process got the leftovers of a box at load 15–18.
- **Fix** (measured, room 1151, about 6 minutes):
  - three engines only
  - each joiner in its own Chrome
  - nice 0
  - joiners at 160×90 with a 15 fps cap
  - result: Lily, T800 and Lilivane all at **1.00**, with dt 0.07–0.13
- The watchdog now logs `rates seat=<rate>(dt ...)` every minute and warns below 0.9.
- **Lesson.** Supervise the metric players experience: game-time rate and frame dt. Process liveness and "joined" status aren't enough.

## 5. The watchdog relaunched a stale lineup

- **What happened.** The first watchdog had its six-bot lineup hard-coded. When room 1149 went unlisted, the watchdog brought back the *old* lineup as room 1150, after the owner had already moved to a smaller one.
- **Fix.**
  - The lineup lives in `live/lineup.json`, which covers host, joiners, coach seat, skins, sabers, views, nice and the end time. The watchdog reads it again before every relaunch.
  - Operators stop the watchdog with SIGTERM, and it tears down its own children.
  - Only one room named Wren should be listed at a time. The host retries if a stale listing makes its own room ambiguous.
- **Lesson.** Supervisors should read desired state, not carry it.

## 6. The coach lease lockout

- **What happened.** When a bot's state was briefly stale (`409 Waiting for native state`), the coach seat dropped its lease. Its next command then hit `A controller holds this bot` for the 30 s lease life, so it had locked itself out.
- **Fix.** `CoachSeat.refused()` keeps the lease on that error and logs once (`kept_lease=True`). There is a regression test for it.
- **Lesson.** Separate "not now" refusals from "not yours" refusals.

## 7. Skins and sabers

- **Skins.** The owner's roster GOB is a JK `-path` mod with 35 `models.dat` entries. It loads with `headless --model-gob <gob>`:
  - The page mounts it as `jkmods/companion/*.gob`, and the engine starts with `-path jkmods/companion`.
  - Each seat whose roster body the GOB carries wears it (`web_bots/serve.py` `ROSTER_MODELS`):
    - Lily → `dlil.3do`
    - T800 → `t800hy4.3do`
    - Lilivane → `lvane.3do`
    - Biddy → `biddybl.3do`
    - Red → `redmandot.3do`
    - CrownBraid → `redmandoh.3do`
  - A body the GOB lacks leaves the stock Kyle variant in place.
- **Joining a modded room.** The host's lobby entry then names the mod, and the engine's bot join refused such rooms. Bots started with the same GOB now set `JK_BOT_WEB_MOD=1` and may join. The ordinary `mods.js` check after the welcome still confirms they already run the host's mod (same fingerprint, so no restart).
- **What other players and spectators get** (upstream `mods.js`):
  - A JKWeb joiner without the mod gets it from the host before the level loads (KIND_MOD transfer, minus retail files) and restarts into it.
  - A spectator gets it through the feed: the keyframe's `tail` names the mod's fingerprint.
  - So in JKWeb, if the host runs the mod, every JKWeb player and spectator ends up seeing the skins.
  - A client that can't load a model (`sithModel_Load` fails in `jkDSS.c`) keeps the player thing's stock model, which is Kyle.
- **Caution.** The host will send the whole GOB (127 MB here) to anyone who joins or watches. Only use a mod you're allowed to share that way. Assets never go in this repo.
- **Sabers.** `--red-sabers lily,t800` sets `JK_BOT_WEB_SABER_COLOR=red`, which writes `saberred1.mat`/`saberred0.mat` (side and tip) into the seat's MPC. The engine logs `BOT_WEB_CHARACTER name=... saber=red`.
- **Cost.** The roster bodies are heavy: `dlil.3do` is 17.8 MB and `lvane.3do` is 16.8 MB, about 14k polygons each. On SwiftShader, with three engines plus a human player, they pushed the host's dt from 0.10 to the 0.25 clamp (rate 0.94).
  - Renicing the two joiner process trees by +5, while the host stayed at nice 0, brought all three back to 1.00 (host dt about 0.15, joiners 0.07–0.20).
  - That's why the live lineup runs the joiners at nice +5. Each joiner is in its own Chrome, so the nice +10 starvation from section 4 doesn't come back.

## 8. Recommended limits for bots per box (8 vCPU, software GL)

- **Stock models:** at most 3 engines (host plus 2 joiners), each in its own Chrome at nice 0.
  - Joiners: 160×90, 15 fps cap, 1 raster thread.
  - Host: 256×144, 25 fps cap.
  - Expect about 2–2.6 cores per Chrome GPU process.
  - Six engines on one box doesn't hold real time.
- **Heavy custom models** (around 15 MB / 14k-polygon bodies): treat them as about one more engine's worth of GPU.
  - Host plus 2 joiners held 1.00 only after the joiners went to nice +5.
  - Don't add a fourth engine. Check the `rates` line after every change.
- **Watch these:**
  - each seat's game-time rate (should be ≥ 0.98)
  - median frame dt (well under 0.25)
  - load average below about 2× the vCPU count
- **Keep the box otherwise idle.** Builds and test runs during a live match cost the host frames. Run them at nice 19 or before going live.
- **For more seats,** use more boxes or a real GPU, not more Chromes.
