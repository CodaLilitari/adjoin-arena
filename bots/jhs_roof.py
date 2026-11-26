"""Opt-in JKWeb coach routes to the JHS roof by the entrance transporter or middle-hall lift."""
import hashlib
import math

from manager.content import archive_index


# The controlled drills change only spawn assignments. Match the archive as well as its JKL
# because a different episode can replace the movement COGs independently.
VERIFIED = {
    ("a62c94789c521af2746cc8378301a4940a59a24f6fb44dd4c443caacc0211b04",
     "90e2641a58e0ec0102355dca9d3ec5eb55c4cbc9945a427227dcc8244885619d"): "original",
    ("647a3afc52516336b86a3e91dcd06daf880048b1b88ddf4acd028978c8a00abd",
     "3545ca4371edc8855e3b022237e172cda40389f1ae510afe51756cba8172cca1"): "hall-grate",
    ("b3bff7fb12f9c0cf28076b0e002cb317bde55fd77ce4578be11d965a86aa7065",
     "d6f578ba8cf1c016121a19065827fcbf1b43365f0a44d3662d542b76fb26d927"): "nearest-original",
    ("14744f3e32ef69d00d86fc5d99e14c984732023524ded360008e96114de77a0a",
     "cfb26514fceae289e3a9bd38f0b412f49b81d5be5c731ef8a223a9c079c32cad"): "entrance-original",
}


def episode_identity(path, level):
    if path is None or level.casefold() != "jhs.jkl":
        return {}
    entries = [row for row in archive_index(path) if row["name"].casefold() == "jkl/jhs.jkl"]
    if len(entries) != 1:
        return {}
    entry = entries[0]
    with path.open("rb") as stream:
        hasher = hashlib.sha256()
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
        archive_hash = hasher.hexdigest()
        stream.seek(entry["offset"])
        level_hash = hashlib.sha256(stream.read(entry["size"])).hexdigest()
    return {"episode_sha256": archive_hash, "map_sha256": level_hash}


def clamp(value, limit=1.0):
    return max(-limit, min(limit, value))


