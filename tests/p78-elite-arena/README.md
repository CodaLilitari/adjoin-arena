# TEMP test: our bot vs SM Sith Lord's Elite Arena P78 (Build 1), 1v1 Canyon Oasis

This is test-only work. Nothing here is meant for a release or for PR4. The engine patch is labelled TEMP
throughout. It only takes effect when the web role is `sp` (`jkBotP78_sp`). With that flag clear,
multiplayer behaviour is unchanged.

Credit: Wren (AI collaborator, via Grok Bot), 2026-11-25, for Andrei Pemberton.
Elite Arena P78 and its bots, COGs, menus and assets are SM Sith Lord's work. None of it is committed
here. It is referenced only by URL and SHA-256 below.

## Third-party inputs (not committed)
| what | source | SHA-256 |
|---|---|---|
| p78-elite-arena.zip (as downloaded, unmodified) | https://smsithlord.com/openjkdf2libretro/cogfactory/gen2/p78-elite-arena.html | 349dc138b9349478c24d6b2b4b38caca92fe9194361ac1f8bc5c1f46d42ab123 |
| P78.GOB (from the zip) | same | 5515ba329407c5f4f088cf3265fadf17eeb391a70587b59b5e54532fb557abd3 |
| TEMP_dlil_skin_from_RedRosterPhoto.gob (Darth Lilitari's dlil.3do/mats/snd/keys/pup cut from RedRosterPhoto.gob, without its static.jkl/jkstrings.uni, which collide with P78) | box only | 9490b0eaedfceb823922a0ce521d6e954a09a2bba99e03ac36bd5a6367870153 |

## Environment
- Box: 8 vCPU Linux, no GPU. Headless Chrome via Playwright, one seat (`lily`), canvas 960x540.
- Graphics-accelerated renderer means the OpenGL path. In Chrome that is ANGLE over Mesa llvmpipe
  (`--use-gl=angle --use-angle=gl-egl --ignore-gpu-blocklist`), so the GL is CPU-rasterised. Run 184001
  was launched by mistake without those flags and fell back to SwiftShader (see the CPU section).
- Engine: OpenJKDF2 PR4 web build (engine source base `3edb94c` "overlay bot-tactics-web.patch") plus
  `engine-patches/p78-sp-adapter.patch`, built with `tools/build_wasm_temp.sh` (emsdk).
- Mode: Single Player > Debug Play > JK1MP > m10.jkl with P78.GOB mounted. The match is started through
  P78's own menu messages: Deathmatch, 1 bot (Jerec), skill state 3, 5 min, no frag limit, all weapons
  (weapons=0), Force on (force=0).
- Lily: Darth Lilitari skin, red saber, third person, dark side, rank 8 (her MP plan).

## Built engine (runs 184001 and 184654)
- openjkdf2.wasm 4cb3026a8203de2f639037600eda8d57c96465272b22e56c159011301a5b0204
- openjkdf2.js   2b8341336854d0b016bfd845378c5be59ea1fad882756c9d440faa91de067441

Run 182704 used an earlier build of the same adapter, from before the Force and weapon fixes. That build
was overwritten and its hash was not recorded.

## What the adapter does (engine-patches/p78-sp-adapter.patch)
- `AI/jkBot.c`: In SP, the bot's peer table is a shadow copy. Slot 0 is the local player. Slots 1..4 are
  P78's bot bodies, found through p70dm QUERY(11,k). The engine's own tables are never written. Actors
  count as peers (`BOT_PEER_TYPE`). The weapon a P78 bot is holding is read from its arms COG
  (CURWEAPON, user2), because actors have no playerInfo weapon mesh.
- `AI/jkBot*.inc`: The peer-weapon reads go through `Bot_PeerWeaponOf`. Before this fix, Force Pull
  target selection, the disarm check and gun-aware tactics all saw "no weapon" on a P78 bot.
- `Gui/jkGUIMultiplayer.c`: Adds the `sp` web role. It runs SP Debug Play of m10 and starts the match
  through P78's menu COG messages. It applies the Lilitari model and the red saber. It also gives Lily
  her MP rank-8 Force plan when SP leaves her Force inventory empty. Logs: P78_ADAPTER, P78_SCORE,
  P78_BODY1, P78_LOCAL, P78_FORCE.
- `Cog/jkCog.c`: Mirrors P78's HUD strings to stdout (P78_HUD).
- `World/sithThing.c`: Hit ledger P78_HIT. It logs every hit on an actor that traces back to the local
  player: raw damage, damage after the capture COG, and health.
- `web_bots-patches/`: The `sp` role and P78.GOB mount in serve.py, longer recording limits and
  `stopRecording` in client.js, and the launcher p78_run.py. The launcher records the canvas from START
  MATCH to MATCH OVER and logs fps and screenshots. `tools/run_smoke.sh` is the launch line.

## Results
| run | engine | renderer / fps | Lily Force | final HUD score (frags/deaths) | winner |
|---|---|---|---|---|---|
| p78-20261125-182704 | early adapter | llvmpipe, ~26 fps | none (rank 0, 0 mana) | YOU 0/13, JEREC 13/0 | Jerec |
| p78-20261125-184001 | fixed adapter | SwiftShader, ~9 fps | rank 8 | YOU 0/7, JEREC 5/2 | Jerec |
| p78-20261125-184654 (the video) | fixed adapter | llvmpipe, ~26 fps | rank 8 | YOU 3/2, JEREC 2/3 | Lily ("YOU WIN") |

184001 in detail: Lily fragged Jerec twice (bryar and repeater) and fragged herself twice, so her net
score was 0. Jerec fragged her 5 times. 7 of her Force Pulls disarmed him.
184654 in detail: Lily fragged Jerec 3 times (repeater, concussion rifle, stormtrooper rifle). Jerec
fragged her twice (repeater, saber). 11 of her Force Pulls disarmed him, and she landed 47 logged hits.
Video: 316 s, 960x540, VP9/Opus, sha256 77d96b26833150127dedbe6a0526340646e91fe3d00093ddc344f873d39d923f
(not committed).

## Diagnosis and fixes
1. Respawn works in SP. The P78_LOCAL died/respawned lines confirm it.
2. "body1=100" in run 182704 was Jerec's thing index, not his health. The health log (P78_BODY1) and
   the hit ledger were not in that run's engine, because a stale build was deployed. So 182704 does not
   show that Lily never damaged him. From 184001 on, P78_HIT shows her hits landing and his health
   dropping.
3. No Force in SP: SP Debug Play loads the level with rank 0, no stars and 0 mana (BOT_FORCE_STATE
   stars=0..., mana=0). The fix applies her MP rank-8 plan. kyle.cog then refills mana as rank*50 on spawn.
4. Force Pull never targeted Jerec, because the bot reads a peer's gun from playerInfo's weapon mesh and
   P78 actors have none. The fix reads the arms COG's CURWEAPON. After the fixes, BOT_PULL lines show
   target=1 ... event=disarm, with the weapon he held before and after.
5. Pull works on P78's actor, and the gun is not given back. p70sk.cog:23 answers SkillTarget 24 for a
   held bryar, rifle, bowcaster, repeater, rail or concussion rifle by calling arms DROP(1). p70w0.cog's
   user6, ending near line 246, spawns the pickup and clears the gun from `has` (`has = has - nb; cw = 0`).
   He then switches to his next gun or to fists. He only gets that weapon back by picking up a gun from
   the map.

## P78 bot rules vs a player (COG audit of P78.GOB, line numbers in the extracted COGs)
- Loadout and ammo: the same as JK MP spawn. p70w0.cog:112-121 gives fists, bryar and saber (has=1030),
  energy 50 and shields 100. Each shot spends ammo (p70w0.cog:528-530). Firing is gated on ammo
  (p70w0.cog:471-474). Guns and ammo only come from pickups within 0.3 units with LOS (p70it.cog:563-577,
  p70w0.cog:547-600, using items.dat maxima).
- Health and shields: p70w0.cog:179-204 is a copy of item_shields' absorb rule. The pulse auto-uses
  bacta below 50 hp, but only bacta he picked up (p70w0.cog:275-278). Force heal costs 200 mana
  (p70f0.cog:430-440). Mana regenerates by 5*d every 5 s up to 400 (p70f0.cog:192-197), and BIND sets
  mana to 400 at spawn (p70f0.cog:107). Force rank = skill+1, max 4 (p70f0.cog:103-104).
- Damage immunity or reduction: none beyond shields and Protection. p70dm.cog:230-232 passes the
  player's damage through unchanged. The body's damage goes through Force armor, which applies only
  while Protection is on (p70f0.cog:168-180), and then shields (p70b0.cog:243-245). The hit ledger shows
  after_cog=0 while his shields are above 50 and full damage after that.
- Aim: projectiles only, no hitscan. He fires only with LOS from body to target and a clear muzzle line
  (p70w0.cog:479, 494-503), and only when facing within about 45 degrees (p70w0.cog:511). At skill d>=3
  there is no random yaw or pitch error, so he aims exactly at the centre (the random error at
  p70w0.cog:519-522 applies only when d<3). The stormtrooper rifle always gets +-2.5 degrees
  (p70w0.cog:523-526). At d>=4 he leads exactly on the target's velocity (p70w0.cog:490). The aim is
  computed at the moment of firing, as FireProjectile's error angle. It does not need him to turn his
  view onto the target.
- Perception: FirstThingInView with a 270-degree cone out to 8 units, plus HasLOS (p70b0.cog:414-418).
  That cone is wider than a player's view. Within 1 unit he keeps a target outside the cone if he has LOS
  (p70b0.cog:441). When he is hit, he immediately turns on the shooter, with no LOS check, until the next
  0.5 s scan (p70b0.cog:227-236). The scan requires LOS (p70b0.cog:435). He goes to the player's position
  without sight only under the menu option TARGET=THE PLAYER, which defaults to off (dm7=0 in
  p70mode.cog:51; the logic is at p70b0.cog:579-583). He sees invisible (Persuasion) targets only at
  d>=4 (p70b0.cog:416).
- Force immunity: none. Pull drops his gun (above). Grip and Deadly Sight return base damage 10, as
  stock actor_st.cog does (p70sk.cog:24). Blinding is honoured through actor flag 0x800
  (p70b0.cog:293).

## CPU (8 vCPU box, one Chrome seat)
| run | renderer | game/wall | fps mean (min) | BOT_STATUS dt mean (max) | Lily's logged hits on Jerec |
|---|---|---|---|---|---|
| 182704 | llvmpipe | 0.9997 | 25.8 (23.2) | 0.044 s (0.153) | not logged (stale build) |
| 184001 | SwiftShader | 1.000 | 9.0 (7.2) | 0.122 s (0.250) | 25 |
| 184654 | llvmpipe | 0.9997 | 26.1 (20.0) | 0.042 s (0.155) | 47 |
The 1-minute load average during 184654 was 3.8 to 4.6 on 8 cores, so the box was not saturated.
Game time kept pace with wall time in every run. The engine does not slow game time down; it takes
fewer, longer frames instead.
Our bot and Jerec's COGs run in the same engine frame on the same thread: jkBot_Tick is called from
sithControl.c:442 and the COG pulses run in that frame's update. Neither one starves the other. The
difference is what a long frame does to each. Lily's aim is a view that has to turn (per-frame input).
Jerec's shot angle is computed exactly when he fires, and his pulses are 0.01 to 0.1 s, so at 9 fps he
loses little. Low fps therefore costs Lily more than him.
