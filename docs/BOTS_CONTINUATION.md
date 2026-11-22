# Competitive bot continuation

## Packaged builds after review

The Linux and JKWeb runtimes include the accepted supply-recovery and bank-landing fixes.
Independent relinks reproduced the packaged Linux executable, browser JavaScript and WASM byte for
byte. A fresh 240-second, four-seat Canyon Oasis recording of this WASM is pending.

| Packaged runtime | SHA-256 | Verification |
| --- | --- | --- |
| Linux x86-64 bot | `900a7bbc87f696f13b22ed2887838129587640d86af3e099d91f868ec91bb7ab` | 205 translation units scanned, 17 rebuilt, 223 source and 218 link-input hashes verified. The patched source passed 76 named test groups and 54 legal loadouts. [Native build receipt](../qa/bots-refinement-native-build.json) |
| JKWeb WASM | `607c58429d62f7be53e0b82922e146e8055127ef3d054cf8f71a4e61ce383f4a` | All 28 changed source hashes verified against the applied patch on the pinned JKWeb base. [Browser build receipt](../qa/bots-refinement-web-build.json) |

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
and still finished with 60 HP. The earlier live clip used the baseline WASM. The multiplayer
effect of the change needs a separate recording of the corrected build.
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