class RoofLift:
    @classmethod
    def from_session(cls, manifest, local, *, opportunistic=False):
        hosted = manifest.get("hosted") or {}
        room = local.get("hosted") or local.get("external") or {}
        keys = ("relay", "episode", "map", "episode_sha256", "map_sha256")
        if (not local.get("adaptive_lily") or not hosted or not all(k in hosted and room.get(k) == hosted[k] for k in keys)
                or (local.get("external") and room.get("id") != manifest.get("room_id"))):
            raise ValueError("The selected room must bind adaptive Lily to the same hosted JHS episode.")
        return cls(room, opportunistic=opportunistic)

    def __init__(self, room, *, opportunistic=False):
        self.identity = VERIFIED.get((room.get("episode_sha256"), room.get("map_sha256")))
        if not self.identity or room.get("map", "").lower() != "jhs.jkl" or room.get("seat") != "lily":
            raise ValueError("The roof coach requires adaptive Lily in a digest-verified JHS room.")
        self.fence = None
        self.active = False
        self.opportunistic = opportunistic
        self.riding = False
        self.counter = 0
        self.next_send = 0

    def update(self, seat, observation, now):
        fence = tuple(observation[k] for k in ("run_id", "world_epoch", "life_epoch"))
        if fence != self.fence:
            self.fence, self.active, self.attempts, self.retry_at = fence, False, 0, 0.0
            self.last_sample, self.queued_after, self.roof_samples = None, None, 0
            self.riding = False
        lily = observation.get("lily") or {}
        sense = lily.get("sense") or {}
        own = sense.get("self") or {}
        game = (observation.get("state") or {}).get("game_time")
        age = (lily.get("age_seconds") or {}).get("sense")
        # The private hosted manifest identifies the initial world only.
        valid = (fence[1] == 1 and observation.get("native_active") and seat.mode in ("auto", "lilivane")
                 and (not self.opportunistic or seat.mode == "lilivane")
                 and own.get("health", 0) > 0 and isinstance(age, (float, int)) and 0 <= age <= .5
                 and isinstance(game, (float, int)) and math.isfinite(game))
        if not valid:
            self.stop(seat, now, "handoff")
            self.riding = False
            return
        if self.last_sample == sense["sample_id"]:
            return
        self.last_sample = sense["sample_id"]
        x, y, z = sense["position"]
        sector = own["sector"]
        if z < .85 or sector not in (3, 7, 9, 16, 19, 0):
            self.riding = False
        if sector in (9, 16) and 1 < z < 4.2 and sense["supported"] and abs(x+.63) < .2:
            expected_y = -8.39 + (z-.155)*(3.795/4.36)
            if abs(y-expected_y) < .58:
                self.riding = True
        target = observation["state"].get("target") or {}
        threatened = own.get("hurt_recently") or (target.get("age", 10) <= .7 and target.get("position")
                                                  and math.dist(sense["position"], target["position"]) < 1.5)
        if threatened:
            self.stop(seat, now, "combat")
            return
        if not self.active:
            hall = sector == 79 and -.55 < x < .351 and abs(y + 3.023) < .45 and 2.72 < z < 3.01
            shuttle = (sector == 16 and abs(x+.63) < .15 and -5.17 < y < -4.18 and 4.46 <= z <= 4.57
                       and sense["supported"])
            entrance = (sector == 5 and -.87 < x < -.33 and -12.58 < y < -11.9 and .06 < z < .23
                        and sense["supported"])
            if self.opportunistic and not (self.riding and shuttle):
                return
            if not (self.attempts < 2 and now >= self.retry_at and (hall or shuttle or entrance)):
                return
            self.route = "entrance" if entrance else "shuttle" if shuttle else "grate"
            self.active, self.started, self.game_start = True, now, game
            self.attempts += 1
            self.queued_after, self.next_send, self.roof_samples = None, 0, 0
            seat.say("jhs_roof_start", content=self.identity, route=self.route,
                     attempt=self.attempts, sector=sector, game_time=game)
        if self.route == "entrance" and sector == 16 and z >= 4.46 and sense["supported"]:
            self.route, self.game_start = "shuttle", game
        allowed = {"grate": (79, 82, 30, 31, 0), "shuttle": (16, 19, 0), "entrance": (5, 7, 3, 9, 16)}
        departed = sector not in allowed[self.route] or (self.route == "shuttle" and z < 4.15)
        if now - self.started > 32 or game - self.game_start > (6 if self.route == "shuttle" else 30) or departed:
            self.stop(seat, now, "timeout_or_departure")
            return
        self.roof_samples = self.roof_samples + 1 if sector == 0 and z >= 4.545 and sense["supported"] else 0
        if self.roof_samples >= 2:
            self.attempts = 2
            self.stop(seat, now, "supported_roof")
            return
        seq = sense["action_seq"]
        if now < self.next_send or (sense["owner"] == "motor" and seq == self.queued_after):
            return
        if self.route == "entrance":
            step = self.entrance_step(sense)
        elif self.route == "shuttle":
            step = self.shuttle_step(sense)
        else:
            step = self.motor_step(sense, (game - self.game_start) % 11 < 4)
        self.counter += 1
        seat.request(seat.cred, "motor", dict(seat.lease, request_id=f"lily.{self.counter}", ttl_seconds=.85,
                                              sample_id=sense["sample_id"], revision=1, steps=[step]))
        self.next_send = now + .065
        if sense["owner"] == "motor":
            self.queued_after = seq

    def stop(self, seat, now, reason):
        if self.active:
            self.active = False
            self.riding = False
            self.retry_at = now + 20
            seat.say("jhs_roof_end", reason=reason)

    @staticmethod
    def entrance_step(sense):
        x, y, z = sense["position"]
        sector = sense["self"]["sector"]
        fx, fy, _ = sense["facing"]
        length = max(.0001, math.hypot(fx, fy))
        fx, fy = fx/length, fy/length
        if sector in (9, 16) and .85 < z < 4.46:
            # The transport travels linearly between its two authored frames.
            # An aft boarding position leaves too little time at the upper stop.
            # The stock mesh extends over .50 beyond its origin in +Y.
            # Aim inside that edge so the final hop clears both rooftop lips.
            desired_y = -8.39 + (z-.155)*(3.795/4.36) + .32
            ahead = desired_y-y
            wx = clamp(4*(-.63-x), .33)
            wy = clamp(max(0., ahead)*3.5, .73)
            hop = ahead > .17 and sense["supported"]
            return {"duration_ms": 145, "forward": clamp(wx*fx+wy*fy), "strafe": clamp(wx*fy-wy*fx),
                    "buttons": int(hop)}
        if sector not in (5, 7) or (sector == 7 and y > -8.97 and z > .155 and sense["supported"]):
            return {"duration_ms": 145}
        centre = -.605 if sector == 5 else -.63
        vx, vy, _ = sense["velocity"]
        wx = clamp(6*(centre-x)-.38*vx, .7)
        wy = clamp(3*(-8.183-y)-.3*vy, .68) if abs(centre-x) < .095 else 0.0
        return {"duration_ms": 145, "forward": clamp(wx*fx+wy*fy), "strafe": clamp(wx*fy-wy*fx)}

    @staticmethod
    def shuttle_step(sense):
        x, y, _ = sense["position"]
        fx, fy, _ = sense["facing"]
        length = max(.0001, math.hypot(fx, fy))
        fx, fy = fx/length, fy/length
        wx = clamp(4*(-.63-x)-.25*sense["velocity"][0], .45)
        # Both the raised parts of the moving model and the final rooftop lip
        # can stop a walking actor. Start hopping from the aft upper deck.
        jump = sense["supported"] and y >= -5.17 and sense["self"]["sector"] in (16, 19)
        return {"duration_ms": 145, "forward": clamp(wx*fx+fy), "strafe": clamp(wx*fy-fx),
                "buttons": int(jump)}

    @staticmethod
    def motor_step(sense, cut):
        x, y, _ = sense["position"]
        sector = sense["self"]["sector"]
        step = {"duration_ms": 145}
        if sector in (31, 0) or (sector == 30 and abs(x-.515) < .074 and abs(y+3.023) < .074):
            return step
        target_x = .17 if cut and sector == 79 else .515
        if sector == 79 and x > .1 and abs(y+3.023) > .045:
            target_x = .12
        vx, vy, _ = sense["velocity"]
        wx, wy = clamp(5*(target_x-x)-.32*vx, .9), clamp(6*(-3.023-y)-.32*vy, .9)
        fx, fy, _ = sense["facing"]
        length = max(.0001, math.hypot(fx, fy))
        fx, fy = fx/length, fy/length
        dx, dy = .35-x, -3.023-y
        yaw = -math.atan2(dx*fy-dy*fx, dx*fx+dy*fy)
        step.update(forward=clamp(wx*fx+wy*fy), strafe=clamp(wx*fy-wy*fx),
                    turn=clamp(.52*yaw, .72) if cut else 0, pitch=clamp(-sense["head_pitch"]/45, .55),
                    buttons=16 if cut else 0)
        if cut and sector == 79:
            step["weapon"] = 10
        return step
