/* Local controlled experiment: place once after graph creation, choose a
   stock graph objective, then exercise inputs, physics, mover COG and TAKEN. */
if ((scenario == 13 || scenario == 14) && bot.graphDone) {
    static int placed, frame, firstLife, phase = -1, entry = -1, landing = -1;
    int item = scenario;
    int thingIndex = item == 13 ? 5 : 6;
    int ilift = -1;
    for (int i = 0; i < nav.liftCount; i++)
        if (nav.lifts[i].thing == thingIndex)
            ilift = i;
    if (ilift >= 0 && bot.world && !dead && (item == 13 || item == 14)) {
        BotLift *lift = &nav.lifts[ilift];
        SithThing *deck = Bot_NavThing(thingIndex);
        int bottom = lift->node[0], top = lift->node[1];
        if (bot.nodes[bottom].pos.z > bot.nodes[top].pos.z) {
            int swap = bottom;
            bottom = top;
            top = swap;
        }
        if (!placed) {
            for (int i = 0; i < bot.nodes[bottom].nEdges; i++) {
                int n = bot.nodes[bottom].edges[i].to;
                fprintf(stderr, "REPLAY_EDGE from=%d to=%d item=%d sector=%u x=%.3f y=%.3f z=%.3f\n",
                        bottom, n, bot.nodes[n].item, bot.nodes[n].sector->id, bot.nodes[n].pos.x,
                        bot.nodes[n].pos.y, bot.nodes[n].pos.z);
                if (bot.nodes[n].item == item)
                    entry = n;
                if (landing < 0 && !nav.liftForNode[n] &&
                    fabsf(bot.nodes[n].pos.z - bot.nodes[bottom].pos.z) < 0.07f)
                    landing = n;
            }
            if (landing < 0) {
                fprintf(stderr, "REPLAY_NO_LANDING\n");
                abort();
            }
            rdVector3 start = bot.nodes[landing].pos;
            start.z += 0.005f;
            sithThing_DetachThing(self);
            sithThing_SetPositionAndOrient(self, &start, &self->orient);
            sithThing_SetSector(self, Bot_SectorAt(&start, deck->sector), 0);
            self->physicsParams.vel = (rdVector3){0};
            placed = 1;
            firstLife = red.life;
        }
        extern int replayLastTaken;
        int got = replayLastTaken == item;
        if (entry >= 0 && red.life == firstLife) {
            if (phase == -1 && self->attachedThing == deck)
                phase = 0;
            if (!phase && got) {
                phase = 1;
                fprintf(stderr, "REPLAY_PICKUP item=%d sector=%u life=%d\n", item, self->sector->id,
                        red.life);
            }
            if (phase == 1 && self->attachedThing == deck &&
                Bot_Horizontal(Bot_Sub(self->position, deck->position)) < 0.08f &&
                fabsf(self->position.z - bot.nodes[entry].pos.z) > 0.35f) {
                phase = 2;
                fprintf(stderr, "REPLAY_ESCAPED item=%d sector=%u life=%d\n", item, self->sector->id,
                        red.life);
            }
            if (phase == 2 && self->sector != bot.nodes[entry].sector && self->sector != deck->sector &&
                (self->attach_flags & SITH_ATTACH_SURFACE)) {
                phase = 3;
                fprintf(stderr, "REPLAY_SAFE_EXIT item=%d life=%d sec=%u hp=%.2f\n", item, red.life,
                        self->sector->id, self->actorParams.health);
            }
            if (phase <= 1 && !(phase == 1 && self->attachedThing == deck)) {
                bot.axes[INPUT_FUNC_FORWARD] = bot.axes[INPUT_FUNC_SLIDE] = 0;
                bot.keys[INPUT_FUNC_FAST] = bot.keys[INPUT_FUNC_JUMP] = 0;
                Bot_LiftMove(self,
                             phase == -1  ? landing
                             : phase == 1 ? entry
                                          : bottom,
                             phase == -1 || phase == 1 ? bottom : entry);
                Bot_GuardGround(self);
            }
        }
        if (frame++ % 8 == 0)
            fprintf(stderr,
                    "REPLAY_STATE entry=%d phase=%d life=%d sec=%u hp=%.1f attach=%d deck=%d z=%.4f "
                    "xyz=%.4f,%.4f,%.4f axes=%.2f,%.2f step=%d wait=%.2f\n",
                    entry, phase, red.life, self->sector->id, self->actorParams.health,
                    self->attach_flags, self->attachedThing == deck, deck->position.z, self->position.x,
                    self->position.y, self->position.z, bot.axes[INPUT_FUNC_FORWARD],
                    bot.axes[INPUT_FUNC_SLIDE], nav.liftStep, nav.liftWaitAt);
    }
}
