if (scenario == 69 && bot.graphDone && !dead) {
    /* Stock m4 face 1835, edge between vertices 1398 and 1397.
       Positive distance is on the shaft side; negative is on the rim. */
    const rdVector3 edge = {0.3881925f, -0.4102375f, 1.753f}, inward = {0.7071f, 0.7071f, 0};
    static int state, firstLife, samples, brakes;
    static flex_t began, deepest, minZ;
    bot.axes[INPUT_FUNC_TURN] = bot.axes[INPUT_FUNC_PITCH] = bot.rawPitch = bot.rawTurn = 0;
    rdVector3 rel = Bot_Sub(self->position, edge);
    flex_t dist = Bot_Dot(rel, inward);
    if (!state) {
        rdVector3 start = {edge.x - inward.x * 0.13f, edge.y - inward.y * 0.13f,
                           edge.z + BOT_FOOT_HEIGHT + 0.003f};
        rdMatrix34 basis = self->orient;
        basis.rvec = (rdVector3){1, 0, 0};
        basis.lvec = (rdVector3){0, 1, 0};
        basis.uvec = (rdVector3){0, 0, 1};
        sithThing_DetachThing(self);
        sithThing_SetPositionAndOrient(self, &start, &basis);
        sithThing_SetSector(self, Bot_SectorAt(&start, bot.world->surfaces[1835].pSector), 0);
        self->physicsParams.vel = (rdVector3){0};
        state = 1;
        firstLife = red.life;
        minZ = start.z;
    } else if (state == 1 && (self->attach_flags & SITH_ATTACH_SURFACE)) {
        self->physicsParams.vel = (rdVector3){inward.x * 1.25f, inward.y * 1.25f, 0};
        began = bot.now;
        state = 2;
        deepest = dist;
        fprintf(stderr, "RIM_BEGIN distance=%.4f z=%.4f sector=%u life=%d\n", dist, self->position.z,
                self->sector->id, red.life);
    }
    if (state <= 2) {
        bot.keys[INPUT_FUNC_JUMP] = bot.keys[INPUT_FUNC_FAST] = 0;
        bot.axes[INPUT_FUNC_FORWARD] = bot.axes[INPUT_FUNC_SLIDE] = 0;
        if (state == 2) {
            if (bot.now - began < 0.45f)
                Bot_ThrustAxes(self, (rdVector3){inward.y, -inward.x, 0}, 0);
            flex_t f = bot.axes[INPUT_FUNC_FORWARD], s = bot.axes[INPUT_FUNC_SLIDE];
            if (!getenv("ADJOIN_VETO_OFF"))
                Bot_GuardGround(self);
            if (fabsf(f - bot.axes[INPUT_FUNC_FORWARD]) + fabsf(s - bot.axes[INPUT_FUNC_SLIDE]) > 0.05f)
                brakes++;
        }
        if (state == 2) {
            deepest = Bot_Max(dist, deepest);
            minZ = Bot_Min(self->position.z, minZ);
            samples++;
            if (bot.now - began >= 1.1f) {
                fprintf(stderr,
                        "RIM_END min_z=%.4f deepest=%.4f final_depth=%.4f z=%.4f sector=%u attach=%d "
                        "brakes=%d hp=%.2f start_life=%d life=%d samples=%d\n",
                        minZ, deepest, dist, self->position.z, self->sector->id, self->attach_flags,
                        brakes, self->actorParams.health, firstLife, red.life, samples);
                state = 3;
            }
        }
    }
}
