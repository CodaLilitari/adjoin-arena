# Wren room 1153 live snapshot (2026-11-25)

This folder is the operational setup that hosted the public JKZone room **Wren**, lobby id **1153**, on 2026-11-25, together with the roster skins that room ran.

The branch was cut from `feature/pr4-headless-coach` at `aeec08f6be5db24f973cad41baeaf3f8430dffa7`, which is the tree the live engines were running. The JS/WASM hashes of `bin/bots-jkweb/openjkdf2.{js,wasm}` in that commit match the files the host and both joiners loaded, and the coach seat's `build` field (`sha256:44b999f50bd299b4`).

Wren (AI collaborator, via Grok Bot).

## Lineup as run

- Room name Wren, JK1MP Canyon Oasis (`m10.jkl`), guns FFA, Jedi rank 8, max 6 players, no time or score limit.
- Three engines: Lily (Darth_Lilitari, host) plus Bot_T800Hybrid and Bot_Lilivane. Each in its own Chrome.
- Host: 256×144, 25 fps cap, 1 raster thread, `--netlog`, normal priority.
- Joiners: 160×90, 15 fps cap, 1 raster thread. Launched at nice 0; after launch their process trees were reniced to +5. `lineup.json` records `join_nice: 5` so a relaunch keeps that.
- Coach seat on Bot_T800Hybrid (auto). Commands go in a control folder (`coach-t800/commands.txt` on the box).
- Red sabers for lily and t800 (`saberred1.mat` / `saberred0.mat`). Lilivane stays green.
- Skins: every seat loaded the RedRosterPhoto GOB as a `-path` mod.

Box-side paths in `watchdog.py`, `resume.sh` and `lineup.json` (`REPO`, `VENV_PY`, `DATA_DIR`, `LIVE`, `model_gob`) are as they were on the host box. Edit them to run from another checkout. Point `model_gob` at `skins/RedRosterPhoto/RedRosterPhoto.gob` in this folder (same SHA-256 as the box copy).

## Files

- `watchdog.py` — hosts the room, starts each joiner in its own Chrome, attaches the coach, logs per-seat game-time rates every minute, relaunches on a drop. Reads `lineup.json` before every launch.
- `resume.sh` — after a box reboot: recreate the venv if needed, refuse a second watchdog, stop stale seats, start the watchdog.
- `lineup.json` — desired state the watchdog re-reads (as on disk when this branch was made).
- `current.json` — sanitized snapshot of room 1153 at 15:51:49 America/New_York. No PIDs, run directories, credentials or feed `up=` tokens.
- `launch-commands.txt` — the headless flags captured from the live processes.
- `RUNBOOK.md` — the box runbook, including the “Live match after a reboot” section.
- `SHA256SUMS` — GOB, skins README, and the engine JS/WASM.
- `skins/` — the roster mod (see credits below).

Not included: `PIDS`, logs, crash dumps, companion/engine credentials, Chrome user-data, feed upload tokens.

## Engine hash check

```
4492ea09a4a165e4740f0e144c2c332cb5db6d4a7f792f7b089e4ce1880dc4d9  bin/bots-jkweb/openjkdf2.js
44b999f50bd299b4fd3677cbf20691a28ab1f5c90681864ef7e41b4d6866e701  bin/bots-jkweb/openjkdf2.wasm
```

Those are the bytes at `aeec08f` and at `7c89541` (the code commit the engines came from; `aeec08f` only added docs).

## Skins

`skins/RedRosterPhoto/RedRosterPhoto.gob` is an unmodified copy of the original GOB (SHA-256 `693341daf7480ceb9e031715b6eb44771de356743e303d73b8b8bd0a4715d650`). `skins/README.md` is the original README (SHA-256 `2cb1660054a168c91376a8673c34a945b6a3ec006886899cabb7726ec44e5727`). See `skins/SHA256SUMS`.

The file is 127,598,371 bytes, over GitHub's 100 MiB git-object limit, so it is stored with **Git LFS** on this branch only.

The README describes the pack as a complete retail movement profile with 35 character entries, for private review on an owned installation of Jedi Knight: Dark Forces II. A JKWeb host that runs this mod will send it to other JKWeb joiners and spectators in-game.

### Credits (from the original README)

Character models and earlier revisions by Red with Andrei. Integration, rig fitting and reference-guided materials by Coda with Andrei. Saber Battle X 3.1 by ShadowX and its credited contributors.

## End time

The watchdog's `until` in `lineup.json` is 16:35 America/New_York on the day of the match. Change it before a later resume.
