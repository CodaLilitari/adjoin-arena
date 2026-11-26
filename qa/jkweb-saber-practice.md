# Saber duels on JKWeb netcode 2

These private trials used two independently controlled JKWeb players, the stock multiplayer rules, fresh navigation memory for each bout, and separate NF and FF scores. Battleground Jedi is `JK1MP/m_boss17.jkl`. Blades of Death is `JK1MP/m5.jkl`. Comparisons use the elapsed game clock of each owner after both players joined. The ordinary-speed holdouts used the regular game loop. The 4× practice build executed the same bot object with fixed 33.33 ms control steps and 6.67 ms physics steps.

## Match results

Thirty-six private bouts covered 69 minutes 40 seconds of match time. Twenty ran with the 4× practice clock, and sixteen used the ordinary game loop. Each score cell below lists total kills by the challenger and by the comparison bot, in that order. The Dark-versus-Dark comparisons used Darth Lilitari and Red, with challenger assignment reversed. The four normal-speed NF predictive bouts also reversed who hosted. Stock appearances were used for the comparisons.

| BGJ challenger | Hit rule | Mode | 4× kills | 1× kills | 1× confirmed saber contacts |
|---|---|---|---:|---:|---:|
| Earlier primary vs. default saber | Classic | NF | 5–16 | 3–5 | — |
| Earlier primary vs. default saber | Classic | FF | 10–19 | 3–11 | — |
| Predictive heavy vs. default saber | Hit what you see | NF | 9–8 | **12–8** | **28–23** |
| Predictive heavy vs. default saber | Hit what you see | FF | 14–16 | 3–4 | 5–7 |
| Higher own-side Surge value vs. default value | Hit what you see | FF | 15–18 | 9–7 | 22–22 |

The predictive NF challenger won three normal-speed games and drew one. In the four 4× games, it won two, drew one and lost one. The normal-speed NF peers reported 84–100 ms end-of-match game RTT with the delay simulator enabled. This supports trying the option on BGJ. Human opponents and other NF maps remain separate tests. The FF results support keeping the existing contact-and-guard behavior. [Time windows, engine hashes, scores and hit totals for every bout](jkweb-saber-trials.json) · [Tested predictive policy](../web_bots/candidate/saber-approach.patch)

## What player footage suggested

