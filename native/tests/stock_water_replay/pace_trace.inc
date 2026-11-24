/* Optional parity evidence. This is a fixture observer, including on death when
   the stock loop ends a step early. Write stable indices and hexadecimal floats
   so two invocations of the same binary can be compared without a tolerance. */
static FILE *paceTrace;

static void pace_io_error(const char *operation)
{
    perror(operation);
    exit(2);
}

static void pace_begin(int keepPlaying)
{
    const char *path = getenv("LILY_PACE_TRACE");
    if (!path) return;
    if (keepPlaying) {
        fputs("LILY_PACE_TRACE requires stopping at the first terminal.\n", stderr);
        exit(2);
    }
    paceTrace = fopen(path, "wx");
    if (!paceTrace) pace_io_error("open LILY_PACE_TRACE");
}

static void pace_row(const SithThing *me, const char *kind, const char *stage,
                     int tick, int step, int streak, const char *result)
{
    if (!paceTrace) return;
    const SithSurface *floor = (me->attach_flags & SITH_ATTACH_SURFACE)
                               ? me->attachedSurface : NULL;
    int attached_sector = floor && floor->pSector ? (int)floor->pSector->id : -1;
    int attached_surface = floor ? (int)(floor - bot.world->surfaces) : -1;
#ifdef BANK_EVALUATION
    const char *owner = bankOwner;
#else
    const char *owner = "unobserved";
#endif
    if (fprintf(paceTrace,
        "{\"kind\":\"%s\",\"stage\":\"%s\",\"tick\":%d,\"step\":%d,\"streak\":%d,"
        "\"sector\":%u,\"attached_sector\":%d,\"attached_surface\":%d,"
        "\"attach_flags\":%u,\"physics_flags\":%u,\"actor_flags\":%u,\"thing_flags\":%u,"
        "\"endurance\":%d,\"wet\":%s,\"water_surface\":%s,\"owner\":\"%s\","
        "\"position\":[\"%a\",\"%a\",\"%a\"],\"velocity\":[\"%a\",\"%a\",\"%a\"],"
        "\"facing\":[\"%a\",\"%a\",\"%a\"],\"up\":[\"%a\",\"%a\",\"%a\"],"
        "\"head_pitch\":\"%a\",\"health\":\"%a\"",
        kind, stage, tick, step, streak, (unsigned)me->sector->id, attached_sector,
        attached_surface, (unsigned)me->attach_flags, (unsigned)me->physicsParams.flags,
        (unsigned)me->actorParams.flags, (unsigned)me->flags, (int)me->actorParams.endurance,
        me->sector->flags & SITH_SECTOR_UNDERWATER ? "true" : "false",
        me->physicsParams.flags & SITH_PF_ONWATERSURFACE ? "true" : "false", owner,
        (double)me->position.x, (double)me->position.y, (double)me->position.z,
        (double)me->physicsParams.vel.x, (double)me->physicsParams.vel.y, (double)me->physicsParams.vel.z,
        (double)me->orient.lvec.x, (double)me->orient.lvec.y, (double)me->orient.lvec.z,
        (double)me->orient.uvec.x, (double)me->orient.uvec.y, (double)me->orient.uvec.z,
        (double)me->actorParams.headPYR.x, (double)me->actorParams.health) < 0)
        pace_io_error("write LILY_PACE_TRACE");
    if (result && fprintf(paceTrace, ",\"result\":\"%s\"", result) < 0)
        pace_io_error("write LILY_PACE_TRACE result");
    if (fputs("}\n", paceTrace) == EOF) pace_io_error("write LILY_PACE_TRACE row");
    if (result) {
        if (fclose(paceTrace) != 0) pace_io_error("close LILY_PACE_TRACE");
        paceTrace = NULL;
    }
}
