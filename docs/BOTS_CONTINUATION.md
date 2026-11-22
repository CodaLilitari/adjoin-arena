# Competitive bot continuation

## Packaged fourth refinement candidate

The Linux and JKWeb packages include the reviewed supply-approach policy, earlier supply-recovery
changes and bank-landing correction. Independent relinks reproduced each runtime file byte for
byte. The four-seat 240-second gameplay check for this build is pending. The prior failed live
movement trial used candidate 3.

| Packaged runtime | SHA-256 | Verification |
| --- | --- | --- |
| Linux x86-64 bot | `d2ad6f4527ee00de93e13d709ed9502ca6dadf4fef8ed8a3d95a8df6f4704808` | 205 translation units scanned, one rebuilt (`jkBot.c`), 223 source and 218 link-input hashes verified. The patched source passed 78 named groups and 54 legal loadouts. [Native build receipt](../qa/bots-refinement-native-build.json) |
| JKWeb WASM | `7f5ab43857e84f0c3e905e28db07a23fc4575095174813c29459db48ad8f0adf` | All 28 changed source hashes verified against the patched, pinned JKWeb source. [Browser build receipt](../qa/bots-refinement-web-build.json) |
| JKWeb JavaScript | `dd348b7f5dace28a4cd387eca7942eb30e25ef78b091e87217937a39cf2a2cd7` | Matches the same browser relink. |

## Third refinement trial

The 240.002-second recording on local runtime commit `536d293` captured four hardware-accelerated
seats, all autonomous, with Lily’s third-person model and red saber side and tip verified.
Lily repeatedly reached a dry sector and then selected another underwater supply. Across 840
fresh living states, 659 were wet, 178 dry and three ambiguous. She spent 189.055 seconds in
17 intervals of little horizontal progress, compared with 52.756 seconds in the preceding run.
Her sampled score went from 0/1 to 1/2 kills/deaths. After 43.4 seconds, she held the concussion
rifle in 700 of 706 remaining living observations and had a target in only ten.

The trace showed eight returns for air by Lily and 19 across all four seats. No confidently
same-life replan for the identical failed item occurred inside its 45-second cooldown. Choosing
another supply in the same area still led back to water. [Live trial and video verification](../qa/bots-refinement3-live.json)

## Supply choices after an unsuccessful dive

A source fixture reproduced the loop with two distinct submerged items reached through the same
bank. The revised planner gives an adequately armed bot 45 seconds to pursue other destinations
after an unsuccessful dive there. Water can still be the only way to a dry shield, a backpack or an
opponent. The fixture verified that the bot keeps that destination through its underwater equipment
rescan. On the tested Canyon Oasis bank the ordinary graph still reaches 483 of 558 anchors.

Independent review accepted the revision after rerunning all 55 driver groups against each source
configuration. All 27 bank replay results matched the preceding build. A fresh four-minute match is needed to measure whether this changes Lily’s
movement and combat opportunities. [Source fixtures and baseline exceptions](../qa/bots-supply-approach-retry.json)

## Four-minute Canyon Oasis baseline

The second refinement candidate ran a four-seat full-Force guns match on `m10.jkl`.
Its JKWeb base was `7a6f95c9a3399e59acbf019dc6b25f9981d29dff`. The recorded WASM SHA-256
was `ea56c2215d2d644170f475516d28fa99694fc85cbea60fbd96f5f698b610608d`.

Lily went from 0/0 to 6/2 kills/deaths, planned six backpack approaches and had 20 same-life
sample intervals with an ammunition increase. The trace recorded concussion, repeater, bowcaster
and saber alternate-fire requests. Stock input requests cannot establish a kill’s cause.
Boba’s longest interval of horizontal confinement near the pool was 54.087 seconds, and Lily’s
final interval was 10.072 seconds. See the [trial summary](BOTS_BEHAVIOR.md#four-minute-canyon-oasis-equipment-trial).

## Supply recovery after the baseline

Both engine source configurations passed independent driver checks for three corrections. The bot
now turns for air on stock contact with the intended underwater supply despite a delayed grant.
Separate failed dives retain their own retry deadlines. A single checked intermediate node can
connect a player to a backpack beyond direct reach. The native companion transport passed. A
POSIX-only harness applied to the browser fork reproduced its existing chat assertion failure on
both the baseline and corrected sources. See the [test matrix](../qa/bots-supply-recovery.json).

## Bank landing under stock physics

Two recorded approaches timed out before the fix at all four tested headings. The corrected
predictor permits a walk of up to 0.16 world units from supported touchdown to the dry anchor.
At a 74 ms control interval, the swimmer reached sustained dry support in 5.133–5.207 seconds
with 100 HP. At 87 ms it took 21.127 seconds with 90 HP. All 27 cases passed on both source
configurations. One previously successful 79 ms control slowed from 25.573 to 29.940 seconds
and still finished with 60 HP. The third refinement trial above shows how these physically
reachable banks can coexist with an unproductive choice of the next supply route.
[Bank replay matrix](../qa/bots-bank-landing.json)

## Competitive work still open

| Capability | Evidence needed |
| --- | --- |
| Time and contest important pickups | A route-time estimate in seconds, stock respawn and touch eligibility, and contested runs showing who actually got the item. The current weighted routing cost includes penalties as well as distance. |
| Disengage, re-kit and re-enter a fight | An autonomous decision that breaks exposure when supplies or health are poor, reaches a viable pickup under pressure and resumes combat after recovery. |
| Fight while moving vertically | Replay heavy-weapon recoil, muzzle clearance and predicted landing together. The checked combat hop currently withholds concussion and rail during committed flight. Validate safer lead against airborne opponents. |
| Judge results against human opponents | Repeat on named builds and compare recorded engagements with human play. A single four-bot scoreboard cannot establish elite human performance. |

The [review dispositions](reviews/2026-11-22-elite-bot-feedback.md) cover stock mechanics, surge
eligibility, enemy state, Force timing and remaining questions in more detail.