- TSM Bguitar carries a wide swing across two opponents on BGJ. In a separate recording, BeefCaike turns back onto Jezz after Jezz crosses the steps. Both examples suggest measuring travel through a close exchange and the ability to reacquire a passing player. The first recording is from a post-tournament FFA. [TSM Bguitar, 0:19–0:23](https://www.youtube.com/watch?v=a5KVIHmUswQ&t=19s) · [BeefCaike vs. Jezz, 0:35–0:43](https://www.youtube.com/watch?v=czdUtyxPn8A&t=35s)
- In Demon27248’s FF chapter an opponent passes high beside the ship and drops down the slope as the player looks down and uses Bacta. A separate FF recording shows the stream crossing and an opponent overhead near the ship. [Demon27248, 1:05–1:11](https://www.youtube.com/watch?v=yLLxjhch6-8&t=65s) · [Lonewolf, Gordakarn and DarkJester on BGJ](https://www.youtube.com/watch?v=DlI9OJPBgws&t=7s)
- WD_Shinji describes practicing specific high-speed Force Jump landings with a competitive player. Jeb_Springfield describes fighting for the Surge and managing Force during a one-on-one. These are stock-era player accounts. The footage supplies examples of decisions and movement, with no verified modern JKWeb ranking or measured network delay. [Shinji’s firsthand account](https://www.jkdf2.net/articles/history-of-a-jk-player-from-anime-clan-noob-to-world-champion-part-2/) · [Jeb’s FF BGJ guide](https://www.jkdf2.net/articles/jebs-bgj-ff-tips-mostly-1-on-1-tactics/)

## Host settings and interpretation

The same upstream netcode can run two different hit rules. Classic lets the defender resolve the incoming attack. With **Hit what you see**, the attacker reports a contact and the defender validates it against its history. The host can choose `--hit-rules hit-what-you-see`. Participating clients expose the active rule and their peer handshake. In these games a completed handshake and the difference between each owner's opening and closing hit ledger measure accepted saber contacts. An input edge only measures pulling the trigger. FF kills also include offensive Force powers. [Upstream hit rules](https://github.com/tristamus/OpenJKDF2/blob/6f6d376063954f86b8d01561aad03c26fec2e4ed/src/Platform/Networking/WSRelay/stdComm_WSRelayHits.c) · [Private practice clock](../docs/FAST_TRAINING.md#private-jkweb-practice)

The default saber policy holds its guard until contact and chooses a heavy secondary when the opponent is likely to stay within reach. The first challenger used the existing coach switch `saber_heavy=0`, which allows a primary swing from farther out. The second challenger kept the heavy and also allowed its wind-up during a closing pass if projected separation was within reach 0.33–0.55 game seconds later. Both used the same movement controller, aim checks and ordinary player inputs.

The stock map can briefly equip another inventory weapon after spawning or collecting an item. The saber-only bot setting restricts its weapon attack inputs. Under FF rules, offensive Force powers remain available. These trials do not establish a typical Internet latency distribution. The delay tests applied a requested 80 ms of additional round-trip delay to the visiting peer only.

## Running the tested NF option

For a local BGJ host, add `--mode nf-sabers --hit-rules hit-what-you-see --nf-saber-entry` to the ordinary headless launcher. An independently joining bot can use `join_room join` with `--sabers-only --nf-saber-entry`. The host selects the room's hit rule. Each operator selects the timing policy for their own bot. The default is off.

Three additional normal-speed games verified those settings with the packaged browser engine. Under NF Hit what you see, Darth Lilitari used the predictive heavy swing 51.365 seconds into the game at a separation of 0.530 world units. Red had the option off and used the existing timing. With the same option requested, Darth made 18 ordinary swing inputs in FF Hit what you see and four in NF Classic, with zero predictive inputs in either game. Both peers completed the network handshake in all three games. [Per-player settings, inputs, accepted hit tallies and engine hash](jkweb-nf-saber-entry.json)

## Full Force resource test

On stock BGJ the Dark and Light Surges have 60-game-second respawns. The corresponding Surge grants a rank-eight player up to 400 mana and a 20-second effect. The four ordinary Force Boosts are distinct items. To test whether a bot benefits from making a detour for its own Surge, the FF challenger assigned a present, eligible Surge a route value of 14 in place of 7. The comparator retained 7. Both used the default saber policy. The scores compare a Dark and a Light player with the challenger assignment and host varied.

The pickup observer records the local player's stock `TAKEN` acknowledgment before the pickup script applies the inventory effect. It identifies the item, life, time and alignment. Bin 14 is a Force Boost, 64 is Dark Surge, and 65 is Light Surge. A collection after spawning on the upper ledge does not establish a route up from the stream. [Pickup observer](../web_bots/candidate/ff-saber-pickup-observer.patch) · [Experimental route weight](../web_bots/candidate/ff-saber-surge.patch)

At 4× the higher weight yielded four side-appropriate Surges against three and trailed 15–18 in kills. At normal speed with simulated delay it yielded one Surge against three, led 9–7 in kills, and tied 22–22 in confirmed saber contacts. Biddy took every Surge in these six games on the Light side. Darth collected ordinary mana boosts but never the Dark Surge. These outcomes give no consistent advantage to doubling the route weight.

In 13 earlier FF bouts on BGJ, all 26 opening navigation reports had a path to the Light Surge and none had a path to the Dark Surge. Both close approaches to Dark Surge in those bouts began at its neighboring spawn. The proposed bank crossing spans 1.70 world units. The navigation controller rejects its sloping run-up and also skips some running jumps between disconnected parts of the map. A useful qualification would start on the other bank and require a real takeoff, stable landing, acknowledged pickup and safe exit in one life. [Stock geometry, sampled routes and test coordinates](bgj-dark-surge-route.json)

## Transfer to Blades of Death

Two 100-game-second FF bouts paired Darth Lilitari with Biddy. Neither player earned a kill across the two games, and the ledger recorded one saber hit. In the first game Darth stayed within 0.10 world units horizontally for the final 60.7 seconds. Neither player reported a fresh target. In the second, both moved for over 90 seconds without a reported target and had about two seconds of nearby contact each. Biddy finished with 100 health and Darth with 20. The first game gives a location to test for a navigation stall. The second raises a separate question about how often the bots find each other on this map. There was too little contact to rank swing policies on this map.
