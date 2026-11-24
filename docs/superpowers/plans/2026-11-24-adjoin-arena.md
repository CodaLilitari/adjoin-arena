# Adjoin Arena development plan

Agreed by Coda and Lilitari with direction from Andrei, 24 November 2026. The first experiment tests whether removing wall-clock pacing preserves one stock-physics trajectory and reduces elapsed time. It establishes a reference for later full-match integration.

## First experiment

1. Start from the pinned PR #2 single-actor stock-water fixture. Use the same executable, map bytes, initial condition, seed, physics settings, controller, and control cadence in every run. The autonomous controller's applied inputs must match at every tick. Record binary, geometry and configuration identities.
2. Compare repeated 1× runs first. Then compare uncapped runs with the paced reference. Change only the outer wait. Preserve control dt, residual-based 150 Hz physics, the 6/7/7 ms actor update pattern, and the order of actor, collision and control processing.
3. Record comparable state at each physics substep and control tick. Include position, velocity, sector, attachment, relevant flags, health, endurance and the dry-ground streak. The first mismatched field and tick or substep should locate a divergence. For the same binary and host we require exact equality of the recorded state. Include the exact step of the 38th consecutive grounded update. A successful landing alone cannot establish parity.
4. Time complete fixture runs with a monotonic clock. Retain all samples and report the spread along with the speed ratio. Scope the claim to this actor, case and build. Store large traces, build trees and owned level data outside this checkout.

## Full-match integration

Use one native host and two fighting peers. The Canyon Oasis scenario begins with a contested concussion rifle. Record acquisition, shot and damage events, continuation of the route, and respawn. Preserve seeds, actual per-seat inputs, delivery order and effective ticks of coaching interventions. Inspect event agreement at 1× and accelerated rates. Verify JKWeb recording separately before attributing native results to the browser build.

Gameplay deadlines, sensing, decisions and rewards follow simulation ticks. Transport health, worker startup and liveness use monotonic wall time. Retain world and life epochs at policy handover. Combine route movement and combat input at one explicit arbitration point so the player can take a shot without abandoning a supply route.

A single controller owns the seat. The coach supplies goals and can stage a revised executable policy or weights while the local player keeps acting. Bind source, external weights and imported dependencies to an identifiable revision. Probe each candidate, activate at an acknowledged safe tick and retain rollback. Close each reward window once, using the engine’s effective tick and counters. Count coached and autonomous runs separately. Evaluate learned corrections to the scripted baseline against held-out starts and opponents. This remains future work.

## Source and credit

Andrei directed the project and supplied competitive coaching. Lilitari built the competitive foundation and adaptive-player work. Red developed the movement and tactics branch. Coda and Lilitari chose the name and initial experiment together. Coda is integrating the new research tooling. Preserve upstream authorship and licensing as recorded in [NOTICE.md](../../../NOTICE.md).

The base headless client waits at [PR #1 native patch lines 6151–6161](https://github.com/CodaLilitari/jk-cross-server/blob/04d482ea760f0604c5fb9e66a6c5f854b1d4385a/native/bot-client.patch#L6151-L6161). The stock-water fixture has its own optional pacing loop. These are distinct clocks.
