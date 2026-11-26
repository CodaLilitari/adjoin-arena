if (scenario == 48 && bot.graphDone && !dead) {
    static int state, firstLife, vetoes, nframe;
    static flex_t hp;
    int id = 0;
    for (int i = 0; i < nav.liftCount; i++)
        if (nav.lifts[i].thing == 48)
            id = i + 1;
    if (id) {
        BotLift *lift = &nav.lifts[id - 1];
        SithThing *deck = Bot_NavThing(lift->thing);
        int bottom = lift->node[0], top = lift->node[1];
        if (bot.nodes[top].pos.z < bot.nodes[bottom].pos.z) {
            int v = bottom;
            bottom = top;
            top = v;
        }
        if (!state) {
            rdVector3 start = bot.nodes[bottom].pos;
            start.z += 0.008f;
            start.x += 0.072f;
            sithThing_DetachThing(self);
            sithThing_SetPositionAndOrient(self, &start, &self->orient);
            sithThing_SetSector(self, Bot_SectorAt(&start, deck->sector), 0);
            self->physicsParams.vel = (rdVector3){0};
            state = 1;
            firstLife = red.life;
        }
        if (state == 1) {
            bot.keys[INPUT_FUNC_JUMP] = 0;
            bot.axes[INPUT_FUNC_FORWARD] = bot.axes[INPUT_FUNC_SLIDE] = 0;
            Bot_LiftPress(self, lift, id, 1);
            if (deck->position.z > deck->trackParams.aFrames[1].pos.z - 0.025f) {
                int landing = -1;
                const BotNode *n = &bot.nodes[bottom];
                for (int j = 0; j < n->nEdges; j++) {
                    int p = n->edges[j].to;
                    if (nav.liftForNode[p] || fabsf(bot.nodes[p].pos.z - n->pos.z) > 0.08f)
                        continue;
                    if (Bot_Horizontal(Bot_Sub(n->pos, bot.nodes[p].pos)) < 0.20f)
                        continue;
                    landing = p;
                    break;
                }
                if (landing < 0) {
                    fprintf(stderr, "NAR_NO_LANDING\n");
                    abort();
                }
                rdVector3 start = bot.nodes[landing].pos;
                start.z += 0.003f;
                sithThing_DetachThing(self);
                sithThing_SetPositionAndOrient(self, &start, &self->orient);
                sithThing_SetSector(self, bot.nodes[landing].sector, 0);
                self->physicsParams.vel = (rdVector3){0};
                hp = self->actorParams.health;
                fprintf(stderr,
                        "NAR_APPROACH start=%.4f,%.4f,%.4f sector=%u deck_z=%.3f health=%.3f life=%d\n",
                        start.x, start.y, start.z, self->sector->id, deck->position.z, hp, red.life);
                state = 2;
            }
        }
        if (state == 2) {
            rdVector3 dir = Bot_Sub(deck->position, self->position);
            Bot_ThrustAxes(self, dir, 0);
            bot.keys[INPUT_FUNC_FAST] = bot.keys[INPUT_FUNC_JUMP] = 0;
            flex_t oldF = bot.axes[INPUT_FUNC_FORWARD], oldS = bot.axes[INPUT_FUNC_SLIDE];
            if (!getenv("ADJOIN_VETO_OFF"))
                Bot_GuardGround(self);
            if (fabsf(oldF - bot.axes[INPUT_FUNC_FORWARD]) + fabsf(oldS - bot.axes[INPUT_FUNC_SLIDE]) >
                0.05f)
                vetoes++;
            if (deck->position.z < deck->trackParams.aFrames[0].pos.z + 0.008f) {
                fprintf(stderr,
                        "NAR_RETURNED vetoes=%d hp_before=%.3f hp_after=%.3f start_life=%d life=%d "
                        "sector=%u offset=%.4f,%.4f\n",
                        vetoes, hp, self->actorParams.health, firstLife, red.life, self->sector->id,
                        self->position.x - deck->position.x, self->position.y - deck->position.y);
                state = 3;
            }
        }
        if (nframe++ % 10 == 0)
            fprintf(stderr,
                    "NAR_STATE state=%d z=%.4f pos=%.4f,%.4f,%.4f hp=%.3f f=%.3f s=%.3f, a=%d sec=%u\n",
                    state, deck->position.z, self->position.x, self->position.y, self->position.z,
                    self->actorParams.health, bot.axes[INPUT_FUNC_FORWARD], bot.axes[INPUT_FUNC_SLIDE],
                    self->attach_flags, self->sector->id);
    }
}
