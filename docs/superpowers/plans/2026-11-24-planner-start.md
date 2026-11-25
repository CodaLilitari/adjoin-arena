# Starting both native planners at GO

The previous eight Canyon Oasis matches showed that slot 1 changed gear targets before pickup eight times and slot 2 never did. Slot 1 spent longer physically held with its bot already planning. This experiment tests whether starting the policy only when each owner observes the gate release changes that opening.

## Design recorded before the new trials

Use one research client executable in both conditions. In OFF it runs the ordinary policy during the hold. In ON it waits for the locally observed physical gate release before starting the policy. Keep the release protocol, stock Force loadouts, game physics, weapon locations, 1x pace, stationary rifle camera, and 22-second shared observation window fixed. Record which native callbacks and clocks the implementation actually gates.

Measure both modes with Boba first and with Jan first. Within each mode and join order, play the normal, swapped, swapped, normal sequence. This gives eight matches per mode. Alternate conditions across the session. Reserve a separate fresh Jan-first, normal-start OFF/ON pair for confirmation. This pair repeats a known layout and measures repeatability. Keep the confirmation out of the main estimates. Retain failed attempts and record their disposition.

## Outcomes and decision

- Count first-seat plans for a different item after release and before the first planned weapon's stock pickup message, corroborated by an opening-life inventory gain. Also report missing or different planned weapons and missing pickups. Suppressing all plans or failing to acquire the weapon cannot count as an improvement.
- Compare local release-to-possession time, the first pickup by sector and slot, and second-seat target changes. The sampling interval for possession is about 0.1 simulated seconds.
- An experimental opening is worth keeping if ordinary controls reproduce the first-seat detour, waiting reduces it in both join orders, first-seat median pickup time improves, and both seats keep collecting the expected weapons. Check the direction on the reserved pair. Report any competing explanation or second-seat regression.
- Scope any adoption to this physical-start fixture. These opening trials measure neither duel wins nor multiplayer acceleration.
